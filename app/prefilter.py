from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Literal

from core.config import settings


Action = Literal["skip", "force"]
Decision = Literal["skip", "force", None]


class Prefilter:
    def __init__(self, config_path: Optional[str], reload_seconds: int) -> None:
        self._config_path: Optional[str] = config_path
        self._reload_seconds: int = max(1, int(reload_seconds))
        self._lock = asyncio.Lock()
        self._last_check_ts: float = 0.0
        self._last_mtime: Optional[float] = None
        self._enabled: bool = bool(config_path)
        self._substring_rules: list[dict[str, Any]] = []
        self._regex_rules: list[dict[str, Any]] = []

    async def match(self, text: str) -> Tuple[Decision, List[str]]:
        if not isinstance(text, str) or not text:
            return None, []
        await self._maybe_reload()
        if not self._enabled:
            return None, []

        matched: list[str] = []
        force = False
        skip = False

        # Substring rules
        if self._substring_rules:
            text_for_ci = text.lower()
            for rule in self._substring_rules:
                pat: str = rule["pattern"]
                ignore_case: bool = bool(rule.get("ignore_case", True))
                action: Action = rule["action"]
                if ignore_case:
                    if pat.lower() in text_for_ci:
                        matched.append(pat)
                        if action == "force":
                            force = True
                        elif action == "skip":
                            skip = True
                else:
                    if pat in text:
                        matched.append(pat)
                        if action == "force":
                            force = True
                        elif action == "skip":
                            skip = True

        # Regex rules
        for rule in self._regex_rules:
            rgx: re.Pattern[str] = rule["compiled"]
            if rgx.search(text) is not None:
                matched.append(rule["pattern"])
                action: Action = rule["action"]
                if action == "force":
                    force = True
                elif action == "skip":
                    skip = True

        if not matched:
            return None, []

        # De-duplicate while preserving order
        seen: set[str] = set()
        deduped = []
        for m in matched:
            if m not in seen:
                seen.add(m)
                deduped.append(m)

        if force:
            return "force", deduped
        if skip:
            return "skip", deduped
        return None, deduped

    async def _maybe_reload(self) -> None:
        """
        Hot-reload rules if interval elapsed and file mtime changed.
        """
        if self._config_path is None:
            self._enabled = False
            return
        now = asyncio.get_running_loop().time()
        if (now - self._last_check_ts) < self._reload_seconds:
            return
        self._last_check_ts = now
        async with self._lock:
            await self._reload_locked()

    async def _reload_locked(self) -> None:
        path = self._config_path
        if not path:
            self._enabled = False
            self._substring_rules = []
            self._regex_rules = []
            return
        try:
            stat = await asyncio.to_thread(os.stat, path)
        except FileNotFoundError:
            self._enabled = False
            self._substring_rules = []
            self._regex_rules = []
            self._last_mtime = None
            return
        except Exception:
            # Keep previous state on unexpected errors
            return

        mtime = float(stat.st_mtime)
        if self._last_mtime is not None and mtime == self._last_mtime:
            return

        try:
            raw = await asyncio.to_thread(self._read_file, path)
            data: Dict[str, Any] = json.loads(raw)
            substrings_in = data.get("substrings") or []
            regexes_in = data.get("regexes") or []
            substring_rules = self._build_substring_rules(substrings_in)
            regex_rules = self._build_regex_rules(regexes_in)
        except Exception:
            # Do not flip off existing valid rules on parse errors
            return

        self._substring_rules = substring_rules
        self._regex_rules = regex_rules
        self._last_mtime = mtime
        self._enabled = bool(self._substring_rules or self._regex_rules)

    @staticmethod
    def _read_file(path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _build_substring_rules(items: list[Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not isinstance(items, list):
            return out
        for item in items:
            if not isinstance(item, dict):
                continue
            pat = item.get("pattern")
            action = item.get("action")
            if not isinstance(pat, str) or not pat:
                continue
            if action not in ("skip", "force"):
                continue
            ignore_case = bool(item.get("ignore_case", True))
            rule: dict[str, Any] = {
                "pattern": pat,
                "ignore_case": ignore_case,
                "action": action,
            }
            out.append(rule)
        return out

    @staticmethod
    def _build_regex_rules(items: list[Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not isinstance(items, list):
            return out
        for item in items:
            if not isinstance(item, dict):
                continue
            pat = item.get("pattern")
            action = item.get("action")
            if not isinstance(pat, str) or not pat:
                continue
            if action not in ("skip", "force"):
                continue
            flags = 0
            if bool(item.get("ignore_case", False)):
                flags |= re.IGNORECASE
            try:
                compiled = re.compile(pat, flags=flags)
            except re.error:
                continue
            rule: dict[str, Any] = {
                "pattern": pat,
                "compiled": compiled,
                "action": action,
            }
            out.append(rule)
        return out


_prefilter: Optional[Prefilter] = None
_prefilter_lock = asyncio.Lock()


def get_prefilter() -> Prefilter:
    """
    Return a process-wide singleton prefilter instance.
    """
    global _prefilter
    if _prefilter is None:
        _prefilter = Prefilter(
            config_path=settings.prefilter_config_json,
            reload_seconds=settings.prefilter_reload_seconds,
        )
    return _prefilter


