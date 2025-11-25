import asyncio
import random
from functools import wraps
from typing import Any, Awaitable, Callable, Optional, TypeVar

from telethon import errors
try:
    # aiogram v3
    from aiogram.exceptions import TelegramRetryAfter as _AiogramRetryAfter  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - optional dependency
    _AiogramRetryAfter = None  # type: ignore[assignment]

from typing_extensions import ParamSpec

P = ParamSpec("P")
R = TypeVar("R")


def handle_flood_wait(
    max_retries: int = 3,
    initial_jitter_min: float = 5.0,
    initial_jitter_max: float = 15.0,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[Optional[R]]]]:
    """
    Decorator for robust async handling of Telethon FloodWaitError with jitter
    and exponential backoff.
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[Optional[R]]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> Optional[R]:
            retries = 0
            while retries < max_retries:
                try:
                    return await func(*args, **kwargs)
                except errors.FloodWaitError as e:
                    wait_time = getattr(e, "seconds", 5)
                    jitter = random.uniform(
                        initial_jitter_min * (retries + 1),
                        initial_jitter_max * (retries + 1),
                    )
                    total_sleep = wait_time + jitter
                    print(
                        f"FloodWaitError: {e}. Sleeping {total_sleep:.2f}s "
                        f"(attempt {retries + 1}/{max_retries})..."
                    )
                    await asyncio.sleep(total_sleep)
                    retries += 1
                except Exception as e:  # noqa: BLE001
                    # Handle aiogram rate limiting dynamically, if aiogram is installed
                    if _AiogramRetryAfter is not None and isinstance(e, _AiogramRetryAfter):
                        wait_time = getattr(e, "retry_after", 5)
                        jitter = random.uniform(
                            initial_jitter_min * (retries + 1),
                            initial_jitter_max * (retries + 1),
                        )
                        total_sleep = wait_time + jitter
                        print(
                            f"AiogramRetryAfter: waiting {total_sleep:.2f}s "
                            f"(attempt {retries + 1}/{max_retries})..."
                        )
                        await asyncio.sleep(total_sleep)
                        retries += 1
                        continue
                    print(f"Unhandled error in {func.__name__}: {e}")
                    raise
            print(f"Reached max retries ({max_retries}) for {func.__name__}. Cancelling.")
            return None

        return wrapper

    return decorator



