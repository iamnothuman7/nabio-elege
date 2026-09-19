from datetime import timedelta

from celery import current_app
from django.db import transaction
from django.utils import timezone

from .models import OutboxEvent


EVENT_TASKS = {
    "submission.accepted.v1": "forms.process_submission",
}


@transaction.atomic
def claim_outbox_event(event_id):
    event = OutboxEvent.objects.select_for_update().filter(pk=event_id).first()
    if event is None:
        return None
    if event.status != OutboxEvent.Status.PENDING or event.available_at > timezone.now():
        return None
    event.status = OutboxEvent.Status.PROCESSING
    event.attempts += 1
    event.save(update_fields=["status", "attempts", "updated_at"])
    return event


def dispatch_outbox_event(event_id, *, send_task=None):
    event = claim_outbox_event(event_id)
    if event is None:
        return False
    send_task = send_task or current_app.send_task
    task_name = EVENT_TASKS.get(event.kind)
    if task_name is None:
        _record_failure(event.id, "unsupported_event")
        return False
    try:
        send_task(task_name, args=[event.aggregate_id])
    except Exception as exc:
        _record_failure(event.id, type(exc).__name__)
        raise
    OutboxEvent.objects.filter(pk=event.id).update(
        status=OutboxEvent.Status.PUBLISHED,
        published_at=timezone.now(),
        last_error_code="",
    )
    return True


@transaction.atomic
def _record_failure(event_id, error_code):
    event = OutboxEvent.objects.select_for_update().get(pk=event_id)
    event.last_error_code = error_code[:120]
    if event.attempts >= 10:
        event.status = OutboxEvent.Status.FAILED
    else:
        event.status = OutboxEvent.Status.PENDING
        delay_seconds = min(15 * (2 ** max(event.attempts - 1, 0)), 3600)
        event.available_at = timezone.now() + timedelta(seconds=delay_seconds)
    event.save(
        update_fields=[
            "status",
            "available_at",
            "last_error_code",
            "updated_at",
        ]
    )
