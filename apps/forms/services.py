from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.campaigns.services import require_campaign_permission
from apps.core.services import append_audit_event, enqueue_outbox_event

from .models import Form, FormVersion, PrivacyNoticeVersion, ProcessingPurpose


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
