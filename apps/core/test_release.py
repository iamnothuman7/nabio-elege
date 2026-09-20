import io
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import SimpleTestCase

from infra.check_dependency_lock import OPTIONS, verify_lock


class ReleaseValidationTests(SimpleTestCase):
    def test_all_module_fields_have_explicit_portuguese_labels(self):
        from apps.workspace.registry import LABELS, MODULES

        fields = {
            field for module in MODULES for field in module.fields + module.columns
        }
        self.assertEqual(fields - LABELS.keys(), set())

    def test_project_lock_matches_inputs(self):
        from django.conf import settings

        self.assertEqual(
            verify_lock(
                settings.BASE_DIR / "requirements-production.txt",
                settings.BASE_DIR / "requirements-production.lock",
            ),
            34,
        )

    def test_lock_rejects_missing_hash_drift_and_extra_index(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "requirements.txt"
            lock = Path(directory) / "lock.txt"
            source.write_text("example==1.0\n", encoding="utf-8")
            header = "\n".join(sorted(OPTIONS)) + "\n"
            for line in [
                "example==1.0",
                "example==2.0 --hash=sha256:" + "a" * 64,
                "example==1.0 --hash=sha256:invalid",
                "--extra-index-url https://example.invalid/simple",
            ]:
                lock.write_text(header + line, encoding="utf-8")
                with self.subTest(line=line), self.assertRaises(ValueError):
                    verify_lock(source, lock)

    def test_all_project_templates_compile(self):
        output = io.StringIO()
        call_command("check_templates", stdout=output)
        self.assertIn("templates compilados", output.getvalue())
