from django.core.exceptions import ValidationError
from django.db import transaction

from apps.campaigns.services import require_campaign_permission
from apps.core.services import append_audit_event, enqueue_outbox_event

from .models import Obligation, ObligationApproval


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
