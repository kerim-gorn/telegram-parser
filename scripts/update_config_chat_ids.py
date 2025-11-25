#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import logging
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from dotenv import load_dotenv
from telethon.utils import get_peer_id

# Ensure project root on sys.path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import settings  # noqa: E402
from scripts.resolve_chat_id import _parse_numeric_chat_id, _extract_username  # noqa: E402
from core.session_manager import SessionManager  # noqa: E402
from core.telethon_client import create_client_from_session  # noqa: E402


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=4)
    path.write_text(text + "\n", encoding="utf-8")


def _get_first_account_key_from_config(cfg: Dict[str, Any]) -> Optional[str]:
    accounts = cfg.get("accounts") or []
    if not isinstance(accounts, list):
        return None
    for acc in accounts:
        if isinstance(acc, dict):
            # Prefer account_id because onboarding stores sessions under it
            acc_id = str(acc.get("account_id") or "").strip()
            if acc_id:
                return acc_id
            phone = str(acc.get("phone") or "").strip()
            if phone:
                return phone
    return None


def _interactive_select_account_key(cfg: Dict[str, Any]) -> Optional[str]:
    """
    Prompt user to select an account key (account_id preferred, fallback to phone)
    from the config file. Returns the selected key or None.
    """
    accounts = cfg.get("accounts") or []
    options: List[Dict[str, str]] = []
    if isinstance(accounts, list):
        for acc in accounts:
            if not isinstance(acc, dict):
                continue
            acc_id = str(acc.get("account_id") or "").strip()
            phone = str(acc.get("phone") or "").strip()
            key = acc_id or phone
            if not key:
                continue
            label = f"{acc_id or '-'} | {phone or '-'}"
            options.append({"key": key, "label": label})
    if options:
        print("Select account to use for resolving chat_id:")
        for i, opt in enumerate(options, start=1):
            print(f"  {i}) {opt['label']}")
        choice = input("Enter number or type account_id/phone (default 1): ").strip()
        if not choice:
            return options[0]["key"]
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(options):
                return options[idx - 1]["key"]
        # treat input as direct key
        return choice
    # No accounts section or empty; prompt direct
    typed = input("Enter account_id or phone to use for resolving: ").strip()
    return typed or None


def _build_arg_parser() -> ArgumentParser:
    p = ArgumentParser(description="Update null chat_id in realtime_config.json using Telegram resolver.")
    p.add_argument("--config", default=None, help="Path to realtime_config.json (default: settings.realtime_config_path)")
    p.add_argument(
        "--account-id",
        default=None,
        help="Account ID to use for resolving (matches onboarding key; overrides config/env)",
    )
    p.add_argument(
        "--phone",
        default=None,
        help="Account phone to use for resolving (if session stored under phone)",
    )
    p.add_argument("--all-accounts", action="store_true", help="Use all accounts from config for membership-based resolution")
    p.add_argument("--dry-run", action="store_true", help="Do not modify file; only print planned changes")
    p.add_argument("--delay-min", type=float, default=float(os.getenv("RESOLVE_DELAY_MIN", "8.0")), help="Min delay between network resolves")
    p.add_argument("--delay-max", type=float, default=float(os.getenv("RESOLVE_DELAY_MAX", "25.0")), help="Max delay between network resolves")
    p.add_argument("--limit", type=int, default=0, help="Resolve at most N missing chat_id entries (0 = no limit)")
    p.add_argument("--max-flood-wait-abort-seconds", type=int, default=int(os.getenv("MAX_FLOOD_WAIT_ABORT_SECONDS", "600")), help="Abort run if FloodWait seconds exceed this value")
    p.add_argument("--max-consecutive-fails", type=int, default=int(os.getenv("MAX_CONSECUTIVE_FAILS", "3")), help="Cooldown after this many consecutive failures")
    p.add_argument("--cooldown-after-fails", type=float, default=float(os.getenv("COOLDOWN_AFTER_FAILS", "900")), help="Cooldown seconds after hitting max consecutive failures")
    p.add_argument("--burst-every", type=int, default=int(os.getenv("BURST_EVERY", "10")), help="Extra sleep after every N attempts")
    p.add_argument("--burst-sleep", type=float, default=float(os.getenv("BURST_SLEEP", "60.0")), help="Extra sleep seconds after each burst")
    p.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"), choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Logging level")
    p.add_argument(
        "--progress-log",
        default=os.getenv("CHAT_ID_PROGRESS_LOG", "chat_id_progress.log"),
        help="Path to a text file where each successful resolution (identifier -> chat_id) is appended",
    )
    return p


