import asyncio
import json
from typing import Any, Iterable, Union

import aio_pika
from aio_pika import ExchangeType, Message, DeliveryMode
from aio_pika.abc import AbstractRobustConnection, AbstractChannel, AbstractExchange
from telethon import events
from telethon.errors.rpcerrorlist import AuthKeyUnregisteredError, SessionExpiredError
from telethon.utils import get_peer_id

from core.config import settings
from core.session_manager import SessionManager
from core.telethon_client import create_client_from_session


def _parse_chats(raw: str) -> list[Union[int, str]]:
    """
    Parse comma-separated chats into list of ints or usernames.
    Examples:
      CHATS_TO_LISTEN="-1001234567890,durov,  -10098765 "
    """
    if not raw:
        return []
    chats: list[Union[int, str]] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            chats.append(int(token))
        except ValueError:
            chats.append(token)
    return chats


async def _setup_rabbitmq() -> tuple[AbstractRobustConnection, AbstractChannel, AbstractExchange]:
    """
    Establish robust AMQP connection and declare a durable fanout exchange.
    """
    connection: AbstractRobustConnection = await aio_pika.connect_robust(settings.celery_broker_url)
    channel: AbstractChannel = await connection.channel()
    exchange: AbstractExchange = await channel.declare_exchange(
        settings.realtime_exchange_name, ExchangeType.FANOUT, durable=True
    )
    return connection, channel, exchange


