import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure project root is on sys.path when running as a script
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services import schedule_parse_history
from core.config import settings
from db.models import Message
from db.session import async_session_factory
from workers.celery_app import celery_app
from scripts.resolve_chat_id import resolve_chat_id  # type: ignore[wrong-import-position]


def _read_env() -> tuple[str, Optional[str], Optional[int], int]:
    load_dotenv()
    phone = os.getenv("TELEGRAM_PHONE")
    if not phone:
        raise RuntimeError("TELEGRAM_PHONE не найден в .env. Добавьте номер аккаунта.")
    chat_identifier = os.getenv("TEST_PUBLIC_CHAT")  # e.g., @durov or https://t.me/durov
    test_chat_id: Optional[int] = None
    test_chat_str = os.getenv("TEST_PUBLIC_CHAT_ID") or (str(settings.test_public_chat_id) if settings.test_public_chat_id else None)
    if test_chat_str and test_chat_str.strip():
        try:
            test_chat_id = int(test_chat_str)
        except ValueError:
            # Ignore invalid numeric id, we will rely on identifier
            test_chat_id = None

    days = int(os.getenv("TEST_HISTORY_DAYS", "3"))
    return phone, chat_identifier, test_chat_id, days


async def _print_messages_for_chat(session: AsyncSession, chat_id: int, since: Optional[datetime] = None, limit: int = 10) -> None:
    if since is None:
        since = datetime.now(tz=timezone.utc) - timedelta(days=7)
    total = await session.scalar(
        select(func.count()).select_from(Message).where(Message.chat_id == chat_id, Message.message_date >= since)
    )
    print(f"Сообщений в БД для chat_id={chat_id} с {since.isoformat()}: {total or 0}")
    rows = (await session.execute(
        select(Message).where(Message.chat_id == chat_id, Message.message_date >= since).order_by(Message.message_date.desc()).limit(limit)
    )).scalars().all()
    if not rows:
        print("Нет сообщений для отображения.")
        return
    print("Последние сообщения:")
    for m in rows:
        preview = (m.text or "").replace("\n", " ")
        if len(preview) > 80:
            preview = preview[:77] + "..."
        print(f"- id={m.message_id} date={m.message_date.isoformat()} sender={m.sender_id} text='{preview}'")


async def main() -> None:
    phone, chat_identifier, env_chat_id, days = _read_env()

    # Determine what to send to Celery (prefer resolvable string identifier)
    chat_entity_for_celery: Optional[object] = chat_identifier if (chat_identifier and chat_identifier.strip()) else env_chat_id
    if chat_entity_for_celery is None:
        raise RuntimeError("Не задан ни TEST_PUBLIC_CHAT (@username/ссылка), ни TEST_PUBLIC_CHAT_ID.")

    # Resolve numeric chat_id for DB printing (if we only have identifier)
    resolved_chat_id: Optional[int] = None
    if chat_identifier:
        try:
            cid, title = await resolve_chat_id(account_phone=phone, identifier=chat_identifier)
            resolved_chat_id = cid
            if title:
                print(f"Определено название чата: {title}")
        except Exception as e:
            print(f"Не удалось разрешить chat_id по идентификатору '{chat_identifier}': {e}")
    else:
        resolved_chat_id = env_chat_id

    print(f"Запускаю parse_history для phone={phone}, entity={chat_entity_for_celery}, days={days}")

    # Отправка задачи в Celery через наш сервис (использует broker/result backend из настроек)
    task_id = schedule_parse_history(account_phone=phone, chat_entity=chat_entity_for_celery, days=days)
    print(f"Celery task отправлена: id={task_id}")

    # Отслеживаем статус задачи через result backend
    async_result = celery_app.AsyncResult(task_id)
    start = datetime.now(tz=timezone.utc)
    timeout = timedelta(seconds=int(os.getenv("DEMO_CELERY_TIMEOUT_SECONDS", "60")))
    last_state = None
    pending_warn_after = float(os.getenv("DEMO_PENDING_WARN_AFTER", "10"))
    pending_since = None
    while True:
        state = async_result.state
        if state != last_state:
            print(f"[Celery] state={state}")
            last_state = state
        if state == "PENDING":
            if pending_since is None:
                pending_since = datetime.now(tz=timezone.utc)
            elif (datetime.now(tz=timezone.utc) - pending_since).total_seconds() > pending_warn_after:
                print("Задача остаётся PENDING. Похоже, воркер Celery не запущен или не видит брокер.")
                break
        if async_result.ready():
            break
        if datetime.now(tz=timezone.utc) - start > timeout:
            print("Таймаут ожидания результата Celery.")
            break
        await asyncio.sleep(1.0)

    if async_result.successful():
        result = async_result.get(propagate=False)
        print(f"[Celery] SUCCESS: result={result}")
    elif async_result.failed():
        print(f"[Celery] FAILURE: {async_result.result}")
        tb = getattr(async_result, "traceback", None)
        if tb:
            print(tb)

    # Выводим данные из Postgres, чтобы показать результат
    # Выводим данные из Postgres, чтобы показать результат (если chat_id удалось определить)
    if resolved_chat_id is not None:
        since_dt = datetime.now(tz=timezone.utc) - timedelta(days=days)
        async with async_session_factory() as session:
            await _print_messages_for_chat(session, chat_id=resolved_chat_id, since=since_dt, limit=10)
    else:
        print("Не удалось определить числовой chat_id для вывода сообщений из БД. Укажите TEST_PUBLIC_CHAT_ID или корректный TEST_PUBLIC_CHAT.")


if __name__ == "__main__":
    asyncio.run(main())


