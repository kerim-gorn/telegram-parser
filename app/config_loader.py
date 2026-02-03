from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Union

from core.config import settings


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_realtime_config() -> Dict[str, Any]:
    """
    Loads realtime config JSON. Expected structure:
    {
      "accounts": [
        {"account_id": "+7999...", "phone": "+7999...", "twofa": null}
      ],
      "chats": [
        // New preferred schema (objects). chat_id takes precedence if provided.
        {"identifier": "@durov", "chat_id": -1001234567890},
        {"identifier": "t.me/c/123/45"},
        {"chat_id": -1009876543210}
      ]
    }
    Backward-compat: "chats" may still be a list of strings/ints.
    """
    path = Path(settings.realtime_config_path)
    data = _read_json(path)
    if isinstance(data, list):
        # Backward-compat: raw list treated as accounts
        return {"accounts": data, "chats": []}
    if not isinstance(data, dict):
        return {"accounts": [], "chats": []}
    accounts = data.get("accounts") or []
    chats = data.get("chats") or []
    # Normalize types
    if not isinstance(accounts, list):
        accounts = []
    if not isinstance(chats, list):
        chats = []
    return {"accounts": accounts, "chats": chats}


def get_account_ids_from_config() -> List[str]:
    cfg = load_realtime_config()
    out: List[str] = []
    for item in cfg.get("accounts", []):
        if isinstance(item, dict):
            acc_id = str(item.get("account_id") or item.get("phone") or "").strip()
            if acc_id:
                out.append(acc_id)
    # dedup preserve order
    seen: set[str] = set()
    return [a for a in out if not (a in seen or seen.add(a))]


def get_chats_from_config() -> List[Union[int, str]]:
    cfg = load_realtime_config()
    chats_raw = cfg.get("chats", [])
    out: List[Union[int, str]] = []
    for item in chats_raw:
        # Preferred: objects with chat_id (priority) and identifier fallback
        if isinstance(item, dict):
            chat_id_val = item.get("chat_id", None)
            if chat_id_val is not None:
                try:
                    out.append(int(chat_id_val))
                    continue
                except Exception:
                    # fall through to identifier when chat_id is malformed
                    pass
            # sensible name for legacy string token in objects
            identifier = item.get("identifier") or item.get("token") or item.get("username")
            if identifier is not None:
                s = str(identifier).strip()
                if s:
                    # tolerate numeric strings inside identifier
                    try:
                        out.append(int(s))
                    except Exception:
                        out.append(s)
                continue
            # If object has neither, skip silently
            continue
        # Backward-compat: list may contain strings/ints directly
        if isinstance(item, int):
            out.append(int(item))
        else:
            # tolerate numeric strings
            try:
                out.append(int(str(item).strip()))
            except Exception:
                s = str(item).strip()
                if s:
                    out.append(s)
    return out


def get_numeric_chat_ids_from_config() -> List[int]:
    """
    Return only numeric chat_id values from the realtime config.
    - For object entries, include item['chat_id'] if it is a valid int.
    - For scalar entries, include only values that can be parsed as int.
    - Ignore identifier-only entries (strings that are not numeric).
    Order is preserved and duplicates removed.
    """
    cfg = load_realtime_config()
    chats_raw = cfg.get("chats", [])
    out: List[int] = []
    seen: set[int] = set()
    for item in chats_raw:
        if isinstance(item, dict):
            if "chat_id" in item and item.get("chat_id") is not None:
                try:
                    cid = int(item.get("chat_id"))
                except Exception:
                    continue
                if cid not in seen:
                    seen.add(cid)
                    out.append(cid)
        else:
            try:
                cid = int(item)
            except Exception:
                continue
            if cid not in seen:
                seen.add(cid)
                out.append(cid)
    return out


def get_chat_locations_from_config() -> Dict[int, List[Dict[str, str | None]]]:
    """
    Build a lookup of chat_id -> list of location tags.
    Each location tag is a dict with optional "city" and "district" keys.
    """
    cfg = load_realtime_config()
    chats_raw = cfg.get("chats", [])
    out: Dict[int, List[Dict[str, str | None]]] = {}
    for item in chats_raw:
        if not isinstance(item, dict):
            continue
        locations_raw = item.get("locations")
        if not isinstance(locations_raw, list) or not locations_raw:
            continue
        chat_id_val = item.get("chat_id", None)
        if chat_id_val is None:
            continue
        try:
            chat_id = int(chat_id_val)
        except Exception:
            continue
        parsed_locations: List[Dict[str, str | None]] = []
        for loc in locations_raw:
            if not isinstance(loc, dict):
                continue
            city_val = loc.get("city")
            district_val = loc.get("district")
            city = str(city_val).strip() if city_val is not None else None
            district = str(district_val).strip() if district_val is not None else None
            if city == "":
                city = None
            if district == "":
                district = None
            if city is None and district is None:
                continue
            parsed_locations.append({"city": city, "district": district})
        if not parsed_locations:
            continue
        if chat_id not in out:
            out[chat_id] = parsed_locations
        else:
            out[chat_id].extend(parsed_locations)
    return out


