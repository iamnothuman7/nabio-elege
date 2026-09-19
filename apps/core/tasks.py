from celery import shared_task
from django.utils import timezone

from .models import OutboxEvent
from .outbox import EVENT_TASKS, dispatch_outbox_event


@shared_task(name="core.dispatch_outbox")
def dispatch_outbox(limit=100):
    event_ids = list(
        OutboxEvent.objects.filter(
            status=OutboxEvent.Status.PENDING,
            available_at__lte=timezone.now(),
            kind__in=EVENT_TASKS,
        )
        .order_by("available_at")
        .values_list("id", flat=True)[:limit]
    )
    dispatched = 0
    for event_id in event_ids:
        if dispatch_outbox_event(event_id):
            dispatched += 1
    return dispatched
