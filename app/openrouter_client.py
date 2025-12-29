"""
Shared OpenRouter API client for LLM operations.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx


OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL_NAME = "qwen/qwen3-max"

# Глобальный клиент для переиспользования (None до первой инициализации)
_openrouter_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()


def _normalize_proxy_url(proxy_url: str) -> str:
    """
    Нормализует URL прокси для httpx.
    Многие HTTP прокси требуют http:// в URL, даже для HTTPS трафика.
    """
    if not proxy_url:
        return proxy_url
    
    # Если URL начинается с https://, заменяем на http://
    # Это стандартная практика для HTTP прокси серверов
    if proxy_url.startswith("https://"):
        return proxy_url.replace("https://", "http://", 1)
    
    return proxy_url


async def get_openrouter_client() -> httpx.AsyncClient:
    """
    Lazy initialization глобального httpx.AsyncClient с поддержкой прокси.
    Клиент создается один раз и переиспользуется для всех запросов.
    """
    global _openrouter_client
    if _openrouter_client is None:
        async with _client_lock:
            if _openrouter_client is None:
                proxy_url = os.getenv("OPENROUTER_PROXY_URL", "").strip()
                
                timeout = httpx.Timeout(connect=20.0, read=30.0, write=15.0, pool=15.0)
                client_kwargs: dict[str, Any] = {
                    "timeout": timeout,
                    "follow_redirects": True,
                }
                
                if proxy_url:
                    # Нормализуем URL прокси (https:// -> http:// для HTTP прокси)
                    normalized_proxy = _normalize_proxy_url(proxy_url)
                    # httpx использует параметр 'proxy' для строки URL
                    client_kwargs["proxy"] = normalized_proxy
                
                _openrouter_client = httpx.AsyncClient(**client_kwargs)
    return _openrouter_client

