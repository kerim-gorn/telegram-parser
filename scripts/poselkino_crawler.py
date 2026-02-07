#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import math
import os
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx

BASE_URL = "https://poselkino.ru/poselki/"
OUTPUT_PATH = "data/poselkino_names.json"
PROGRESS_PATH = "data/poselkino_progress.json"
NAME_PREFIX = "Коттеджный поселок "


@dataclass
class ParseResult:
    names: list[str]
    max_page: int


class PoselkinoListParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._current_href: str | None = None
        self._current_text: list[str] = []
        self._names: list[str] = []
        self._max_page: int = 1

    @property
    def names(self) -> list[str]:
        return self._names

    @property
    def max_page(self) -> int:
        return self._max_page

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = None
        for key, value in attrs:
            if key == "href":
                href = value
                break
        if not href:
            return
        self._update_max_page_from_href(href)
        if href.startswith("/poselki/") and href.count("/") >= 2:
            self._current_href = href
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href is None:
            return
        text = data.strip()
        if text:
            self._current_text.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a":
            return
        if self._current_href is None:
            return
        text = " ".join(self._current_text).strip()
        if text.startswith(NAME_PREFIX):
            name = text[len(NAME_PREFIX) :].strip()
            if name:
                self._names.append(name)
        self._current_href = None
        self._current_text = []

    def _update_max_page_from_href(self, href: str) -> None:
        try:
            query = urlsplit(href).query
        except ValueError:
            return
        if not query:
            return
        params = parse_qs(query)
        if "PAGEN_1" not in params:
            return
        try:
            page = int(params["PAGEN_1"][0])
        except (ValueError, TypeError, IndexError):
            return
        if page > self._max_page:
            self._max_page = page


def build_page_url(base_url: str, page: int) -> str:
    if page <= 1:
        return base_url
    parts = urlsplit(base_url)
    params = parse_qs(parts.query)
    params["PAGEN_1"] = [str(page)]
    query = urlencode(params, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def extract_names_and_pages(html: str) -> ParseResult:
    parser = PoselkinoListParser()
    parser.feed(html)
    return ParseResult(names=parser.names, max_page=parser.max_page)


def extract_total_count(html: str) -> int | None:
    match = re.search(r"Поселки\s*-\s*Страница\s*\d+\s*([0-9\s\u00a0]+)", html)
    if not match:
        return None
    digits = re.sub(r"[^\d]", "", match.group(1))
    if not digits:
        return None
    return int(digits)


def dedupe_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def load_progress() -> dict[str, object]:
    if not os.path.exists(PROGRESS_PATH):
        return {}
    try:
        with open(PROGRESS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_progress(names: list[str], last_page: int, max_page: int) -> None:
    output_dir = PROGRESS_PATH.rsplit("/", 1)[0]
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    payload = {
        "last_page": last_page,
        "max_page": max_page,
        "names": names,
    }
    with open(PROGRESS_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def save_output(names: list[str]) -> None:
    output_dir = OUTPUT_PATH.rsplit("/", 1)[0]
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(names, handle, ensure_ascii=False, indent=2)


async def fetch_with_retries(
    client: httpx.AsyncClient,
    url: str,
    attempts: int = 4,
    delay_s: float = 1.0,
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if attempt < attempts:
                if isinstance(exc, httpx.HTTPStatusError):
                    status = exc.response.status_code
                    if status in {429, 500, 502, 503, 504}:
                        await asyncio.sleep(delay_s * (attempt + 2))
                        continue
                await asyncio.sleep(delay_s * attempt)
    assert last_exc is not None
    raise last_exc


async def crawl() -> list[str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }
    progress = load_progress()
    last_page = int(progress.get("last_page", 0))
    all_names = list(progress.get("names", []))
    max_page = int(progress.get("max_page", 0))

    async with httpx.AsyncClient(
        headers=headers,
        timeout=20.0,
        follow_redirects=True,
    ) as client:
        first_response = await fetch_with_retries(client, build_page_url(BASE_URL, 1))
        first_result = extract_names_and_pages(first_response.text)
        total_count = extract_total_count(first_response.text)
        page_size = len(first_result.names)
        if total_count and page_size:
            max_page = max(max_page, math.ceil(total_count / page_size))
        max_page = max(max_page, first_result.max_page)

        if last_page < 1:
            all_names.extend(first_result.names)
            all_names = dedupe_keep_order(all_names)
            last_page = 1
            save_progress(all_names, last_page, max_page)
            save_output(all_names)

        if max_page < 1:
            fallback_response = await fetch_with_retries(client, build_page_url(BASE_URL, 1))
            fallback_result = extract_names_and_pages(fallback_response.text)
            max_page = max(fallback_result.max_page, last_page)
            save_progress(all_names, last_page, max_page)

        for page in range(last_page + 1, max_page + 1):
            page_url = build_page_url(BASE_URL, page)
            response = await fetch_with_retries(client, page_url)
            page_result = extract_names_and_pages(response.text)
            if not page_result.names:
                print(f"No results on page {page}, stopping.")
                max_page = page - 1
                save_progress(all_names, last_page, max_page)
                break
            all_names.extend(page_result.names)
            all_names = dedupe_keep_order(all_names)
            last_page = page
            save_progress(all_names, last_page, max_page)
            save_output(all_names)
            print(f"Page {page}/{max_page}: +{len(page_result.names)} names")
            await asyncio.sleep(0.4)

    return all_names


async def main() -> None:
    names = await crawl()
    if not names:
        print("No names found. The site may have blocked the request.")
        return
    print(f"Saved {len(names)} names to {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
