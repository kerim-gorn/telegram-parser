from celery import Celery

from core.config import settings
from celery.schedules import crontab

# Celery configuration
celery_app = Celery(
    "telegram_parser",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["workers.historical_worker", "workers.beat_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    broker_connection_retry_on_startup=True,
)

celery_app.conf.beat_schedule = {
    "schedule-parsing-daily-3am": {
        "task": "workers.beat_tasks.schedule_parsing",
        "schedule": crontab(minute=0, hour=3),
    },
    "bootstrap-new-channels-every-15-minutes": {
        "task": "workers.beat_tasks.bootstrap_new_channels",
        "schedule": crontab(minute="*/15"),
    },
}


