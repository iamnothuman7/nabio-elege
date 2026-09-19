from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TransactionTestCase
from unittest.mock import Mock

from apps.campaigns.models import Campaign, Tenant

from .models import AuditEvent, OutboxEvent
from .outbox import dispatch_outbox_event
from .services import enqueue_outbox_event


class AuditAndOutboxTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("auditor", password="test-only")
        self.tenant = Tenant.objects.create(name="Organização", slug="organizacao")
        self.campaign = Campaign.objects.create(
            tenant=self.tenant,
            code="campanha",
            name="Campanha",
            election_id="2026",
            office_code="office",
            jurisdiction_code="CE",
        )

    def test_audit_event_is_immutable(self):
        event = AuditEvent.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            actor=self.user,
            action="campaign.created",
            resource_type="campaign",
            resource_id=str(self.campaign.id),
        )
        event.reason = "alterado"
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()

    def test_outbox_requires_business_transaction(self):
        with self.assertRaises(RuntimeError):
            enqueue_outbox_event(
                tenant=self.tenant,
                campaign=self.campaign,
                kind="campaign.created.v1",
                aggregate_type="campaign",
                aggregate_id=self.campaign.id,
            )

        with transaction.atomic():
            event = enqueue_outbox_event(
                tenant=self.tenant,
                campaign=self.campaign,
                kind="campaign.created.v1",
                aggregate_type="campaign",
                aggregate_id=self.campaign.id,
            )
        self.assertEqual(event.status, OutboxEvent.Status.PENDING)

    def test_outbox_dispatches_known_event_and_marks_it_published(self):
        with transaction.atomic():
            event = enqueue_outbox_event(
                tenant=self.tenant,
                campaign=self.campaign,
                kind="submission.accepted.v1",
                aggregate_type="submission",
                aggregate_id="fictitious-submission",
            )
        sender = Mock()
        self.assertTrue(dispatch_outbox_event(event.id, send_task=sender))
        event.refresh_from_db()
        sender.assert_called_once_with(
            "forms.process_submission", args=["fictitious-submission"]
        )
        self.assertEqual(event.status, OutboxEvent.Status.PUBLISHED)
