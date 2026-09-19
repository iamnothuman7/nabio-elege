import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.campaigns.models import Campaign, Membership, Permission, Role, Tenant

from .models import Obligation, ObligationApproval, PaymentAllocation, PaymentRecord
from .services import decide_obligation, submit_obligation


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
        creator_role = Role.objects.create(
            tenant=self.tenant, code="creator", name="Criador"
        )
        creator_role.permissions.add(create_permission, approve_permission)
        approver_role = Role.objects.create(
            tenant=self.tenant, code="approver", name="Aprovador"
        )
        approver_role.permissions.add(approve_permission)
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
