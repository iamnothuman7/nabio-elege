import hashlib
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from django.conf import settings
from django.test import SimpleTestCase


class RegistrationExpansionTests(SimpleTestCase):
    def controller(self):
        spec = spec_from_file_location(
            "registration_expansion",
            settings.BASE_DIR / "infra/registration_expansion.py",
        )
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_only_exact_reviewed_migration_and_compatible_reader_allowed(self):
        controller = self.controller()
        source = (
            (settings.BASE_DIR / controller.MIGRATION)
            .read_bytes()
            .replace(b"\r\n", b"\n")
        )
        self.assertEqual(
            hashlib.sha256(source).hexdigest(), controller.MIGRATION_SHA256
        )
        run = Mock()
        previous = Path("/releases") / controller.COMPATIBLE_READER
        controller.validate_source(
            settings.BASE_DIR, previous, [controller.MIGRATION], run
        )
        run.assert_called_once_with(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                controller.COMPATIBLE_READER,
                previous.name,
            ],
            cwd=settings.BASE_DIR,
        )
        for changes in [
            [],
            ["apps/core/migrations/9999_wrong.py"],
            [controller.MIGRATION, "apps/core/migrations/9999_wrong.py"],
        ]:
            with self.assertRaises(RuntimeError):
                controller.validate_source(settings.BASE_DIR, previous, changes, run)

    def test_modified_migration_fails_closed(self):
        controller = self.controller()
        with TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / controller.MIGRATION
            path.parent.mkdir(parents=True)
            path.write_bytes(b"unreviewed")
            with self.assertRaises(RuntimeError):
                controller.validate_source(root, root, [controller.MIGRATION], Mock())

    def test_migration_is_additive_nullable_and_has_no_data_operations(self):
        from django.db.migrations import AddField, AlterField
        from importlib import import_module

        migration = import_module(
            "apps.workspace.migrations.0009_simpler_registration"
        ).Migration
        self.assertEqual(len(migration.operations), 4)
        self.assertEqual(
            [type(op) for op in migration.operations],
            [AddField, AddField, AlterField, AlterField],
        )
        self.assertTrue(all(op.field.null for op in migration.operations))
