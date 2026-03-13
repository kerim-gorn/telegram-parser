from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.classification import DomainInfo, DomainType
from core.config import settings


@dataclass
class AutoReplyScenario:
    id: str
    enabled: bool
    domains: List[str]
    subcategories: List[str]
    telegram_account_id: str
    llm_model: Optional[str]
    prompt_key: str
    delay_seconds: int


@dataclass
class SelectedAutoReply:
    scenario_id: str
    telegram_account_id: str
    llm_model: Optional[str]
    prompt_template: str
    prompt_key: str
    delay_seconds: int


class AutoReplyRouterError(Exception):
    pass


class AutoReplyRouter:
    """
    Selects auto-reply scenario based on intents/domains and source message data.

    Config is loaded from JSON with ordered list of scenarios; first matching scenario wins.
    """

    def __init__(self, config_path: Optional[str] = None, prompts_path: Optional[str] = None) -> None:
        if config_path is None:
            config_path = settings.auto_reply_config_path
        if prompts_path is None:
            prompts_path = settings.auto_reply_prompts_path

        self._config_path = Path(config_path)
        self._prompts_path = Path(prompts_path)

        self._enabled: bool = False
        self._default_model: Optional[str] = None
        self._scenarios: List[AutoReplyScenario] = []
        self._prompts: Dict[str, str] = {}

        self._load_config()
        self._load_prompts()

    def _load_config(self) -> None:
        if not self._config_path.exists():
            # Fail soft: no config -> feature disabled
            self._enabled = False
            self._scenarios = []
            return

        try:
            data = json.loads(self._config_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise AutoReplyRouterError(f"Failed to read auto-reply config: {e}") from e

        if not isinstance(data, dict):
            raise AutoReplyRouterError("Auto-reply config must be a JSON object")

        self._enabled = bool(data.get("enabled", True)) and bool(settings.auto_reply_enabled)
        default_model = data.get("default_model")
        self._default_model = str(default_model).strip() or None if default_model is not None else None

        raw_scenarios = data.get("scenarios") or []
        scenarios: List[AutoReplyScenario] = []
        if isinstance(raw_scenarios, list):
            for item in raw_scenarios:
                if not isinstance(item, dict):
                    continue
                scenario_id = str(item.get("id") or "").strip()
                if not scenario_id:
                    continue
                enabled = bool(item.get("enabled", True))
                match_cfg = item.get("match") or {}
                if not isinstance(match_cfg, dict):
                    match_cfg = {}
                domains_raw = match_cfg.get("domains") or []
                subcats_raw = match_cfg.get("subcategories") or []
                domains = [str(d).strip() for d in domains_raw if str(d).strip()]
                subcategories = [str(s).strip() for s in subcats_raw if str(s).strip()]
                if not domains:
                    # Domain-less scenarios are ignored for now
                    continue
                telegram_account_id = str(item.get("telegram_account_id") or "").strip()
                if not telegram_account_id:
                    continue
                llm_model_raw = item.get("llm_model")
                llm_model = str(llm_model_raw).strip() or None if llm_model_raw is not None else None
                prompt_key = str(item.get("prompt_key") or "").strip()
                if not prompt_key:
                    continue
                delay_seconds = int(item.get("delay_seconds") or 0)
                scenarios.append(
                    AutoReplyScenario(
                        id=scenario_id,
                        enabled=enabled,
                        domains=domains,
                        subcategories=subcategories,
                        telegram_account_id=telegram_account_id,
                        llm_model=llm_model,
                        prompt_key=prompt_key,
                        delay_seconds=delay_seconds,
                    )
                )
        self._scenarios = scenarios

    def _load_prompts(self) -> None:
        if not self._prompts_path.exists():
            self._prompts = {}
            return
        try:
            data = json.loads(self._prompts_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise AutoReplyRouterError(f"Failed to read auto-reply prompts: {e}") from e
        if not isinstance(data, dict):
            raise AutoReplyRouterError("Auto-reply prompts file must be a JSON object")
        # Ignore _doc key if present
        self._prompts = {k: str(v) for k, v in data.items() if k != "_doc"}

    def reload(self) -> None:
        """Reload config and prompts from disk."""
        self._load_config()
        self._load_prompts()

    def _normalize_domains(self, domains_raw: Any) -> List[DomainInfo]:
        out: List[DomainInfo] = []
        if not isinstance(domains_raw, list):
            return out
        for item in domains_raw:
            if isinstance(item, DomainInfo):
                out.append(item)
            elif isinstance(item, dict):
                try:
                    out.append(DomainInfo(**item))
                except Exception:
                    continue
        return out

    def select_scenario(
        self,
        intents: Any,
        domains_raw: Any,
        msg_data: Dict[str, Any],
    ) -> Optional[SelectedAutoReply]:
        """
        Select first matching auto-reply scenario or return None.
        """
        if not self._enabled:
            return None

        # Require sender id and non-empty text
        sender_id = msg_data.get("sender_id")
        text = msg_data.get("text") or ""
        if sender_id is None:
            return None
        if not isinstance(text, str) or not text.strip():
            return None

        # Enforce minimal length at global level: if text is too short for all scenarios, we still check per scenario
        domains = self._normalize_domains(domains_raw)
        if not domains:
            return None

        # We do not re-check intents here; caller is expected to pass only REQUEST-like candidates.

        # Collect all domain/subcategory pairs from classification
        classified_pairs: List[tuple[str, Optional[str]]] = []
        for d in domains:
            domain_name: str
            if isinstance(d.domain, DomainType):
                domain_name = d.domain.value
            else:
                domain_name = str(d.domain)
            if not domain_name:
                continue
            if getattr(d, "subcategories", None):
                for sub in d.subcategories:
                    classified_pairs.append((domain_name, str(sub)))
            else:
                classified_pairs.append((domain_name, None))

        if not classified_pairs:
            return None

        # First matching scenario wins
        for scenario in self._scenarios:
            if not scenario.enabled:
                continue

            # Determine if any (domain, subcat) pair matches scenario filters
            for domain_name, subcat in classified_pairs:
                if domain_name not in scenario.domains:
                    continue
                if scenario.subcategories:
                    if subcat is None:
                        continue
                    if subcat not in scenario.subcategories:
                        continue
                # Match found
                prompt_template = self._prompts.get(scenario.prompt_key)
                if not prompt_template:
                    # Scenario without prompt is effectively disabled
                    break
                model_name = scenario.llm_model or self._default_model
                return SelectedAutoReply(
                    scenario_id=scenario.id,
                    telegram_account_id=scenario.telegram_account_id,
                    llm_model=model_name,
                    prompt_template=prompt_template,
                    prompt_key=scenario.prompt_key,
                    delay_seconds=scenario.delay_seconds,
                )

        return None


_auto_reply_router: Optional[AutoReplyRouter] = None


def get_auto_reply_router() -> AutoReplyRouter:
    global _auto_reply_router
    if _auto_reply_router is None:
        _auto_reply_router = AutoReplyRouter()
    return _auto_reply_router

