import io
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from .checks import production_guardrails


class DeploymentChecksTests(TestCase):
    def production_values(self):
        shared = Path.cwd().parent / "nabio-isolated-shared"
        return dict(
            APP_ENV="production", DEBUG=False, LOCAL_DEMO=False, MFA_REQUIRED=True,
            DATABASES={"default": {"ENGINE": "django.db.backends.postgresql"}},
            SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True, SECURE_SSL_REDIRECT=True,
            ALLOWED_HOSTS=["elege.nabio.pro"], CSRF_TRUSTED_ORIGINS=["https://elege.nabio.pro"],
            SECRET_KEY="s" * 64, FIELD_ENCRYPTION_KEY=Fernet.generate_key().decode(),
            BLIND_INDEX_KEY="b" * 64, RECEIPT_TOKEN_KEY="r" * 64,
            CACHES={"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": "redis://127.0.0.1:6380/1"}},
            CLAMAV_HOST="127.0.0.1", MEDIA_ROOT=shared / "media", STATIC_ROOT=shared / "staticfiles",
        )

    def test_valid_production_configuration_passes_static_guards(self):
        with override_settings(**self.production_values()):
            self.assertEqual(production_guardrails(None), [])

    def test_insecure_defaults_are_rejected_without_secret_disclosure(self):
        with override_settings(APP_ENV="production"):
            errors = production_guardrails(None)
        codes = {error.id for error in errors}
        self.assertTrue({"nabio.E003", "nabio.E004", "nabio.E007", "nabio.E008", "nabio.E009", "nabio.E011"}.issubset(codes))
        self.assertNotIn("test-only-blind-index", str(errors))

    def test_duplicate_secrets_and_public_private_storage_overlap_are_rejected(self):
        values = self.production_values()
        values["RECEIPT_TOKEN_KEY"] = values["SECRET_KEY"]
        values["STATIC_ROOT"] = values["MEDIA_ROOT"] / "static"
        with override_settings(**values):
            codes = {error.id for error in production_guardrails(None)}
        self.assertTrue({"nabio.E007", "nabio.E012"}.issubset(codes))

    def test_wildcards_and_http_origins_are_rejected(self):
        values = self.production_values()
        values.update(ALLOWED_HOSTS=["*"], CSRF_TRUSTED_ORIGINS=["http://elege.nabio.pro"])
        with override_settings(**values):
            codes = {error.id for error in production_guardrails(None)}
        self.assertTrue({"nabio.E005", "nabio.E006"}.issubset(codes))

    def test_liveness_is_minimal_even_for_authenticated_user_without_mfa(self):
        self.client.force_login(User.objects.create_user("healthcheck"))
        with override_settings(MFA_REQUIRED=True), self.assertNumQueries(0):
            response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_runtime_failure_does_not_echo_connection_details(self):
        output = io.StringIO()
        path = "apps.core.management.commands.check_runtime.Command"
        with patch(path + ".database", side_effect=RuntimeError("postgres://private-password@host/db")), patch(path + ".migrations", return_value=True), patch(path + ".redis_ping", return_value=True), patch(path + ".antivirus", return_value=True):
            with self.assertRaises(CommandError):
                call_command("check_runtime", stdout=output)
        self.assertIn("database: INDISPONÍVEL", output.getvalue())
        self.assertNotIn("private-password", output.getvalue())
