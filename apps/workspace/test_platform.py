import io
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import CommandError, call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.campaigns.models import Campaign, Membership, Tenant
from apps.core.models import AuditEvent
from apps.core.rls import database_scope
from .models import FieldWorker, SecurityProfile
from .platform_services import (
    create_customer,
    open_campaign,
    set_tenant_status,
    set_user_status,
)


class PlatformTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            "platform-test", "", "Test-only-Admin-854!"
        )
        self.customer_args = dict(
            actor=self.admin,
            organization="Cliente sintético",
            slug="synthetic",
            campaign_name="Campanha sintética",
            username="synthetic.manager",
            password="Test-only-Customer-267!",
            election_id="DEMO",
            office_code="administrativo",
            jurisdiction_code="DEMO",
            is_demo=True,
        )
        self.tenant, self.campaign, self.customer, self.member = create_customer(
            **self.customer_args
        )
        self.client.force_login(self.admin)

    def customer_login(self):
        SecurityProfile.objects.filter(user=self.customer).update(
            password_change_required=False
        )
        self.client.force_login(self.customer)

    def test_platform_requires_both_superuser_and_staff_and_active(self):
        self.client.logout()
        self.assertEqual(
            self.client.get(reverse("platform_dashboard")).status_code, 302
        )
        self.customer_login()
        for path in ("/plataforma/", "/admin/", "/plataforma/clientes/novo/"):
            self.assertEqual(self.client.get(path).status_code, 403)
        self.admin.is_staff = False
        self.admin.save()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/admin/").status_code, 403)

    def test_admin_dashboard_and_home(self):
        self.assertRedirects(self.client.get("/"), reverse("platform_dashboard"))
        response = self.client.get(reverse("platform_dashboard"))
        self.assertContains(response, "Cliente sintético")
        self.assertContains(response, "synthetic.manager")
        self.assertNotContains(response, self.customer_args["password"])
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_customer_creation_nonprivileged_and_forces_password_change(self):
        self.assertFalse(self.customer.is_staff)
        self.assertFalse(self.customer.is_superuser)
        self.assertTrue(self.customer.securityprofile.password_change_required)
        self.assertTrue(self.customer.check_password(self.customer_args["password"]))
        self.assertTrue(self.campaign.is_demo)
        self.assertGreater(self.member.role.permissions.count(), 0)

    def test_create_customer_ui_and_atomic_validation(self):
        payload = {
            key: value for key, value in self.customer_args.items() if key != "actor"
        }
        payload.update(
            slug="another", username="another.manager", organization="Outro cliente"
        )
        self.assertRedirects(
            self.client.post(reverse("platform_customer_create"), payload),
            reverse("platform_dashboard"),
        )
        payload.update(slug="no-partial", password="weak")
        self.assertEqual(
            self.client.post(reverse("platform_customer_create"), payload).status_code,
            200,
        )
        self.assertFalse(Tenant.objects.filter(slug="no-partial").exists())
        with self.assertRaises(ValidationError):
            create_customer(**dict(self.customer_args, slug="duplicate-user"))
        self.assertFalse(Tenant.objects.filter(slug="duplicate-user").exists())

    def test_admin_campaign_access_is_explicit_and_audited(self):
        self.assertFalse(
            Membership.objects.filter(user=self.admin, campaign=self.campaign).exists()
        )
        self.assertEqual(
            self.client.get(reverse("dashboard", args=[self.campaign.pk])).status_code,
            404,
        )
        url = reverse("platform_campaign_open", args=[self.campaign.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(
            self.client.post(url), reverse("dashboard", args=[self.campaign.pk])
        )
        self.assertTrue(
            Membership.objects.get(user=self.admin, campaign=self.campaign).is_effective
        )
        with database_scope(campaign=self.campaign, actor=self.admin):
            self.assertTrue(
                AuditEvent.objects.filter(
                    campaign=self.campaign, action="platform.campaign_opened"
                ).exists()
            )

    def test_customer_cannot_open_another_campaign_or_create_clients(self):
        self.customer_login()
        self.assertEqual(
            self.client.post(
                reverse("platform_campaign_open", args=[self.campaign.pk])
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(reverse("platform_customer_create"), {}).status_code, 403
        )
        with self.assertRaises(PermissionDenied):
            create_customer(
                **dict(self.customer_args, actor=self.customer, slug="forbidden")
            )

    def test_changes_require_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        self.assertEqual(
            csrf_client.post(
                reverse("platform_campaign_open", args=[self.campaign.pk])
            ).status_code,
            403,
        )

    def test_suspended_tenant_denies_campaign_and_opening(self):
        set_tenant_status(actor=self.admin, tenant=self.tenant, status="suspended")
        with self.assertRaises(ValidationError):
            open_campaign(actor=self.admin, campaign=self.campaign)
        self.customer_login()
        self.assertEqual(
            self.client.get(reverse("dashboard", args=[self.campaign.pk])).status_code,
            404,
        )

    def test_user_suspension_revokes_sessions_and_protects_admin(self):
        self.customer_login()
        version = SecurityProfile.objects.get(user=self.customer).session_version
        set_user_status(actor=self.admin, user=self.customer, active=False)
        self.assertEqual(
            SecurityProfile.objects.get(user=self.customer).session_version, version + 1
        )
        self.assertFalse(self.client.get("/").wsgi_request.user.is_authenticated)
        with self.assertRaises(ValidationError):
            set_user_status(actor=self.admin, user=self.admin, active=False)

    @override_settings(MFA_REQUIRED=True)
    def test_superadmin_has_no_mfa_bypass(self):
        self.assertRedirects(self.client.get("/plataforma/"), reverse("security"))

    @override_settings(LOCAL_DEMO=False)
    def test_isolated_demo_is_labeled_without_global_demo_mode(self):
        self.customer_login()
        self.assertContains(
            self.client.get(reverse("dashboard", args=[self.campaign.pk])),
            "Dados fictícios",
        )


class ProductBootstrapTests(TestCase):
    def bootstrap(self, credentials=None):
        stream = io.StringIO()
        credentials = credentials or {
            "admin_password": "Test-only-Initial-Administrator-583!",
            "demo_password": "Test-only-Initial-Demonstration-476!",
        }
        with patch("sys.stdin", io.StringIO(json.dumps(credentials))):
            call_command(
                "bootstrap_product_access",
                admin_username="new.admin",
                demo_username="new.demo",
                credentials_stdin=True,
                stdout=stream,
            )
        return stream.getvalue()

    def test_bootstrap_scoped_demo_two_distinct_accounts_no_overwrite(self):
        output = self.bootstrap()
        admin, demo = (
            User.objects.get(username="new.admin"),
            User.objects.get(username="new.demo"),
        )
        campaign = Campaign.objects.get(is_demo=True)
        self.assertTrue(admin.is_staff and admin.is_superuser)
        self.assertFalse(demo.is_staff or demo.is_superuser)
        self.assertTrue(admin.securityprofile.password_change_required)
        self.assertTrue(demo.securityprofile.password_change_required)
        self.assertIsNone(admin.securityprofile.enabled_at)
        with database_scope(campaign=campaign, actor=demo):
            self.assertEqual(FieldWorker.objects.filter(campaign=campaign).count(), 3)
        self.assertNotIn("Test-only", output)
        with self.assertRaises(CommandError):
            self.bootstrap()
        self.assertEqual(User.objects.count(), 2)
        self.assertEqual(Tenant.objects.count(), 1)

    def test_equal_or_weak_passwords_create_nothing(self):
        for credentials in (
            {"admin_password": "same", "demo_password": "same"},
            {
                "admin_password": "Test-only-Strong-Administrator!",
                "demo_password": "weak",
            },
        ):
            with self.assertRaises(CommandError):
                self.bootstrap(credentials)
            self.assertFalse(User.objects.exists())
            self.assertFalse(Tenant.objects.exists())
