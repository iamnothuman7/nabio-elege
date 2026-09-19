from django.db import transaction

from apps.core.crypto import blind_index, decrypt_json, encrypt_json
from apps.core.services import append_audit_event, enqueue_outbox_event

from .models import ContactPoint, Person, ServiceRequest, Submission


@transaction.atomic
def process_submission(*, submission_id):
    submission = (
        Submission.objects.select_for_update()
        .select_related(
            "form_version__form__purpose__retention_policy",
            "campaign",
            "tenant",
        )
        .get(pk=submission_id)
    )
    if submission.processing_status in {
        Submission.ProcessingStatus.PROCESSED,
        Submission.ProcessingStatus.REVIEW_REQUIRED,
    }:
        return submission

    submission.processing_status = Submission.ProcessingStatus.PROCESSING
    submission.save(update_fields=["processing_status", "row_version", "updated_at"])
    payload = decrypt_json(submission.payload_ciphertext)

    person = None
    possible_duplicate = False
    contact_values = []
    for field_name, contact_type in (
        ("email", ContactPoint.Type.EMAIL),
        ("phone", ContactPoint.Type.PHONE),
    ):
        value = payload.get(field_name)
        if value:
            match_hmac = blind_index(value, campaign_id=submission.campaign_id)
            possible_duplicate = possible_duplicate or ContactPoint.objects.filter(
                person__campaign=submission.campaign,
                type=contact_type,
                match_hmac=match_hmac,
            ).exists()
            contact_values.append((contact_type, value, match_hmac))

    if possible_duplicate:
        submission.processing_status = Submission.ProcessingStatus.REVIEW_REQUIRED
        event_kind = "person.review_requested.v1"
    else:
        display_name = payload.get("name")
        if display_name:
            purpose = submission.form_version.form.purpose
            person = Person.objects.create(
                tenant=submission.tenant,
                campaign=submission.campaign,
                created_by=submission.created_by,
                display_name_ciphertext=encrypt_json({"value": display_name}),
                retention_policy=purpose.retention_policy,
            )
            for contact_type, value, match_hmac in contact_values:
                ContactPoint.objects.create(
                    person=person,
                    type=contact_type,
                    value_ciphertext=encrypt_json({"value": value}),
                    match_hmac=match_hmac,
                )
        submission.processing_status = Submission.ProcessingStatus.PROCESSED
        event_kind = "submission.processed.v1"

    message = payload.get("message")
    if message:
        ServiceRequest.objects.create(
            tenant=submission.tenant,
            campaign=submission.campaign,
            created_by=submission.created_by,
            person=person,
            submission=submission,
            category=submission.form_version.form.purpose.code,
        )

    submission.save(update_fields=["processing_status", "row_version", "updated_at"])
    append_audit_event(
        actor=submission.created_by,
        tenant=submission.tenant,
        campaign=submission.campaign,
        action="submission.processed",
        resource_type="submission",
        resource_id=submission.id,
        minimized_diff={
            "result": submission.processing_status,
            "person_created": bool(person),
            "service_request_created": bool(message),
        },
    )
    enqueue_outbox_event(
        tenant=submission.tenant,
        campaign=submission.campaign,
        kind=event_kind,
        aggregate_type="submission",
        aggregate_id=submission.id,
        aggregate_version=submission.row_version,
        payload_minimized={"submission_id": str(submission.id)},
    )
    return submission
