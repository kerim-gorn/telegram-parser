from celery import Celery

from app.settings.config import settings


celery_app = Celery(
    "parser_llm",
    broker=settings.celery.broker_url or settings.rabbitmq.amqp_url,
    backend=settings.celery.result_backend or settings.redis.url,
)

celery_app.conf.update(
    timezone=settings.app.timezone,
    enable_utc=True,
)
