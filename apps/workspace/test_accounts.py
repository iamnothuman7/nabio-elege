import io
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command, CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.campaigns.models import Membership, Permission, Tenant
from apps.core.crypto import encrypt_json, hash_token
from apps.core.models import AuditEvent
from .models import SecurityProfile


class PasswordLifecycleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "operator", password="Initial-Secret-2026!"
        )
        self.profile = SecurityProfile.objects.create(
            user=self.user, password_change_required=True
        )
        self.client.force_login(self.user)
        self.payload = {
            "old_password": "Initial-Secret-2026!",
            "new_password1": "Different-New-Secret-2026!",
            "new_password2": "Different-New-Secret-2026!",
        }

    def test_required_password_blocks_html_and_private_api_but_not_health(self):
        self.assertRedirects(self.client.get("/"), reverse("password_change"))
        response = self.client.get("/api/v1/campaigns")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "password_change_required")
        self.assertEqual(self.client.get("/healthz/").status_code, 200)

    @override_settings(MFA_REQUIRED=True)
    def test_bootstrap_password_then_mfa_has_no_redirect_loop(self):
        self.assertEqual(self.client.get(reverse("password_change")).status_code, 200)
        response = self.client.post(reverse("password_change"), self.payload)
        self.assertRedirects(response, reverse("security"))
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.password_change_required)
        self.assertIsNotNone(self.profile.password_changed_at)
        self.assertRedirects(self.client.get("/"), reverse("security"))

    def test_password_change_revokes_other_sessions_and_audits_without_secrets(self):
        other = Client()
        other.force_login(self.user)
        response = self.client.post(reverse("password_change"), self.payload)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.get("/").wsgi_request.user.is_authenticated)
        self.assertFalse(other.get("/").wsgi_request.user.is_authenticated)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.payload["new_password1"]))
        event = AuditEvent.objects.get(action="security.password_changed")
        self.assertNotIn("Secret", str(event.minimized_diff))

    def test_old_password_and_new_password_policy_are_enforced(self):
        for payload in [
            dict(self.payload, old_password="wrong"),
            dict(self.payload, new_password1="123", new_password2="123"),
            dict(
                self.payload,
                new_password1=self.payload["old_password"],
                new_password2=self.payload["old_password"],
            ),
        ]:
            self.assertEqual(
                self.client.post(reverse("password_change"), payload).status_code, 200
            )
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertTrue(self.user.check_password(self.payload["old_password"]))
        self.assertTrue(self.profile.password_change_required)

    def test_repeated_failures_lock_password_changes(self):
        for _ in range(5):
            self.client.post(
                reverse("password_change"), dict(self.payload, old_password="wrong")
            )
        self.assertContains(
            self.client.post(reverse("password_change"), self.payload),
            "Muitas tentativas",
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.payload["old_password"]))

    def test_enabled_mfa_requires_fresh_factor_and_consumes_recovery_once(self):
        self.profile.enabled_at = timezone.now()
        self.profile.totp_secret_ciphertext = encrypt_json(
            {"secret": "JBSWY3DPEHPK3PXP"}
        )
        self.profile.recovery_hashes = [hash_token("recovery-test-only")]
        self.profile.save()
        self.assertEqual(
            self.client.post(reverse("password_change"), self.payload).status_code, 200
        )
        self.assertEqual(
            self.client.post(
                reverse("password_change"), dict(self.payload, second_factor="wrong")
            ).status_code,
            200,
        )
        response = self.client.post(
            reverse("password_change"),
            dict(self.payload, second_factor="recovery-test-only"),
        )
        self.assertEqual(response.status_code, 302)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.recovery_hashes, [])
        self.assertEqual(
            self.client.session["mfa_version"], self.profile.session_version
        )
        second = {
            "old_password": self.payload["new_password1"],
            "new_password1": "Third-Secret-2026!",
            "new_password2": "Third-Secret-2026!",
            "second_factor": "recovery-test-only",
        }
        self.assertEqual(
            self.client.post(reverse("password_change"), second).status_code, 200
        )

    def test_csrf_and_anonymous_access_are_protected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(
            client.post(reverse("password_change"), self.payload).status_code, 403
        )
        anonymous = Client()
        self.assertEqual(anonymous.get(reverse("password_change")).status_code, 302)

    def test_login_routes_initial_operator_to_password_change(self):
        self.client.logout()
        response = self.client.post(
            reverse("login"),
            {"username": "operator", "password": self.payload["old_password"]},
        )
        self.assertRedirects(response, reverse("password_change"))


class BootstrapOperatorTests(TestCase):
    def bootstrap(self, password="Bootstrap-Initial-Secret-2026!", **overrides):
        options = {
            "tenant_name": "Organização sintética",
            "tenant_slug": "bootstrap-test",
            "campaign_name": "Campanha sintética",
            "campaign_code": "synthetic",
            "election_id": "example",
            "office_code": "example",
            "jurisdiction_code": "example",
            "username": "first-operator",
            "permission": ["memberships.manage.campaign"],
            "password_stdin": True,
            **overrides,
        }
        output = io.StringIO()
        with patch("sys.stdin", io.StringIO(password + "\n")):
            call_command("bootstrap_operator", stdout=output, **options)
        return output.getvalue()

    def test_operator_has_explicit_minimal_role_and_mandatory_change(self):
        output = self.bootstrap()
        user = User.objects.get(username="first-operator")
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertTrue(user.securityprofile.password_change_required)
        self.assertEqual(
            set(
                Membership.objects.get(user=user).role.permissions.values_list(
                    "code", flat=True
                )
            ),
            {"memberships.manage.campaign"},
        )
        self.assertNotIn("Bootstrap-Initial", output)
        self.assertTrue(
            AuditEvent.objects.filter(action="security.operator_bootstrapped").exists()
        )

    def test_existing_operator_or_tenant_is_never_overwritten(self):
        self.bootstrap()
        with self.assertRaises(CommandError):
            self.bootstrap(password="Other-Initial-Secret-2026!")
        self.assertEqual(User.objects.filter(username="first-operator").count(), 1)
        self.assertEqual(Tenant.objects.filter(slug="bootstrap-test").count(), 1)

    def test_weak_password_and_unknown_permission_do_not_create_data(self):
        with self.assertRaises(CommandError):
            self.bootstrap(password="123")
        with self.assertRaises(CommandError):
            self.bootstrap(permission=["nonexistent.permission"])
        self.assertFalse(Tenant.objects.filter(slug="bootstrap-test").exists())
        self.assertFalse(User.objects.filter(username="first-operator").exists())
