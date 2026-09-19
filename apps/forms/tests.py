from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.campaigns.models import Campaign, Membership, Permission, Role, Tenant
from apps.core.crypto import decrypt_json
from apps.core.models import AuditEvent, OutboxEvent, RetentionPolicy
from apps.core.services import canonical_json_hash

from .models import (
    Form,
    FormVersion,
    PrivacyNoticeVersion,
    ProcessingPurpose,
    SourceLink,
    Submission,
    ServiceRequest,
)
from .processing import process_submission
from .public_services import IdempotencyConflict, receive_public_submission
from .services import publish_form_version, receive_assisted_submission


class FormPublishingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("publisher", password="test-only")
        self.tenant = Tenant.objects.create(name="Organização", slug="organizacao")
        self.campaign = Campaign.objects.create(
            tenant=self.tenant,
            code="campanha",
            name="Campanha",
            election_id="2026",
            office_code="office",
            jurisdiction_code="CE",
        )
        permission = Permission.objects.get(code="forms.publish.campaign")
        assist_permission = Permission.objects.get(code="submissions.assist.assigned")
        role = Role.objects.create(tenant=self.tenant, code="publisher", name="Publicador")
        role.permissions.add(permission, assist_permission)
        self.membership = Membership.objects.create(
            user=self.user,
            tenant=self.tenant,
            campaign=self.campaign,
            role=role,
            status=Membership.Status.ACTIVE,
        )
        retention = RetentionPolicy.objects.create(
            tenant=self.tenant,
            code="service",
            name="Atendimento",
            status=RetentionPolicy.Status.ACTIVE,
        )
        self.purpose = ProcessingPurpose.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            created_by=self.user,
            code="service-request",
            description="Receber solicitações de atendimento.",
            legal_basis_ref="revisão jurídica pendente",
            allowed_fields=["name", "email", "message"],
            retention_policy=retention,
            status=ProcessingPurpose.Status.ACTIVE,
        )
        notice_content = "Usaremos os dados para atender sua solicitação."
        self.notice = PrivacyNoticeVersion.objects.create(
            purpose=self.purpose,
            version=1,
            content=notice_content,
            content_hash=canonical_json_hash({"content": notice_content}),
            status=PrivacyNoticeVersion.Status.APPROVED,
            approved_by=self.user,
            approved_at=timezone.now(),
        )
        self.form = Form.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            created_by=self.user,
            purpose=self.purpose,
            title="Solicitação de atendimento",
            slug="atendimento",
        )
        schema = {"fields": [{"name": "message", "type": "long_text"}]}
        self.version = FormVersion.objects.create(
            form=self.form,
            version_number=1,
            schema_json=schema,
            schema_hash=canonical_json_hash(schema),
            notice_version=self.notice,
            status=FormVersion.Status.APPROVED,
            approved_by=self.user,
            approved_at=timezone.now(),
        )

    def test_publish_is_transactional_and_audited(self):
        published = publish_form_version(
            actor=self.user,
            form_version_id=self.version.id,
            expected_form_row_version=self.form.row_version,
        )
        self.version.refresh_from_db()
        self.assertEqual(published.status, Form.Status.PUBLISHED)
        self.assertEqual(published.current_version_id, self.version.id)
        self.assertEqual(self.version.status, FormVersion.Status.PUBLISHED)
        self.assertTrue(
            AuditEvent.objects.filter(action="form.published", campaign=self.campaign).exists()
        )
        self.assertTrue(
            OutboxEvent.objects.filter(kind="form.published.v1", campaign=self.campaign).exists()
        )

    def test_published_version_is_immutable(self):
        publish_form_version(
            actor=self.user,
            form_version_id=self.version.id,
            expected_form_row_version=self.form.row_version,
        )
        self.version.refresh_from_db()
        self.version.schema_json = {"fields": []}
        with self.assertRaises(ValidationError):
            self.version.save()

    def test_stale_form_version_is_rejected(self):
        with self.assertRaises(ValidationError):
            publish_form_version(
                actor=self.user,
                form_version_id=self.version.id,
                expected_form_row_version=999,
            )

    def test_public_submission_is_encrypted_and_idempotent(self):
        published = publish_form_version(
            actor=self.user,
            form_version_id=self.version.id,
            expected_form_row_version=self.form.row_version,
        )
        source_link = SourceLink.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            created_by=self.user,
            form=published,
        )
        fields = {"message": "Preciso de atendimento."}
        first, replayed = receive_public_submission(
            public_code=source_link.public_code,
            version_id=self.version.id,
            fields=fields,
            idempotency_key="submission-1",
        )
        second, second_replayed = receive_public_submission(
            public_code=source_link.public_code,
            version_id=self.version.id,
            fields=fields,
            idempotency_key="submission-1",
        )

        self.assertFalse(replayed)
        self.assertTrue(second_replayed)
        self.assertEqual(first, second)
        self.assertEqual(Submission.objects.count(), 1)
        submission = Submission.objects.get()
        self.assertNotIn(fields["message"].encode(), bytes(submission.payload_ciphertext))
        self.assertEqual(decrypt_json(submission.payload_ciphertext), fields)

    def test_same_idempotency_key_with_different_body_conflicts(self):
        published = publish_form_version(
            actor=self.user,
            form_version_id=self.version.id,
            expected_form_row_version=self.form.row_version,
        )
        source_link = SourceLink.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            created_by=self.user,
            form=published,
        )
        receive_public_submission(
            public_code=source_link.public_code,
            version_id=self.version.id,
            fields={"message": "Primeiro conteúdo"},
            idempotency_key="same-key",
        )
        with self.assertRaises(IdempotencyConflict):
            receive_public_submission(
                public_code=source_link.public_code,
                version_id=self.version.id,
                fields={"message": "Conteúdo diferente"},
                idempotency_key="same-key",
            )

    def test_submission_processing_creates_service_request_once(self):
        published = publish_form_version(
            actor=self.user,
            form_version_id=self.version.id,
            expected_form_row_version=self.form.row_version,
        )
        source_link = SourceLink.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            created_by=self.user,
            form=published,
        )
        receive_public_submission(
            public_code=source_link.public_code,
            version_id=self.version.id,
            fields={"message": "Solicitação para triagem"},
            idempotency_key="processing-1",
        )
        submission = Submission.objects.get()
        processed = process_submission(submission_id=submission.id)
        process_submission(submission_id=submission.id)

        self.assertEqual(
            processed.processing_status, Submission.ProcessingStatus.PROCESSED
        )
        self.assertEqual(ServiceRequest.objects.count(), 1)
        self.assertEqual(ServiceRequest.objects.get().submission_id, submission.id)

    def test_assisted_submission_derives_agent_from_session_user(self):
        published = publish_form_version(
            actor=self.user,
            form_version_id=self.version.id,
            expected_form_row_version=self.form.row_version,
        )
        receive_assisted_submission(
            actor=self.user,
            form_id=published.id,
            version_id=self.version.id,
            fields={"message": "Atendimento assistido fictício"},
            idempotency_key="assisted-1",
        )
        submission = Submission.objects.get()
        self.assertEqual(submission.created_by_id, self.user.id)
        self.assertEqual(submission.assisted_by_membership_id, self.membership.id)
        self.assertEqual(submission.capture_mode, Submission.CaptureMode.ASSISTED)
