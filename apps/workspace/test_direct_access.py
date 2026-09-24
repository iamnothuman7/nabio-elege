import io
import json
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from apps.campaigns.models import Membership, Tenant
from apps.core.crypto import encrypt_json
from apps.core.models import AuditEvent
from apps.core.rls import database_scope
from .direct_access import prepare_direct_access
from .models import CampaignProfile, FieldWorker, SecurityProfile, Territory
from .platform_services import create_customer
from .security import PASSWORD_ONLY_GROUP, requires_second_factor


@override_settings(MFA_REQUIRED=True)
class DirectAccessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            "owner.test", "", "Old-Admin-Test-853!"
        )
        self.tenant, self.demo, self.customer, self.member = create_customer(
            actor=self.admin,
            organization="Synthetic",
            slug="synthetic",
            campaign_name="Demo",
            username="customer.demo",
            password="Old-Customer-Test-738!",
            election_id="DEMO",
            office_code="test",
            jurisdiction_code="DEMO",
            is_demo=True,
        )
        with database_scope(campaign=self.demo, actor=self.customer):
            territory = Territory.objects.create(
                tenant=self.tenant,
                campaign=self.demo,
                created_by=self.customer,
                name="Synthetic territory",
                municipality="Fortaleza",
                state="CE",
                coordinator=self.member,
            )
            self.worker = FieldWorker.objects.create(
                tenant=self.tenant,
                campaign=self.demo,
                created_by=self.customer,
                name="Fictitious worker",
                function="volunteer",
                territory=territory,
                supervisor=self.member,
                onboarding_reference="TEST-SYNTHETIC",
            )
        self.options = dict(
            admin_username=self.admin.username,
            customer_username=self.customer.username,
            new_customer_username="customer.real",
            admin_password="New-Owner-Test-9837!abc",
            customer_password="New-Customer-Test-826!def",
            tenant_slug="real-client",
            customer_name="Test client",
        )

    def prepare(self, **overrides):
        return prepare_direct_access(**(self.options | overrides))

    def login(self, username, password):
        client = Client()
        response = client.post(
            "/entrar/", {"username": username, "password": password}, follow=True
        )
        return client, response

    def test_password_only_login_reaches_both_dashboards(self):
        campaign = self.prepare()
        owner, response = self.login(
            self.admin.username, self.options["admin_password"]
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "opcional · acesso por senha")
        self.assertEqual(response.redirect_chain, [("/", 302), ("/plataforma/", 302)])
        customer, response = self.login(
            "customer.real", self.options["customer_password"]
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.redirect_chain, [("/", 302), (f"/c/{campaign.pk}/", 302)]
        )
        self.assertEqual(customer.get("/plataforma/").status_code, 403)
        self.assertEqual(customer.get(f"/c/{self.demo.pk}/").status_code, 404)
        self.assertEqual(customer.get("/api/v1/campaigns").status_code, 200)
        self.assertEqual(owner.get("/plataforma/atividade/").status_code, 200)

    def test_conversion_preserves_demo_and_starts_empty(self):
        campaign = self.prepare()
        self.assertFalse(campaign.is_demo)
        self.assertNotEqual(campaign.tenant_id, self.tenant.pk)
        with database_scope(campaign=campaign, actor=self.customer):
            self.assertFalse(FieldWorker.objects.filter(campaign=campaign).exists())
            self.assertEqual(
                CampaignProfile.objects.get(campaign=campaign).candidate_name,
                "Test client",
            )
        with database_scope(campaign=self.demo, actor=self.customer):
            self.assertTrue(FieldWorker.objects.filter(pk=self.worker.pk).exists())
        self.demo.refresh_from_db()
        self.assertTrue(self.demo.is_demo)
        self.member.refresh_from_db()
        self.assertEqual(self.member.status, "revoked")
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_staff or self.customer.is_superuser)
        self.assertFalse(User.objects.filter(username="customer.demo").exists())
        new_member = Membership.objects.get(user=self.customer, campaign=campaign)
        self.assertEqual(
            set(new_member.role.permissions.all()),
            set(self.member.role.permissions.all()),
        )

    def test_old_passwords_sessions_and_factor_are_revoked(self):
        previous = Client()
        previous.force_login(self.customer)
        profile = SecurityProfile.objects.get(user=self.customer)
        profile.enabled_at = timezone.now()
        profile.totp_secret_ciphertext = encrypt_json({"secret": "JBSWY3DPEHPK3PXP"})
        profile.recovery_hashes = ["old-code"]
        profile.save()
        self.prepare()
        self.assertFalse(previous.get("/").wsgi_request.user.is_authenticated)
        self.customer.refresh_from_db()
        profile.refresh_from_db()
        self.assertFalse(self.customer.check_password("Old-Customer-Test-738!"))
        self.assertIsNone(profile.enabled_at)
        self.assertEqual(bytes(profile.totp_secret_ciphertext), b"")
        self.assertEqual(profile.recovery_hashes, [])
        self.assertFalse(profile.password_change_required)

    def test_unrelated_accounts_still_require_mfa_and_cannot_self_exempt(self):
        user = User.objects.create_user(
            "unrelated", password="Other-Password-Test-298!"
        )
        client, response = self.login(user.username, "Other-Password-Test-298!")
        self.assertEqual(response.redirect_chain, [("/seguranca/", 302)])
        self.prepare()
        profile = SecurityProfile.objects.get(user=user)
        self.assertTrue(requires_second_factor(user, profile))
        response = client.post(
            "/entrar/",
            {
                "username": user.username,
                "password": "Other-Password-Test-298!",
                "mfa_optional": "true",
                "group": PASSWORD_ONLY_GROUP,
            },
        )
        self.assertEqual(response.url, "/seguranca/")
        self.assertFalse(user.groups.filter(name=PASSWORD_ONLY_GROUP).exists())

    def test_optional_factor_page_and_activation_keep_future_factor_checks(self):
        self.prepare()
        client, _ = self.login("customer.real", self.options["customer_password"])
        self.assertContains(client.get("/seguranca/"), "Voltar ao meu painel")
        profile = SecurityProfile.objects.get(user=self.customer)
        profile.enabled_at = timezone.now()
        profile.save()
        self.assertTrue(requires_second_factor(self.customer, profile))
        self.assertEqual(client.get("/").url, "/seguranca/")
        self.assertEqual(client.get("/api/v1/campaigns").json()["code"], "mfa_required")

    def test_voluntary_password_change_returns_to_panel_without_factor(self):
        self.prepare()
        client, _ = self.login("customer.real", self.options["customer_password"])
        response = client.post(
            "/senha/",
            {
                "old_password": self.options["customer_password"],
                "new_password1": "Another-Test-Password-462!",
                "new_password2": "Another-Test-Password-462!",
            },
        )
        self.assertEqual(response.url, "/")

    def test_weak_duplicate_or_colliding_credentials_roll_back(self):
        for overrides in (
            {"customer_password": "weak"},
            {"customer_password": self.options["admin_password"]},
            {"new_customer_username": self.admin.username},
            {"tenant_slug": self.tenant.slug},
        ):
            with (
                self.subTest(overrides=list(overrides)),
                self.assertRaises(ValidationError),
            ):
                self.prepare(**overrides)
            self.assertFalse(Tenant.objects.filter(slug="real-client").exists())
            self.customer.refresh_from_db()
            self.assertEqual(self.customer.username, "customer.demo")
            self.assertTrue(self.customer.check_password("Old-Customer-Test-738!"))
        self.assertFalse(Group.objects.filter(name=PASSWORD_ONLY_GROUP).exists())

    def test_non_demo_refuses_conversion(self):
        self.demo.is_demo = False
        self.demo.save()
        with self.assertRaises(ValidationError):
            self.prepare()
        self.assertFalse(Tenant.objects.filter(slug="real-client").exists())

    def test_reexecution_refused_and_audit_has_no_secrets(self):
        self.prepare()
        with self.assertRaises(ValidationError):
            self.prepare()
        with database_scope(actor=self.admin):
            events = list(
                AuditEvent.objects.filter(
                    action="security.password_only_access_configured"
                ).values("minimized_diff", "reason")
            )
            self.assertEqual(len(events), 2)
            self.assertNotIn(self.options["admin_password"], json.dumps(events))
            self.assertNotIn(self.options["customer_password"], json.dumps(events))

    def test_csrf_and_rate_limit_still_enforced(self):
        self.prepare()
        payload = {
            "username": "customer.real",
            "password": self.options["customer_password"],
        }
        self.assertEqual(
            Client(enforce_csrf_checks=True).post("/entrar/", payload).status_code, 403
        )
        client = Client()
        for _ in range(5):
            client.post("/entrar/", payload | {"password": "wrong"})
        self.assertEqual(client.post("/entrar/", payload).status_code, 200)
        self.assertNotIn("_auth_user_id", client.session)

    def test_command_rejects_bad_json_without_secret_in_output(self):
        options = {
            key: value
            for key, value in self.options.items()
            if not key.endswith("password")
        }
        with patch("sys.stdin", io.StringIO('{"admin_password": "DO-NOT-ECHO"}')):
            with self.assertRaises(CommandError) as caught:
                call_command(
                    "prepare_direct_access",
                    **options,
                    passwords_stdin=True,
                    confirm_password_only=True,
                )
        self.assertNotIn("DO-NOT-ECHO", str(caught.exception))
