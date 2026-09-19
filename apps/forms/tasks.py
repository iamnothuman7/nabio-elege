from celery import shared_task

from .processing import process_submission


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    name="forms.process_submission",
)
def process_submission_task(self, submission_id):
    submission = process_submission(submission_id=submission_id)
    return str(submission.id)
