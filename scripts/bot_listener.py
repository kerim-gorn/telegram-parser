import asyncio
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.types import Message

import os
from dotenv import load_dotenv


async def run_bot_listener() -> None:
    """
    Persistent listener for a Telegram bot (via aiogram.Bot).
    - Uses TELEGRAM_BOT_TOKEN from .env (loaded via Settings).
    - Logs every incoming message the bot receives (private and group contexts).
    """
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set in environment or .env")
        return

    bot = Bot(token=token)
    dp = Dispatcher()

    stats: dict[str, Any] = {"received": 0, "last": None}

    async def _stats_reporter() -> None:
        while True:
            try:
                await asyncio.sleep(60)
                rcv = int(stats.get("received", 0))
                last = stats.get("last")
                print(f"[BotListener] stats: received={rcv} last={last}")
                stats["received"] = 0
            except asyncio.CancelledError:
                raise
            except Exception:
                # swallow and continue
                pass

    @dp.message()  # all incoming messages to the bot (private and groups)
    async def _on_message(message: Message) -> None:
        try:
            chat = message.chat
            from_user = message.from_user
            cid = int(chat.id) if chat else None
            mid = int(message.message_id)
            chat_type = getattr(chat, "type", None)
            text = message.text or message.caption or ""
            sender_username = None
            if from_user and from_user.username:
                sender_username = from_user.username if from_user.username.startswith("@") else f"@{from_user.username}"
            chat_username = None
            if chat and getattr(chat, "username", None):
                cu = getattr(chat, "username")
                if isinstance(cu, str) and cu:
                    chat_username = cu if cu.startswith("@") else f"@{cu}"
            kind = "private" if str(chat_type) == "private" else "group_or_channel"
            print(
                f"[BotListener] {kind} chat_id={cid} msg_id={mid} "
                f"sender={sender_username} chat={chat_username} text={text!r}"
            )
            stats["received"] = int(stats.get("received", 0)) + 1
            stats["last"] = {"chat_id": cid, "message_id": mid}
        except Exception as e:  # noqa: BLE001
            print(f"[BotListener] handler error: {e}")

    try:
        me = await bot.get_me()
        uname = getattr(me, "username", None) or str(getattr(me, "id", ""))
        if isinstance(uname, str) and uname and not uname.startswith("@"):
            uname = f"@{uname}"
        print(f"[BotListener] Started as {uname}")
    except Exception:
        print("[BotListener] Started (username unknown)")

    stats_task = asyncio.create_task(_stats_reporter())
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            handle_signals=True,
        )
    finally:
        try:
            stats_task.cancel()
        except Exception:
            pass
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run_bot_listener())
