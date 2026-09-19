import hashlib
import json

from django.db import transaction

from .models import AuditEvent, OutboxEvent


def canonical_json_hash(value):
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def append_audit_event(
    *,
    actor,
    action,
    resource_type,
    resource_id,
    tenant=None,
    campaign=None,
    reason="",
    minimized_diff=None,
    request_id=None,
):
    return AuditEvent.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        tenant=tenant,
        campaign=campaign,
        reason=reason,
        minimized_diff=minimized_diff or {},
        request_id=request_id,
    )


def enqueue_outbox_event(
    *,
    tenant,
    campaign,
    kind,
    aggregate_type,
    aggregate_id,
    aggregate_version=1,
    payload_minimized=None,
):
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Eventos de outbox devem ser criados dentro de uma transação.")
    return OutboxEvent.objects.create(
        tenant=tenant,
        campaign=campaign,
        kind=kind,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        aggregate_version=aggregate_version,
        payload_minimized=payload_minimized or {},
    )
