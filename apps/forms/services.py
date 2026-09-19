import hashlib
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.campaigns.services import membership_for, require_campaign_permission
from apps.core.crypto import derive_receipt_token, encrypt_json, hash_token
from apps.core.models import IdempotencyRecord
from apps.core.services import (
    append_audit_event,
    canonical_json_hash,
    enqueue_outbox_event,
)

from .models import (
    Form,
    FormVersion,
    PrivacyNoticeVersion,
    ProcessingPurpose,
    Submission,
    SubmissionReceipt,
    opaque_code,
)
from .public_services import (
    IdempotencyConflict,
    PublicFormVersionConflict,
    validate_submission_fields,
)


@transaction.atomic
def publish_form_version(*, actor, form_version_id, expected_form_row_version, request_id=None):
    version = (
        FormVersion.objects.select_related(
            "form__campaign", "form__tenant", "form__purpose", "notice_version"
        )
        .select_for_update()
        .get(pk=form_version_id)
    )
    form = Form.objects.select_for_update().get(pk=version.form_id)
    require_campaign_permission(actor, form.campaign, "forms.publish.campaign")

    if form.row_version != expected_form_row_version:
        raise ValidationError("O formulário foi alterado; recarregue antes de publicar.")
    if version.status != FormVersion.Status.APPROVED:
        raise ValidationError("Somente uma versão aprovada pode ser publicada.")
    if version.notice_version.status != PrivacyNoticeVersion.Status.APPROVED:
        raise ValidationError("O aviso de privacidade ainda não foi aprovado.")
    if form.purpose.status != ProcessingPurpose.Status.ACTIVE:
        raise ValidationError("A finalidade do formulário não está ativa.")

    version.status = FormVersion.Status.PUBLISHED
    version.published_at = timezone.now()
    version.save(update_fields=["status", "published_at", "updated_at"])

    form.current_version = version
    form.status = Form.Status.PUBLISHED
    form.save(update_fields=["current_version", "status", "row_version", "updated_at"])

    append_audit_event(
        actor=actor,
        tenant=form.tenant,
        campaign=form.campaign,
        action="form.published",
        resource_type="form_version",
        resource_id=version.id,
        minimized_diff={"version": version.version_number},
        request_id=request_id,
    )
    enqueue_outbox_event(
        tenant=form.tenant,
        campaign=form.campaign,
        kind="form.published.v1",
        aggregate_type="form",
        aggregate_id=form.id,
        aggregate_version=form.row_version,
        payload_minimized={"form_version_id": str(version.id)},
    )
    return form


@transaction.atomic
def receive_assisted_submission(
    *, actor, form_id, version_id, fields, idempotency_key, request_id=None
):
    if not idempotency_key or len(idempotency_key) > 200:
        raise ValidationError(
            {"Idempotency-Key": "Envie uma chave de idempotência válida."}
        )

    form = (
        Form.objects.select_for_update()
        .select_related("campaign", "tenant", "current_version", "purpose")
        .get(pk=form_id)
    )
    membership = require_campaign_permission(
        actor, form.campaign, "submissions.assist.assigned"
    )
    if membership is None:
        membership = membership_for(actor, form.campaign)
    if membership is None:
        raise ValidationError("O modo assistido exige vínculo ativo com a campanha.")
    if form.status != Form.Status.PUBLISHED or not form.current_version_id:
        raise ValidationError("O formulário não está publicado.")
    if str(form.current_version_id) != str(version_id):
        raise PublicFormVersionConflict

    version = FormVersion.objects.select_related("form__purpose").get(pk=version_id)
    validate_submission_fields(version=version, fields=fields)
    route = f"/v1/campaigns/{form.campaign_id}/forms/{form.id}/assisted-submissions"
    actor_scope = f"membership:{membership.id}"
    key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    request_hash = canonical_json_hash(
        {"version_id": str(version_id), "fields": fields}
    )
    existing = IdempotencyRecord.objects.filter(
        campaign=form.campaign,
        actor_scope=actor_scope,
        route=route,
        key_hash=key_hash,
    ).first()
    if existing:
        if existing.request_hash != request_hash:
            raise IdempotencyConflict
        receipt_id = existing.result_ref["receipt_id"]
        return {
            "receipt_id": receipt_id,
            "status": "received",
            "message": "Recebemos sua solicitação.",
            "receipt_token": derive_receipt_token(receipt_id),
            "next_action": "processing",
        }, True

    submission = Submission.objects.create(
        tenant=form.tenant,
        campaign=form.campaign,
        created_by=actor,
        form_version=version,
        capture_mode=Submission.CaptureMode.ASSISTED,
        assisted_by_membership=membership,
        payload_ciphertext=encrypt_json(fields),
    )
    receipt_id = opaque_code()
    receipt_token = derive_receipt_token(receipt_id)
    SubmissionReceipt.objects.create(
        submission=submission,
        receipt_id=receipt_id,
        token_hash=hash_token(receipt_token),
        expires_at=timezone.now() + timedelta(days=30),
    )
    IdempotencyRecord.objects.create(
        tenant=form.tenant,
        campaign=form.campaign,
        actor_scope=actor_scope,
        route=route,
        key_hash=key_hash,
        request_hash=request_hash,
        status_code=202,
        result_ref={
            "submission_id": str(submission.id),
            "receipt_id": receipt_id,
        },
        expires_at=timezone.now() + timedelta(hours=24),
    )
    append_audit_event(
        actor=actor,
        tenant=form.tenant,
        campaign=form.campaign,
        action="submission.assisted_received",
        resource_type="submission",
        resource_id=submission.id,
        minimized_diff={
            "form_version_id": str(version.id),
            "assisted_by_membership_id": str(membership.id),
        },
        request_id=request_id,
    )
    enqueue_outbox_event(
        tenant=form.tenant,
        campaign=form.campaign,
        kind="submission.accepted.v1",
        aggregate_type="submission",
        aggregate_id=submission.id,
        aggregate_version=submission.row_version,
        payload_minimized={"submission_id": str(submission.id)},
    )
    return {
        "receipt_id": receipt_id,
        "status": "received",
        "message": "Recebemos sua solicitação.",
        "receipt_token": receipt_token,
        "next_action": "processing",
    }, False
