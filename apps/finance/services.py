from django.core.exceptions import ValidationError
from django.db import models, transaction

from apps.campaigns.services import require_campaign_permission
from apps.core.services import append_audit_event, enqueue_outbox_event

from .models import (
    BankEntry,
    Obligation,
    ObligationApproval,
    PaymentAllocation,
    PaymentRecord,
    ReconciliationLink,
)


def positive_cents(value):
    if isinstance(value, bool) or not str(value).isdigit() or int(value) <= 0:
        raise ValidationError("Informe um número inteiro positivo de centavos.")
    return int(value)


@transaction.atomic
def submit_obligation(*, actor, obligation_id, expected_version, request_id=None):
    obligation = (
        Obligation.objects.select_related("campaign", "tenant")
        .select_for_update()
        .get(pk=obligation_id)
    )
    require_campaign_permission(actor, obligation.campaign, "finance.create.campaign")
    if obligation.row_version != expected_version:
        raise ValidationError("A obrigação foi alterada; recarregue antes de enviar.")
    if obligation.approval_status != Obligation.ApprovalStatus.DRAFT:
        raise ValidationError("Somente obrigações em rascunho podem ser submetidas.")
    obligation.approval_status = Obligation.ApprovalStatus.SUBMITTED
    obligation.save(update_fields=["approval_status", "row_version", "updated_at"])
    append_audit_event(
        actor=actor,
        tenant=obligation.tenant,
        campaign=obligation.campaign,
        action="obligation.submitted",
        resource_type="obligation",
        resource_id=obligation.id,
        request_id=request_id,
    )
    return obligation


@transaction.atomic
def allocate_payment(*, actor, payment_id, obligation_id, amount_cents, request_id=None):
    payment = (
        PaymentRecord.objects.select_for_update()
        .select_related("campaign", "tenant")
        .get(pk=payment_id)
    )
    obligation = Obligation.objects.select_for_update().get(pk=obligation_id)
    require_campaign_permission(actor, payment.campaign, "finance.reconcile.campaign")
    if payment.campaign_id != obligation.campaign_id:
        raise ValidationError("Pagamento e obrigação devem pertencer à mesma campanha.")
    if payment.status == PaymentRecord.Status.REVERSED:
        raise ValidationError("Um pagamento estornado não pode ser alocado.")
    if obligation.approval_status != Obligation.ApprovalStatus.APPROVED:
        raise ValidationError("A obrigação precisa estar aprovada antes da alocação.")
    if payment.currency != obligation.currency:
        raise ValidationError("As moedas devem ser iguais.")
    amount_cents = positive_cents(amount_cents)
    if amount_cents <= 0:
        raise ValidationError("O valor alocado deve ser positivo.")

    payment_allocated = payment.allocations.aggregate(total=models.Sum("amount_cents"))[
        "total"
    ] or 0
    obligation_allocated = obligation.payment_allocations.filter(
        payment__status__in=[PaymentRecord.Status.RECORDED, PaymentRecord.Status.VERIFIED]
    ).aggregate(total=models.Sum("amount_cents"))["total"] or 0
    if payment_allocated + amount_cents > payment.amount_cents:
        raise ValidationError("A alocação supera o saldo do pagamento.")
    if obligation_allocated + amount_cents > obligation.amount_cents:
        raise ValidationError("A alocação supera o saldo da obrigação.")

    allocation = PaymentAllocation.objects.create(
        payment=payment,
        obligation=obligation,
        amount_cents=amount_cents,
    )
    append_audit_event(
        actor=actor,
        tenant=payment.tenant,
        campaign=payment.campaign,
        action="payment.allocated",
        resource_type="payment_allocation",
        resource_id=allocation.id,
        minimized_diff={
            "payment_id": str(payment.id),
            "obligation_id": str(obligation.id),
            "amount_cents": amount_cents,
        },
        request_id=request_id,
    )
    return allocation


