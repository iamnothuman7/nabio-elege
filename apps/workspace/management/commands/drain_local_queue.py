from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.models import OutboxEvent
from apps.core.outbox import dispatch_outbox_event
from apps.forms.processing import process_submission


class Command(BaseCommand):
    help = "Processa a fila de submissões local sem Redis (somente demonstração)."

    def handle(self, *args, **options):
        if not getattr(settings, "LOCAL_DEMO", False):
            raise CommandError("Use Celery/Redis fora da demonstração local.")
        def send_task(name, args):
            if name != "forms.process_submission":
                raise CommandError("Consumidor não permitido.")
            process_submission(submission_id=args[0])
        count = 0
        for event in OutboxEvent.objects.filter(status="pending", kind="submission.accepted.v1", available_at__lte=timezone.now())[:100]:
            count += bool(dispatch_outbox_event(event.pk, send_task=send_task))
        self.stdout.write(f"Eventos processados: {count}")
