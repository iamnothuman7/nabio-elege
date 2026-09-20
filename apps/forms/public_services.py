import hashlib
import re
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.core.crypto import derive_receipt_token, encrypt_json, hash_token
from apps.core.models import IdempotencyRecord
from apps.core.services import (
    append_audit_event,
    canonical_json_hash,
    enqueue_outbox_event,
)

from .models import Form, FormVersion, Manifestation, SourceLink, Submission, SubmissionReceipt, opaque_code


class PublicFormUnavailable(Exception):
    pass


class PublicFormVersionConflict(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


SUPPORTED_FIELD_TYPES = {
    "short_text",
    "long_text",
    "email",
    "phone",
    "single_choice",
    "multiple_choice",
    "boolean",
}


def _published_context(source_link):
    form = source_link.form
    now = timezone.now()
    if form.campaign.tenant.status != "active" or form.campaign.phase in {"closing", "archived"} or form.purpose.status != "active":
        raise PublicFormUnavailable
    if not source_link.is_active:
        raise PublicFormUnavailable
    if form.status != Form.Status.PUBLISHED or not form.current_version_id:
        raise PublicFormUnavailable
    if form.opens_at and form.opens_at > now:
        raise PublicFormUnavailable
    if form.closes_at and form.closes_at <= now:
        raise PublicFormUnavailable
    return form.current_version


def get_public_form(public_code):
    source_link = (
        SourceLink.objects.select_related(
            "form__current_version__notice_version", "form__purpose"
        )
        .filter(public_code=public_code)
        .first()
    )
    if source_link is None:
        raise PublicFormUnavailable
    version = _published_context(source_link)
    return source_link, version


def validate_submission_fields(*, version, fields):
    if not isinstance(fields, dict):
        raise ValidationError({"fields": "Os campos devem formar um objeto JSON."})

    schema_fields = version.schema_json.get("fields", [])
    definitions = {}
    for definition in schema_fields:
        name = definition.get("name")
        field_type = definition.get("type")
        if not name or field_type not in SUPPORTED_FIELD_TYPES:
            raise ValidationError("A versão publicada contém um campo não suportado.")
        if name not in version.form.purpose.allowed_fields:
            raise ValidationError("A versão publicada contém campo fora da finalidade aprovada.")
        definitions[name] = definition

    unknown = sorted(set(fields) - set(definitions))
    if unknown:
        raise ValidationError({"fields": "O envio contém campos não permitidos."})

    errors = {}
    for name, definition in definitions.items():
        value = fields.get(name)
        if definition.get("required") and (value is None or value == ""):
            errors.setdefault(name, []).append("Este campo é obrigatório.")
            continue
        if value is None or value == "":
            continue
        field_type = definition["type"]
        if field_type in {"short_text", "long_text", "email", "phone"}:
            if not isinstance(value, str):
                errors.setdefault(name, []).append("Informe um texto válido.")
                continue
            limits = {"short_text": 150, "long_text": 2000, "email": 254, "phone": 32}
            if len(value) > min(definition.get("max_length", limits[field_type]), limits[field_type]):
                errors.setdefault(name, []).append("O valor excede o limite permitido.")
            if field_type == "phone" and not re.fullmatch(r"\+[1-9][0-9]{7,14}", value):
                errors.setdefault(name, []).append("Use o formato internacional, como +5585999999999.")
            if field_type == "email":
                try:
                    validate_email(value)
                except ValidationError:
                    errors.setdefault(name, []).append("Informe um e-mail válido.")
        elif field_type == "boolean" and not isinstance(value, bool):
            errors.setdefault(name, []).append("Informe verdadeiro ou falso.")
        elif field_type == "single_choice":
            if value not in definition.get("options", []):
                errors.setdefault(name, []).append("Escolha uma opção permitida.")
        elif field_type == "multiple_choice":
            options = set(definition.get("options", []))
            if not isinstance(value, list) or any(not isinstance(item, str) or item not in options for item in value):
                errors.setdefault(name, []).append("Escolha apenas opções permitidas.")

    if "adult_declaration" in definitions and fields.get("adult_declaration") is not True:
        errors["adult_declaration"] = ["Este formulário atende somente pessoas com 18 anos ou mais."]

    if errors:
        raise ValidationError(errors)


@transaction.atomic
def receive_public_submission(
    *, public_code, version_id, fields, idempotency_key, request_id=None
):
    if not idempotency_key or len(idempotency_key) > 200:
        raise ValidationError(
            {"Idempotency-Key": "Envie uma chave de idempotência válida."}
        )

    source_link = (
        SourceLink.objects.select_for_update()
        .filter(public_code=public_code)
        .first()
    )
    if source_link is None:
        raise PublicFormUnavailable
    source_link.form = Form.objects.select_for_update().get(pk=source_link.form_id)
    current_version = _published_context(source_link)
    if str(current_version.id) != str(version_id):
        raise PublicFormVersionConflict

    validate_submission_fields(version=current_version, fields=fields)
    route = f"/v1/public/forms/{public_code}/submissions"
    actor_scope = f"public-link:{source_link.id}"
    key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    request_hash = salted_hmac("submission-idempotency", canonical_json_hash(
        {"version_id": str(version_id), "fields": fields}
    ), algorithm="sha256").hexdigest()
    existing = IdempotencyRecord.objects.filter(
        campaign=source_link.campaign,
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
        tenant=source_link.tenant,
        campaign=source_link.campaign,
        form_version=current_version,
        source_link=source_link,
        capture_mode=Submission.CaptureMode.DIRECT,
        payload_ciphertext=encrypt_json(fields),
    )
    Manifestation.objects.create(tenant=submission.tenant, campaign=submission.campaign, submission=submission, purpose=current_version.form.purpose, notice_version=current_version.notice_version, choice="granted" if fields.get("consent") is True else "denied", method="direct", confirmed_at=timezone.now() if fields.get("consent") is True else None)
    receipt_id = opaque_code()
    receipt_token = derive_receipt_token(receipt_id)
    SubmissionReceipt.objects.create(
        submission=submission,
        receipt_id=receipt_id,
        token_hash=hash_token(receipt_token),
        expires_at=timezone.now() + timedelta(days=30),
    )
    result_ref = {
        "submission_id": str(submission.id),
        "receipt_id": receipt_id,
    }
    IdempotencyRecord.objects.create(
        tenant=source_link.tenant,
        campaign=source_link.campaign,
        actor_scope=actor_scope,
        route=route,
        key_hash=key_hash,
        request_hash=request_hash,
        status_code=202,
        result_ref=result_ref,
        expires_at=timezone.now() + timedelta(hours=24),
    )
    append_audit_event(
        actor=None,
        tenant=source_link.tenant,
        campaign=source_link.campaign,
        action="submission.received",
        resource_type="submission",
        resource_id=submission.id,
        minimized_diff={
            "form_version_id": str(current_version.id),
            "capture_mode": Submission.CaptureMode.DIRECT,
        },
        request_id=request_id,
    )
    enqueue_outbox_event(
        tenant=source_link.tenant,
        campaign=source_link.campaign,
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