def _normalize_username_token(identifier: str) -> Optional[str]:
    u = _extract_username(identifier or "")
    if not u:
        return None
    return f"@{u.lower()}"


async def _collect_membership_for_account(account_key: str, logger: logging.Logger) -> tuple[set[int], dict[str, int]]:
    ids: set[int] = set()
    uname_map: dict[str, int] = {}
    sm = SessionManager(
        redis_url=settings.redis_url,
        key_prefix=settings.telegram_session_prefix,
        encryption_key=settings.session_crypto_key,
    )
    try:
        string_session = await sm.get_string_session(account_key)
        if not string_session:
            logger.warning(f"[account] No session for '{account_key}'")
            return ids, uname_map
        client = create_client_from_session(string_session)
        async with client:
            async for d in client.iter_dialogs():
                try:
                    pid = int(get_peer_id(d.entity))
                    ids.add(pid)
                    uname = getattr(d.entity, "username", None)
                    if isinstance(uname, str) and uname:
                        uname_map[f"@{uname.lower()}"] = pid
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[dialogs] Skip entity for '{account_key}': {e}")
        return ids, uname_map
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[account] Failed to collect dialogs for '{account_key}': {e}")
        return ids, uname_map
    finally:
        try:
            await sm.close()
        except Exception:
            pass


def _safe_write_json(path: Path, data: dict[str, Any], logger: logging.Logger) -> None:
    try:
        tmp = path.with_suffix(".tmp.json")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
        tmp.replace(path)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to write realtime_config.json: {e}")


async def _update_missing_chat_ids(
    config_path: Path,
    account_keys: List[str],
    delay_min: float,
    delay_max: float,
    limit: int,
    dry_run: bool,
    max_flood_wait_abort_seconds: int,  # kept for interface
    max_consecutive_fails: int,
    cooldown_after_fails: float,
    burst_every: int,
    burst_sleep: float,
    logger: logging.Logger,
    progress_log_path: Optional[str],
) -> Tuple[int, int]:
    cfg = _read_json(config_path)
    chats = cfg.get("chats") or []
    if not isinstance(chats, list) or not chats:
        logger.info("No chats found in config.")
        return 0, 0

    # Normalize to object form for processing
    normalized: List[Dict[str, Any]] = []
    for item in chats:
        if isinstance(item, dict):
            obj = dict(item)
            # Ensure 'identifier' key if a legacy alias was used
            if "identifier" not in obj:
                for k in ("token", "username"):
                    if k in obj and isinstance(obj[k], str) and obj[k].strip():
                        obj["identifier"] = obj[k].strip()
                        break
            normalized.append(obj)
        else:
            # Legacy scalar -> wrap
            s = str(item).strip()
            if not s:
                continue
            try:
                normalized.append({"identifier": s, "chat_id": int(s)})
            except Exception:
                normalized.append({"identifier": s, "chat_id": None})

    # Build membership indices for all accounts (one connection per account)
    logger.info(f"Collecting dialogs for {len(account_keys)} accounts...")
    per_account_ids: Dict[str, set[int]] = {}
    per_account_usernames: Dict[str, Dict[str, int]] = {}
    for acc in account_keys:
        ids, unames = await _collect_membership_for_account(acc, logger)
        per_account_ids[acc] = ids
        per_account_usernames[acc] = unames
        # light pacing between accounts
        await asyncio.sleep(random.uniform(max(0.5, delay_min / 4.0), max(1.0, delay_max / 4.0)))

    # Aggregate for quick lookup
    id_to_accounts: Dict[int, List[str]] = {}
    username_to_accounts: Dict[str, List[Tuple[str, int]]] = {}
    for acc, ids in per_account_ids.items():
        for cid in ids:
            id_to_accounts.setdefault(int(cid), []).append(acc)
    for acc, umap in per_account_usernames.items():
        for uname, cid in umap.items():
            username_to_accounts.setdefault(uname, []).append((acc, int(cid)))

    total = len(normalized)
    missing = sum(1 for obj in normalized if obj.get("chat_id") is None)
    logger.info(f"Planned: total={total} missing={missing}")

    resolved = 0
    skipped = 0
    errors = 0
    attempts = 0

    progress_fp = None
    try:
        if progress_log_path:
            progress_fp = open(progress_log_path, "a", encoding="utf-8")
            logger.info(f"Progress log: appending to {progress_log_path}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not open progress log file '{progress_log_path}': {e}")
        progress_fp = None

    remaining = limit if limit and limit > 0 else None
    for obj in normalized:
        current = obj.get("chat_id")
        if current is not None:
            skipped += 1
            continue
        token = str(obj.get("identifier") or "").strip()
        if not token:
            skipped += 1
            continue

        chat_id: Optional[int] = None
        # numeric or t.me/c/<id> mapping
        numeric = _parse_numeric_chat_id(token)
        if numeric is not None:
            members = id_to_accounts.get(int(numeric), [])
            if members:
                chat_id = int(numeric)
            else:
                logging.info(f"[skip] Not a member of numeric chat {numeric} in any account; token='{token}'")

        # username mapping from dialogs
        if chat_id is None:
            uname = _normalize_username_token(token)
            if uname and uname in username_to_accounts:
                # pick first available mapping
                _, cid = username_to_accounts[uname][0]
                chat_id = int(cid)
            else:
                if uname:
                    logging.info(f"[skip] Username not found in dialogs: {uname}")
                else:
                    logging.info(f"[skip] Unsupported token format (no username, no numeric): '{token}'")

        if chat_id is not None:
            obj["chat_id"] = int(chat_id)
            resolved += 1
            attempts += 1
            if not dry_run:
                cfg["chats"] = normalized
                _safe_write_json(config_path, cfg, logger)
            if progress_fp is not None:
                ts = datetime.now().isoformat()
                accs = id_to_accounts.get(int(chat_id), [])
                progress_fp.write(f"{ts}\t{','.join(accs) or '-'}\t{token}\t{int(chat_id)}\n")
                progress_fp.flush()
        else:
            errors += 1
            attempts += 1

        # No per-item sleeping here because resolution uses only prebuilt dialog indices
        # and does not hit Telegram per item. We sleep only during per-account dialog collection above.

        if remaining is not None:
            remaining -= 1
            if remaining <= 0:
                break

    try:
        if progress_fp is not None:
            progress_fp.close()
    except Exception:
        pass

    # Final write (idempotent; most updates were in-place already)
    if not dry_run:
        cfg["chats"] = normalized
        _safe_write_json(config_path, cfg, logger)
        logger.info(f"Final write to {config_path}")
    else:
        logger.info("Dry-run: no changes written.")

    logger.info(f"Summary: resolved={resolved} skipped={skipped} errors={errors} attempts={attempts}")
    return resolved, errors


