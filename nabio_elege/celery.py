import os

from celery import Celery


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nabio_elege.settings")

app = Celery("nabio_elege")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
