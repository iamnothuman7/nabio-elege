from unittest.mock import patch

from django.test import SimpleTestCase

from infra.validate_isolated import plan, provision, validate_existing, validation_database


class IsolatedProvisioningTests(SimpleTestCase):
    def test_plan_is_restricted_to_qa_and_has_no_public_port(self):
        result = plan("a" * 40)
        self.assertEqual(result["root"], "/var/www/apps/nabio-elege-qa")
        self.assertEqual(result["databases"], ("nabio_elege_qa", "test_nabio_elege_qa"))
        self.assertIsNone(result["public_port"])

    def test_plan_rejects_unpinned_or_command_like_revision(self):
        for revision in ["main", "origin/main", "abc123", "; unsafe", "A" * 40, "a" * 41]:
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                plan(revision)

    def test_non_admin_is_rejected_before_any_provisioning(self):
        with patch("infra.validate_isolated.os.geteuid", return_value=1000, create=True), patch("infra.validate_isolated.run") as run:
            with self.assertRaises(RuntimeError):
                provision("a" * 40)
        run.assert_not_called()

    def test_revalidation_database_has_an_exclusive_bounded_name(self):
        self.assertEqual(validation_database("a" * 40), "test_nabio_elege_qa_aaaaaaaaaaaa")
        with self.assertRaises(ValueError):
            validation_database("main; unsafe")

    def test_non_admin_cannot_revalidate_existing_qa(self):
        with patch("infra.validate_isolated.os.geteuid", return_value=1000, create=True), patch("infra.validate_isolated.postgres") as postgres:
            with self.assertRaises(RuntimeError):
                validate_existing("a" * 40)
        postgres.assert_not_called()