async def _amain() -> int:
    load_dotenv()
    parser = _build_arg_parser()
    args = parser.parse_args()

    # Logger setup
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger("update_config_chat_ids")

    cfg_path = Path(args.config) if args.config else Path(settings.realtime_config_path)
    cfg = _read_json(cfg_path)

    # Select account keys to use
    account_keys: List[str] = []
    if bool(args.all_accounts):
        acc_list = cfg.get("accounts") or []
        if not isinstance(acc_list, list) or not acc_list:
            logger.error("No accounts[] found in realtime_config.json for --all-accounts.")
            return 2
        for acc in acc_list:
            if not isinstance(acc, dict):
                continue
            key = (str(acc.get("account_id") or "") or str(acc.get("phone") or "")).strip()
            if key:
                account_keys.append(key)
        # dedupe preserving order
        seen: set[str] = set()
        account_keys = [k for k in account_keys if not (k in seen or seen.add(k))]
        if not account_keys:
            logger.error("No usable account keys discovered in accounts[].")
            return 2
        logger.info(f"Using all accounts: {len(account_keys)}")
    else:
        account_key = (args.account_id or args.phone or "").strip()
        if not account_key:
            pre = _get_first_account_key_from_config(cfg)
            if pre:
                print(f"Default account candidate: {pre}")
            account_key = _interactive_select_account_key(cfg) or pre or ""
        if not account_key:
            logger.error("Error: account not provided.")
            return 2
        account_keys = [account_key]

    try:
        await _update_missing_chat_ids(
            config_path=cfg_path,
            account_keys=account_keys,
            delay_min=float(args.delay_min),
            delay_max=float(args.delay_max),
            limit=int(args.limit or 0),
            dry_run=bool(args.dry_run),
            max_flood_wait_abort_seconds=int(args.max_flood_wait_abort_seconds),
            max_consecutive_fails=int(args.max_consecutive_fails),
            cooldown_after_fails=float(args.cooldown_after_fails),
            burst_every=int(args.burst_every),
            burst_sleep=float(args.burst_sleep),
            logger=logger,
            progress_log_path=str(getattr(args, "progress_log", "") or "chat_id_progress.log"),
        )
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed: {e}")
        return 1


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()


