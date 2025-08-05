import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

app = Celery('backend')

app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'execute-orders-every-2-seconds': {
        'task': 'rooms.tasks.execute_pending_orders',
        'schedule': 2.0,
    },
}
