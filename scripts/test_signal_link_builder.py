from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path when running as:
#   python scripts/test_signal_link_builder.py
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.signal_notifier import _build_link


def _strip_prefix(s: str) -> str:
    return s.lstrip("\n")


def test_no_thread_with_username() -> None:
    link = _build_link(chat_id=None, chat_username="@channel", message_id=123, message_thread_id=None)
    assert _strip_prefix(link) == '<a href="https://t.me/channel/123">Открыть оригинал</a>'


def test_with_thread_and_username() -> None:
    link = _build_link(chat_id=None, chat_username="@channel", message_id=456, message_thread_id=10)
    assert _strip_prefix(link) == '<a href="https://t.me/channel/10/456">Открыть оригинал</a>'


def test_no_thread_with_chat_id_only() -> None:
    link = _build_link(chat_id=-1001234567890, chat_username=None, message_id=789, message_thread_id=None)
    assert _strip_prefix(link) == '<a href="https://t.me/c/1001234567890/789">Открыть оригинал</a>'


def test_with_thread_and_chat_id_only() -> None:
    link = _build_link(chat_id=-1001234567890, chat_username=None, message_id=42, message_thread_id=7)
    assert _strip_prefix(link) == '<a href="https://t.me/c/1001234567890/7/42">Открыть оригинал</a>'


if __name__ == "__main__":
    # Simple ad-hoc runner
    test_no_thread_with_username()
    test_with_thread_and_username()
    test_no_thread_with_chat_id_only()
    test_with_thread_and_chat_id_only()
    print("All _build_link tests passed.")


