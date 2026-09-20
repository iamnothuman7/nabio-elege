from celery import shared_task

from .inventory import expire_due_reservations


@shared_task(name="workspace.expire_stock_reservations")
def expire_stock_reservations():
    return expire_due_reservations()
