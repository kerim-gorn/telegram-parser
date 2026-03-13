from typing import Any, Union

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


def schedule_auto_reply(payload: dict[str, Any]) -> str:
    """
    Enqueue a Celery task for auto-reply DM.
    Returns Celery task id.
    """
    delay_seconds_raw = payload.get("delay_seconds") or 0
    try:
        delay_seconds = int(delay_seconds_raw)
    except (TypeError, ValueError):
        delay_seconds = 0

    send_kwargs: dict[str, Any] = {
        "kwargs": {"payload": payload},
    }
    if delay_seconds > 0:
        send_kwargs["countdown"] = delay_seconds

    task = celery_app.send_task(
        "workers.auto_reply_worker.send_auto_reply",
        **send_kwargs,
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


