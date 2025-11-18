from typing import Union

from workers.celery_app import celery_app


def schedule_parse_history(account_phone: str, chat_entity: Union[int, str], days: int = 7) -> str:
    """
    Enqueue a Celery task for historical parsing (backfill).
    Returns Celery task id.
    """
    task = celery_app.send_task(
        "workers.historical_worker.backfill_chat",
        kwargs={"account_phone": account_phone, "chat_entity": chat_entity, "days": days},
    )
    return task.id


def schedule_backfill_chat(account_phone: str, chat_entity: Union[int, str], days: int = 30) -> str:
    """
    Explicit alias for backfill task.
    """
    task = celery_app.send_task(
        "workers.historical_worker.backfill_chat",
        kwargs={"account_phone": account_phone, "chat_entity": chat_entity, "days": days},
    )
    return task.id


