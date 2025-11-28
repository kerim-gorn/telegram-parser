import asyncio
import os
import sys
from argparse import ArgumentParser
from datetime import datetime, timezone

from dotenv import load_dotenv
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties


async def main() -> None:
    parser = ArgumentParser(description="Send a test signal via Telegram Bot")
    parser.add_argument("--text", type=str, default="Smoke test: signal notifier", help="Message text")
    args = parser.parse_args()

    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id_env = os.getenv("SIGNALS_BOT_CHAT_ID")
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set")
        sys.exit(1)
    if not chat_id_env:
        print("ERROR: SIGNALS_BOT_CHAT_ID is not set")
        sys.exit(1)

    try:
        chat_id = int(chat_id_env) if chat_id_env.strip().lstrip("-").isdigit() else chat_id_env
    except Exception:
        chat_id = chat_id_env

    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    body = (
        f"<b>🧪 Smoke Test</b>\n"
        f"<b>Time:</b> {now}\n"
        f"<b>Text:</b>\n"
        f"<pre>{args.text}</pre>"
    )

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await bot.send_message(chat_id, body, disable_web_page_preview=True)
        print("OK: sent")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())


