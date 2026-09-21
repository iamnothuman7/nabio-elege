from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import SecurityProfile


class AccessExperienceTests(TestCase):
    def test_anonymous_home_is_product_and_all_public_access_pages_render(self):
        response = self.client.get("/")
        self.assertTemplateUsed(response, "workspace/landing.html")
        for name in ("product_landing", "login", "access_help", "accept_invitation"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertIn("no-store", response["Cache-Control"])
        self.assertContains(
            self.client.get(reverse("access_help")), "ainda não está disponível"
        )

    def test_login_has_accessible_labels_and_never_returns_password(self):
        response = self.client.post(
            reverse("login"),
            {
                "username": "<script>test</script>",
                "password": "never-return-this-password",
            },
        )
        self.assertContains(response, 'aria-describedby="login-error"')
        self.assertContains(response, 'autocomplete="current-password"')
        self.assertContains(response, "&lt;script&gt;test&lt;/script&gt;")
        self.assertNotContains(response, "<script>test</script>")
        self.assertNotContains(response, "never-return-this-password")
        self.assertEqual(response.context["username"], "<script>test</script>")
        self.assertContains(response, "workspace/auth.js")

    def test_oversize_password_is_rejected_before_expensive_authentication(self):
        with patch("apps.workspace.auth_views.authenticate") as authenticate:
            response = self.client.post(
                reverse("login"), {"username": "operator", "password": "x" * 1025}
            )
        self.assertContains(response, "Não foi possível entrar")
        authenticate.assert_not_called()
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_csrf_required_and_unsafe_methods_rejected(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(
            client.post(
                reverse("login"), {"username": "operator", "password": "wrong"}
            ).status_code,
            403,
        )
        self.assertEqual(self.client.put(reverse("login")).status_code, 405)

    def test_lockout_and_generic_error_do_not_reveal_accounts(self):
        User.objects.create_user("operator", password="Account-Test-Only-2026!")
        message = None
        for index in range(5):
            response = self.client.post(
                reverse("login"), {"username": "operator", "password": "wrong"}
            )
            message = response.context["error"]
        with patch("apps.workspace.auth_views.authenticate") as authenticate:
            response = self.client.post(
                reverse("login"),
                {"username": "operator", "password": "Account-Test-Only-2026!"},
            )
        authenticate.assert_not_called()
        self.assertEqual(response.context["error"], message)
        other = Client(REMOTE_ADDR="192.0.2.10")
        self.assertEqual(
            other.post(
                reverse("login"), {"username": "unknown", "password": "wrong"}
            ).context["error"],
            message,
        )

    @override_settings(MFA_REQUIRED=True)
    def test_public_help_accessible_during_required_security_steps(self):
        user = User.objects.create_user("operator", password="Account-Test-Only-2026!")
        SecurityProfile.objects.create(user=user, password_change_required=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("access_help")).status_code, 200)
        self.assertEqual(self.client.get(reverse("product_landing")).status_code, 200)
        self.assertRedirects(self.client.get("/"), reverse("password_change"))

    def test_valid_login_rotates_session_and_logout_is_post_only(self):
        user = User.objects.create_user("operator", password="Account-Test-Only-2026!")
        session = self.client.session
        session["synthetic_marker"] = True
        session.save()
        before = session.session_key
        response = self.client.post(
            reverse("login"),
            {"username": "operator", "password": "Account-Test-Only-2026!"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(self.client.session.session_key, before)
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"))
        self.assertNotIn("_auth_user_id", self.client.session)
