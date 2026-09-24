from celery import shared_task
from django.db import connection

from apps.campaigns.models import Campaign
from apps.core.rls import database_scope

from .processing import process_submission


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    name="forms.process_submission",
)
def process_submission_task(self, submission_id, campaign_id=None):
    if campaign_id is None and connection.vendor == "postgresql":
        raise ValueError("Mensagem legada sem campanha: reenvie pela outbox revisada.")
    campaign = Campaign.objects.get(pk=campaign_id) if campaign_id else None
    with database_scope(campaign=campaign):
        submission = process_submission(submission_id=submission_id)
    return str(submission.id)
