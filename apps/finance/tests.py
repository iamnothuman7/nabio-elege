import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.campaigns.models import Campaign, Membership, Permission, Role, Tenant

from .models import (
    BankAccount,
    BankEntry,
    Obligation,
    ObligationApproval,
    PaymentAllocation,
    PaymentRecord,
)
from .services import (
    allocate_payment,
    decide_obligation,
    reconcile_bank_entry,
    submit_obligation,
)


class FinancialIntegrityTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.creator = users.objects.create_user("creator", password="test-only")
        self.approver = users.objects.create_user("approver", password="test-only")
        self.tenant = Tenant.objects.create(name="Organização", slug="organizacao")
        self.campaign = Campaign.objects.create(
            tenant=self.tenant,
            code="campanha",
            name="Campanha",
            election_id="2026",
            office_code="office",
            jurisdiction_code="CE",
        )
        create_permission = Permission.objects.get(code="finance.create.campaign")
        approve_permission = Permission.objects.get(code="finance.approve.campaign")
        reconcile_permission = Permission.objects.get(code="finance.reconcile.campaign")
        creator_role = Role.objects.create(
            tenant=self.tenant, code="creator", name="Criador"
        )
        creator_role.permissions.add(create_permission, approve_permission)
        approver_role = Role.objects.create(
            tenant=self.tenant, code="approver", name="Aprovador"
        )
        approver_role.permissions.add(approve_permission, reconcile_permission)
        Membership.objects.create(
            user=self.creator,
            tenant=self.tenant,
            campaign=self.campaign,
            role=creator_role,
            status=Membership.Status.ACTIVE,
        )
        Membership.objects.create(
            user=self.approver,
            tenant=self.tenant,
            campaign=self.campaign,
            role=approver_role,
            status=Membership.Status.ACTIVE,
        )
        self.obligation = Obligation.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            created_by=self.creator,
            origin_type="purchase_order",
            origin_id=uuid.uuid4(),
            creditor_ref="supplier:test",
            description="Compra fictícia",
            amount_cents=100_000,
        )

    def test_creator_cannot_approve_own_obligation(self):
        submitted = submit_obligation(
            actor=self.creator,
            obligation_id=self.obligation.id,
            expected_version=self.obligation.row_version,
        )
        with self.assertRaises(ValidationError):
            decide_obligation(
                actor=self.creator,
                obligation_id=submitted.id,
                expected_version=submitted.row_version,
                decision=ObligationApproval.Decision.APPROVED,
                reason="Não permitido",
            )

    def test_independent_approver_can_approve(self):
        submitted = submit_obligation(
            actor=self.creator,
            obligation_id=self.obligation.id,
            expected_version=self.obligation.row_version,
        )
        approved = decide_obligation(
            actor=self.approver,
            obligation_id=submitted.id,
            expected_version=submitted.row_version,
            decision=ObligationApproval.Decision.APPROVED,
            reason="Documentação conferida",
        )
        self.assertEqual(approved.approval_status, Obligation.ApprovalStatus.APPROVED)
        self.assertEqual(approved.approvals.count(), 1)

    def test_allocation_cannot_exceed_payment_or_obligation(self):
        payment = PaymentRecord.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            created_by=self.creator,
            external_reference="payment-1",
            amount_cents=50_000,
            paid_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            PaymentAllocation.objects.create(
                payment=payment,
                obligation=self.obligation,
                amount_cents=60_000,
            )

    def test_payment_allocation_uses_remaining_balances(self):
        submitted = submit_obligation(actor=self.creator, obligation_id=self.obligation.pk, expected_version=self.obligation.row_version)
        decide_obligation(actor=self.approver, obligation_id=submitted.pk, expected_version=submitted.row_version, decision="approved", reason="Conferência independente")
        payment = PaymentRecord.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            created_by=self.creator,
            external_reference="payment-service-1",
            amount_cents=60_000,
            paid_at=timezone.now(),
        )
        allocation = allocate_payment(
            actor=self.approver,
            payment_id=payment.id,
            obligation_id=self.obligation.id,
            amount_cents=50_000,
        )
        self.assertEqual(allocation.amount_cents, 50_000)
        with self.assertRaises(ValidationError):
            allocate_payment(
                actor=self.approver,
                payment_id=payment.id,
                obligation_id=self.obligation.id,
                amount_cents=20_000,
            )

    def test_bank_entry_reconciliation_tracks_partial_state(self):
        account = BankAccount.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            created_by=self.creator,
            name="Conta fictícia",
            funding_source="test",
        )
        entry = BankEntry.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            created_by=self.creator,
            account=account,
            external_id="entry-1",
            occurred_at=timezone.now(),
            amount_cents=-60_000,
            original_line_hash="a" * 64,
        )
        payment = PaymentRecord.objects.create(
            tenant=self.tenant,
            campaign=self.campaign,
            created_by=self.creator,
            external_reference="payment-bank-1",
            amount_cents=60_000,
            paid_at=timezone.now(),
        )
        reconcile_bank_entry(
            actor=self.approver,
            entry_id=entry.id,
            payment_id=payment.id,
            amount_cents=30_000,
        )
        entry.refresh_from_db()
        self.assertEqual(entry.status, BankEntry.Status.PARTIAL)