async def _publish_message(exchange: AbstractExchange, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    msg = Message(body=body, content_type="application/json", delivery_mode=DeliveryMode.PERSISTENT)
    # Fanout ignores routing_key
    await exchange.publish(msg, routing_key="")


async def run_realtime_worker(account_id: str | None = None) -> None:
    """
    Persistent realtime worker:
      - Loads encrypted StringSession from Redis (stateless worker).
      - Connects to Telegram once and listens for events.NewMessage.
      - Immediately publishes message payloads to RabbitMQ fanout exchange.
    """
    acct_id = account_id or settings.telegram_account_id
    chats_filter: list[Union[int, str]] = _parse_chats(settings.realtime_chats_raw)

    session_manager = SessionManager(
        settings.redis_url,
        settings.telegram_session_prefix,
        settings.session_crypto_key,
    )

    while True:
        client = None
        amqp_connection: AbstractRobustConnection | None = None
        try:
            string_session = await session_manager.get_string_session(acct_id)
            if not string_session:
                raise RuntimeError(
                    f"No StringSession found in Redis for account '{acct_id}'. "
                    "Run scripts/onboard_account.py to bootstrap."
                )

            client = create_client_from_session(string_session)
            amqp_connection, channel, exchange = await _setup_rabbitmq()

            async with client:
                # Lightweight, rate-limited stats (once per 60s)
                stats: dict[str, Any] = {
                    "received": 0,
                    "published": 0,
                    "failed": 0,
                    "last_event": None,
                }

                async def _stats_reporter() -> None:
                    while True:
                        try:
                            await asyncio.sleep(60)
                            rcv = stats.get("received", 0)
                            pub = stats.get("published", 0)
                            fail = stats.get("failed", 0)
                            last = stats.get("last_event")
                            print(f"[Realtime] stats: received={rcv} published={pub} failed={fail} last={last}")
                            stats["received"] = 0
                            stats["published"] = 0
                            stats["failed"] = 0
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            # Do not spam on stats errors; continue
                            pass

                stats_task = asyncio.create_task(_stats_reporter())
                # Pre-resolve chat filters to ignore invalid entries
                effective_chats: list[Any] = []
                if chats_filter:
                    for ch in chats_filter:
                        try:
                            ent = await client.get_input_entity(ch)
                            effective_chats.append(ent)
                        except Exception as e:  # noqa: BLE001
                            print(f"[Realtime] Ignoring invalid chat filter entry '{ch}': {e}")

                # Register handler with resolved chats or without filter
                if effective_chats:
                    # Compute how many target chats are present in user's dialogs (joined/subscribed)
                    dialog_ids: set[int] = set()
                    try:
                        async for d in client.iter_dialogs():
                            try:
                                dialog_ids.add(get_peer_id(d.entity))
                            except Exception:
                                pass
                        target_ids = {get_peer_id(ent) for ent in effective_chats}
                        intersection_ids = target_ids & dialog_ids
                        # Keep only targets that are actually joined to avoid listening on non-joined channels
                        listening_chats = [ent for ent in effective_chats if get_peer_id(ent) in intersection_ids]
                        print(
                            f"[Realtime] Dialogs overlap: {len(intersection_ids)} of {len(effective_chats)} targets are in dialogs"
                        )
                    except Exception:
                        # Non-critical diagnostics
                        listening_chats = effective_chats
                    if listening_chats:
                        @client.on(events.NewMessage(chats=listening_chats))
                        async def _handler(event: Any) -> None:
                            try:
                                stats["received"] = int(stats.get("received", 0)) + 1
                                stats["last_event"] = {
                                    "chat_id": int(event.chat_id) if event.chat_id is not None else None,
                                    "message_id": int(event.message.id),
                                }
                                payload = {
                                    "event": "NewMessage",
                                    "chat_id": int(event.chat_id) if event.chat_id is not None else None,
                                    "message_id": int(event.message.id),
                                    "message": event.message.to_dict(),
                                }
                                await _publish_message(exchange, payload)
                                stats["published"] = int(stats.get("published", 0)) + 1
                            except Exception as e:  # noqa: BLE001
                                stats["failed"] = int(stats.get("failed", 0)) + 1
                                print(f"[Handler] Failed to publish message: {e}")
                        print(
                            f"[Realtime] Starting client. Listening on {len(listening_chats)} joined targets "
                            f"of {len(effective_chats)} configured."
                        )
                    else:
                        # No joined targets yet; do not register a broad catch-all handler.
                        print(
                            f"[Realtime] Starting client. Listening on 0 joined targets of {len(effective_chats)} configured."
                        )
                else:
                    @client.on(events.NewMessage())
                    async def _handler(event: Any) -> None:
                        try:
                            stats["received"] = int(stats.get("received", 0)) + 1
                            stats["last_event"] = {
                                "chat_id": int(event.chat_id) if event.chat_id is not None else None,
                                "message_id": int(event.message.id),
                            }
                            payload = {
                                "event": "NewMessage",
                                "chat_id": int(event.chat_id) if event.chat_id is not None else None,
                                "message_id": int(event.message.id),
                                "message": event.message.to_dict(),
                            }
                            await _publish_message(exchange, payload)
                            stats["published"] = int(stats.get("published", 0)) + 1
                        except Exception as e:  # noqa: BLE001
                            stats["failed"] = int(stats.get("failed", 0)) + 1
                            print(f"[Handler] Failed to publish message: {e}")

                try:
                    await client.run_until_disconnected()
                finally:
                    try:
                        stats_task.cancel()
                    except Exception:
                        pass
            print("[Realtime] Client disconnected gracefully. Restarting in 10s.")
            await asyncio.sleep(10)

        except (AuthKeyUnregisteredError, SessionExpiredError) as e:
            print(f"[Realtime] CRITICAL: Session invalid or expired: {e}. Sleeping 1h.")
            await asyncio.sleep(3600)
            break  # Let the container orchestrator restart us
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"[Realtime] Unhandled error: {e}. Retrying in 30s.")
            await asyncio.sleep(30)
        finally:
            if client is not None and client.is_connected():
                try:
                    await client.disconnect()
                except Exception:
                    pass
            if amqp_connection is not None:
                try:
                    await amqp_connection.close()
                except Exception:
                    pass


if __name__ == "__main__":
    asyncio.run(run_realtime_worker())

