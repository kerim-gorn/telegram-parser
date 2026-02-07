import asyncio
import json
import logging
import os
import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from dotenv import load_dotenv
from telethon import errors
from telethon.tl import functions, types

# Ensure project root on sys.path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config_loader import get_account_ids_from_config  # noqa: E402
from core.anti_ban import handle_flood_wait  # noqa: E402
from core.config import settings  # noqa: E402
from core.session_manager import SessionManager  # noqa: E402
from core.telethon_client import create_client_from_session  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_LOG_PATH = Path("logs/search_public_chats.log")


@dataclass(frozen=True)
class SearchResult:
    query: str
    username: Optional[str]
    title: Optional[str]
    entity_id: int
    entity_type: str


def _read_queries(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Input JSON must be a list of strings.")
    seen: set[str] = set()
    out: list[str] = []
    for item in payload:
        if not isinstance(item, str):
            raise ValueError("Input JSON must be a list of strings.")
        q = item.strip()
        if not q:
            continue
        if q in seen:
            continue
        seen.add(q)
        out.append(q)
    return out


def _progress_path(input_path: Path) -> Path:
    name = input_path.name
    if input_path.suffix:
        base = name[: -len(input_path.suffix)]
    else:
        base = name
    return input_path.with_name(f"{base}.progress.json")


def _load_progress(progress_path: Path) -> int:
    if not progress_path.exists():
        return 0
    try:
        payload = json.loads(progress_path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to read progress file: %s", progress_path)
        return 0
    next_index = payload.get("next_index")
    try:
        return max(0, int(next_index))
    except Exception:
        logger.warning("Invalid progress file: %s", progress_path)
        return 0


def _save_progress(progress_path: Path, next_index: int, total: int) -> None:
    progress_path.write_text(
        json.dumps(
            {
                "next_index": int(next_index),
                "total": int(total),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _default_output_path(input_path: Path) -> Path:
    name = input_path.name
    if input_path.suffix:
        base = name[: -len(input_path.suffix)]
    else:
        base = name
    return input_path.with_name(f"{base}.results.jsonl")


def _load_existing_keys(output_path: Path) -> set[tuple[int, str]]:
    if not output_path.exists():
        return set()
    keys: set[tuple[int, str]] = set()
    for line in output_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            logger.warning("Malformed JSON line in results file: %s", output_path)
            continue
        entity_id = item.get("entity_id")
        username = item.get("username") or ""
        try:
            key = (int(entity_id), str(username))
        except Exception:
            logger.warning("Invalid entity_id in results file: %s", output_path)
            continue
        keys.add(key)
    return keys


def _extract_search_results(query: str, result) -> list[SearchResult]:
    out: list[SearchResult] = []
    for chat in getattr(result, "chats", []) or []:
        entity_type = "unknown"
        if isinstance(chat, types.Channel):
            if getattr(chat, "megagroup", False):
                entity_type = "group"
            elif getattr(chat, "broadcast", False):
                entity_type = "channel"
            else:
                entity_type = "channel"
        elif isinstance(chat, types.Chat):
            entity_type = "group"
        else:
            continue
        out.append(
            SearchResult(
                query=query,
                username=getattr(chat, "username", None),
                title=getattr(chat, "title", None),
                entity_id=int(chat.id),
                entity_type=entity_type,
            )
        )
    return out


@handle_flood_wait(max_retries=3, initial_jitter_min=5.0, initial_jitter_max=15.0)
async def _search_request(client, query: str, limit: int):
    return await client(functions.contacts.SearchRequest(q=query, limit=limit))


async def _search_with_backoff(
    client,
    query: str,
    limit: int,
    max_attempts: int,
    backoff_base: float,
    backoff_factor: float,
    backoff_cap: float,
    jitter_min: float,
    jitter_max: float,
) -> list[SearchResult]:
    delay = backoff_base
    for attempt in range(1, max_attempts + 1):
        try:
            result = await _search_request(client, query, limit)
            if result is None:
                raise RuntimeError("SearchRequest returned None")
            return _extract_search_results(query, result)
        except (errors.RPCError, asyncio.TimeoutError, OSError, RuntimeError) as e:
            if attempt >= max_attempts:
                logger.error("Search failed after %s attempts. query=%s error=%s", attempt, query, e)
                return []
            jitter = os.urandom(1)[0] / 255.0
            sleep_for = min(delay, backoff_cap) + (jitter_min + (jitter_max - jitter_min) * jitter)
            logger.warning(
                "Search retry in %.2fs (attempt %s/%s). query=%s error=%s",
                sleep_for,
                attempt,
                max_attempts,
                query,
                e,
            )
            await asyncio.sleep(sleep_for)
            delay = min(delay * backoff_factor, backoff_cap)
    return []


async def _search_account(
    account_id: str,
    queries: Sequence[str],
    output_path: Path,
    existing_keys: set[tuple[int, str]],
    limit: int,
    per_query_sleep_min: float,
    per_query_sleep_max: float,
    max_attempts: int,
    backoff_base: float,
    backoff_factor: float,
    backoff_cap: float,
    base_index: int,
    total_queries: int,
    progress_path: Path,
) -> int:
    session_manager = SessionManager(
        redis_url=settings.redis_url,
        key_prefix=settings.telegram_session_prefix,
        encryption_key=settings.session_crypto_key,
    )
    try:
        string_session = await session_manager.get_string_session(account_id)
        if not string_session:
            logger.warning("[%s] no session in Redis, skipping", account_id)
            return 0
        client = create_client_from_session(string_session)
        saved = 0
        async with client:
            with output_path.open("a", encoding="utf-8") as f:
                for idx, query in enumerate(queries, start=1):
                    results = await _search_with_backoff(
                        client=client,
                        query=query,
                        limit=limit,
                        max_attempts=max_attempts,
                        backoff_base=backoff_base,
                        backoff_factor=backoff_factor,
                        backoff_cap=backoff_cap,
                        jitter_min=per_query_sleep_min,
                        jitter_max=per_query_sleep_max,
                    )
                    for item in results:
                        key = (item.entity_id, item.username or "")
                        if key in existing_keys:
                            continue
                        existing_keys.add(key)
                        f.write(json.dumps(item.__dict__, ensure_ascii=False) + "\n")
                        saved += 1
                    _save_progress(
                        progress_path=progress_path,
                        next_index=base_index + idx,
                        total=total_queries,
                    )
                    sleep_for = per_query_sleep_min + (
                        (per_query_sleep_max - per_query_sleep_min) * (os.urandom(1)[0] / 255.0)
                    )
                    logger.info(
                        "[%s] %s/%s '%s' done, sleep %.2fs",
                        account_id,
                        idx,
                        len(queries),
                        query,
                        sleep_for,
                    )
                    await asyncio.sleep(sleep_for)
        return saved
    finally:
        await session_manager.close()


def _chunks(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    if size <= 0:
        yield items
        return
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _build_parser() -> ArgumentParser:
    p = ArgumentParser(description="Search public Telegram channels/groups by queries list.")
    p.add_argument("input", help="Path to .json list of search queries")
    p.add_argument("--output", help="Output .jsonl path (default: рядом с input)")
    p.add_argument("--accounts", help="Comma-separated account_ids. Default: realtime_config.json")
    p.add_argument("--queries-per-account", type=int, default=5)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--sleep-min", type=float, default=4.0, help="Min jitter between queries")
    p.add_argument("--sleep-max", type=float, default=6.0, help="Max jitter between queries")
    p.add_argument("--attempts", type=int, default=3, help="Max attempts per query")
    p.add_argument("--backoff-base", type=float, default=3.0)
    p.add_argument("--backoff-factor", type=float, default=1.7)
    p.add_argument("--backoff-cap", type=float, default=60.0)
    p.add_argument("--reset-progress", action="store_true", help="Ignore progress and start from 0")
    return p


async def _amain() -> int:
    load_dotenv()
    log_path = DEFAULT_LOG_PATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        filename=str(log_path),
    )
    args = _build_parser().parse_args()
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error("Input file not found: %s", input_path)
        return 2
    output_path = Path(args.output) if args.output else _default_output_path(input_path)
    progress_path = _progress_path(input_path)
    if args.reset_progress and progress_path.exists():
        progress_path.unlink(missing_ok=True)

    try:
        queries = _read_queries(input_path)
    except Exception as e:
        logger.error("Failed to read queries: %s", e)
        return 2
    if not queries:
        logger.warning("No queries found in input: %s", input_path)
        return 0
    start_index = 0
    if not args.reset_progress:
        start_index = _load_progress(progress_path)
    if start_index >= len(queries):
        logger.info("Progress indicates all queries processed. Use --reset-progress to restart.")
        return 0
    if start_index > 0:
        logger.info("Resuming from query %s/%s (progress: %s)", start_index, len(queries), progress_path)
    queries = queries[start_index:]

    if args.accounts:
        accounts = [a.strip() for a in args.accounts.split(",") if a.strip()]
    else:
        accounts = get_account_ids_from_config()
    if not accounts:
        logger.error("No accounts configured for search.")
        return 3

    existing_keys = _load_existing_keys(output_path)
    logger.info("Loaded %s existing results. Output: %s", len(existing_keys), output_path)

    saved_total = 0
    per_account = max(1, int(args.queries_per_account))
    account_index = 0
    base_index = start_index
    for chunk in _chunks(queries, per_account):
        account_id = accounts[account_index % len(accounts)]
        account_index += 1
        logger.info("Using account %s for %s queries", account_id, len(chunk))
        saved = await _search_account(
            account_id=account_id,
            queries=chunk,
            output_path=output_path,
            existing_keys=existing_keys,
            limit=int(args.limit),
            per_query_sleep_min=float(args.sleep_min),
            per_query_sleep_max=float(args.sleep_max),
            max_attempts=int(args.attempts),
            backoff_base=float(args.backoff_base),
            backoff_factor=float(args.backoff_factor),
            backoff_cap=float(args.backoff_cap),
            base_index=base_index,
            total_queries=len(queries) + start_index,
            progress_path=progress_path,
        )
        saved_total += saved
        base_index += len(chunk)

    logger.info("Done. Saved %s new results to %s", saved_total, output_path)
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
