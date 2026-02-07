#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _iter_chats(payload: Any) -> Iterable[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise SystemExit("Config root must be a JSON object")
    chats = payload.get("chats")
    if not isinstance(chats, list):
        raise SystemExit("Config must contain 'chats' list")
    for item in chats:
        if isinstance(item, dict):
            yield item


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, dict, str)):
        return bool(value)
    return True


def _chat_priority(chat: dict[str, Any]) -> tuple[int, int]:
    has_chat_id = _has_value(chat.get("chat_id"))
    has_locations = _has_value(chat.get("locations"))
    return (1 if has_chat_id else 0, 1 if has_locations else 0)


def _print_removed(identifier: str, chat: dict[str, Any]) -> None:
    print(f"Removing duplicate identifier: {identifier}")
    print(json.dumps(chat, ensure_ascii=False, indent=4))


def main() -> None:
    input_path = Path("realtime_config.json")
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    data = _load_json(input_path)
    chats_list = list(_iter_chats(data))

    by_identifier: dict[str, list[int]] = defaultdict(list)
    for idx, chat in enumerate(chats_list):
        identifier = chat.get("identifier")
        if isinstance(identifier, str) and identifier:
            by_identifier[identifier].append(idx)

    duplicate_groups = {key: idxs for key, idxs in by_identifier.items() if len(idxs) > 1}
    if not duplicate_groups:
        print("No duplicate identifiers found.")
        return

    keep_indices: set[int] = set()
    removed_count = 0
    for identifier, indices in duplicate_groups.items():
        candidates = [(idx, _chat_priority(chats_list[idx])) for idx in indices]
        candidates.sort(key=lambda item: item[1], reverse=True)
        keep_idx = candidates[0][0]
        keep_indices.add(keep_idx)
        for idx in indices:
            if idx != keep_idx:
                _print_removed(identifier, chats_list[idx])
                removed_count += 1

    filtered_chats = []
    for idx, chat in enumerate(chats_list):
        identifier = chat.get("identifier")
        if identifier in duplicate_groups:
            if idx in keep_indices:
                filtered_chats.append(chat)
            continue
        filtered_chats.append(chat)

    data["chats"] = filtered_chats
    input_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )
    print(f"Removed {removed_count} duplicate chat entries.")


if __name__ == "__main__":
    main()