@transaction.atomic
def reconcile_bank_entry(*, actor, entry_id, payment_id, amount_cents, request_id=None):
    # All paths lock payments before bank entries to avoid inverse lock order.
    payment = PaymentRecord.objects.select_for_update().get(pk=payment_id)
    entry = (
        BankEntry.objects.select_for_update()
        .select_related("campaign", "tenant")
        .get(pk=entry_id)
    )
    require_campaign_permission(actor, entry.campaign, "finance.reconcile.campaign")
    if entry.campaign_id != payment.campaign_id:
        raise ValidationError("A entrada e o pagamento devem pertencer à mesma campanha.")
    if entry.amount_cents >= 0:
        raise ValidationError("Somente saídas bancárias podem ser conciliadas a pagamentos.")
    if payment.status == PaymentRecord.Status.REVERSED:
        raise ValidationError("Pagamentos estornados não podem ser conciliados.")
    if entry.account.currency != payment.currency:
        raise ValidationError("As moedas devem ser iguais.")
    amount_cents = positive_cents(amount_cents)
    if amount_cents <= 0:
        raise ValidationError("O valor conciliado deve ser positivo.")
    reconciled = entry.reconciliations.filter(reversed_at__isnull=True).aggregate(
        total=models.Sum("amount_cents")
    )["total"] or 0
    if reconciled + amount_cents > abs(entry.amount_cents):
        raise ValidationError("A conciliação supera o valor da entrada bancária.")
    payment_reconciled = payment.reconciliations.filter(reversed_at__isnull=True).aggregate(total=models.Sum("amount_cents"))["total"] or 0
    if payment_reconciled + amount_cents > payment.amount_cents:
        raise ValidationError("A conciliação supera o valor do pagamento.")

    link = ReconciliationLink.objects.create(
        entry=entry,
        payment=payment,
        amount_cents=amount_cents,
    )
    total_reconciled = reconciled + amount_cents
    entry.status = (
        BankEntry.Status.RECONCILED
        if total_reconciled == abs(entry.amount_cents)
        else BankEntry.Status.PARTIAL
    )
    entry.save(update_fields=["status", "row_version", "updated_at"])
    append_audit_event(
        actor=actor,
        tenant=entry.tenant,
        campaign=entry.campaign,
        action="bank_entry.reconciled",
        resource_type="bank_entry",
        resource_id=entry.id,
        minimized_diff={"amount_cents": amount_cents, "status": entry.status},
        request_id=request_id,
    )
    return link


@transaction.atomic
def decide_obligation(
    *, actor, obligation_id, expected_version, decision, reason, request_id=None
):
    obligation = (
        Obligation.objects.select_related("campaign", "tenant")
        .select_for_update()
        .get(pk=obligation_id)
    )
    require_campaign_permission(actor, obligation.campaign, "finance.approve.campaign")
    if obligation.row_version != expected_version:
        raise ValidationError("A obrigação foi alterada; recarregue antes de decidir.")
    if obligation.approval_status != Obligation.ApprovalStatus.SUBMITTED:
        raise ValidationError("A obrigação não está aguardando decisão.")
    if obligation.created_by_id == actor.id:
        raise ValidationError("O criador não pode realizar a aprovação final.")
    if decision not in ObligationApproval.Decision.values:
        raise ValidationError("Decisão inválida.")

    ObligationApproval.objects.create(
        obligation=obligation,
        obligation_version=obligation.row_version,
        decided_by=actor,
        decision=decision,
        reason=reason,
    )
    obligation.approval_status = decision
    obligation.save(update_fields=["approval_status", "row_version", "updated_at"])
    append_audit_event(
        actor=actor,
        tenant=obligation.tenant,
        campaign=obligation.campaign,
        action=f"obligation.{decision}",
        resource_type="obligation",
        resource_id=obligation.id,
        reason=reason,
        request_id=request_id,
    )
    enqueue_outbox_event(
        tenant=obligation.tenant,
        campaign=obligation.campaign,
        kind=f"expense.{decision}.v1",
        aggregate_type="obligation",
        aggregate_id=obligation.id,
        aggregate_version=obligation.row_version,
        payload_minimized={"decision": decision},
    )
    return obligation
