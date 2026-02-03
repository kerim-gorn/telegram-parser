"""
Domain-based routing for Telegram message notifications.

Routes messages with REQUEST intent to Telegram groups based on their classification domains.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.classification import DomainInfo, DomainType
from core.config import settings


class DomainRouterError(Exception):
    """Base exception for domain router errors."""
    pass


class DomainRouter:
    """
    Routes messages to Telegram groups based on their classification domains.
    
    Loads configuration from JSON file with domain-to-chat_id mapping.
    Supports two configuration formats:
    
    1. Simple value:
       "CONSTRUCTION_AND_REPAIR": null  # or chat_id or "muted"
    
    2. With subcategories and optional location overrides:
       "CONSTRUCTION_AND_REPAIR": {
         "default": null,  # chat_id for domain without subcategories or when subcategory not found
         "location_overrides": [
           {"city": "moscow", "district": "szao", "chat_id": -1001234567890},
           {"city": "dubai", "chat_id": -1001234567891}
         ],
         "subcategories": {
           "REPAIR_SERVICES": -1001234567890,
           "MAJOR_RENOVATION": {
             "default": -1001234567891,
             "location_overrides": [
               {"city": "moscow", "district": "szao", "chat_id": -1001234567892}
             ]
           },
           "SMALL_TOOLS_AND_MATERIALS": "muted"
         }
       }
    
    Uses fallback chat_id for domains without assigned groups.
    """
    
    def __init__(self, config_path: str | None = None) -> None:
        """
        Initialize domain router with configuration file.
        
        Args:
            config_path: Path to JSON configuration file. If None, uses settings.domain_routing_config_path.
        
        Raises:
            DomainRouterError: If configuration file is missing or invalid.
        """
        if config_path is None:
            config_path = settings.domain_routing_config_path
        
        self._config_path = Path(config_path)
        self._domains_map: dict[str, int | None | dict[str, Any]] = {}
        self._muted_subcategories: set[str] = set()
        self._fallback_chat_id: int | None = None
        
        self._load_config()
    
    def _load_config(self) -> None:
        """Load and validate configuration from JSON file."""
        if not self._config_path.exists():
            raise DomainRouterError(
                f"Domain routing configuration file not found: {self._config_path}"
            )
        
        try:
            data = json.loads(self._config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise DomainRouterError(
                f"Invalid JSON in domain routing configuration: {e}"
            ) from e
        except Exception as e:
            raise DomainRouterError(
                f"Failed to read domain routing configuration: {e}"
            ) from e
        
        if not isinstance(data, dict):
            raise DomainRouterError(
                "Domain routing configuration must be a JSON object"
            )
        
        # Load domains mapping
        domains_raw = data.get("domains")
        if not isinstance(domains_raw, dict):
            raise DomainRouterError(
                "Domain routing configuration must have 'domains' object"
            )
        
        self._domains_map = {}
        for domain_name, domain_config in domains_raw.items():
            if isinstance(domain_config, dict):
                # Format with subcategories: {"default": chat_id, "subcategories": {...}}
                parsed_config: dict[str, Any] = {}
                
                # Parse default chat_id
                default_value = domain_config.get("default")
                parsed_config["default"] = self._parse_chat_id_value(default_value)
                
                # Parse location overrides
                parsed_config["location_overrides"] = self._parse_location_overrides(
                    domain_config.get("location_overrides")
                )

                # Parse subcategories mapping
                subcategories_raw = domain_config.get("subcategories")
                if isinstance(subcategories_raw, dict):
                    parsed_subcategories: dict[str, Any] = {}
                    for subcat_name, subcat_chat_id in subcategories_raw.items():
                        if isinstance(subcat_chat_id, dict):
                            parsed_subcat: dict[str, Any] = {
                                "default": self._parse_chat_id_value(subcat_chat_id.get("default")),
                                "location_overrides": self._parse_location_overrides(
                                    subcat_chat_id.get("location_overrides")
                                ),
                            }
                            parsed_subcategories[str(subcat_name)] = parsed_subcat
                        else:
                            parsed_subcategories[str(subcat_name)] = self._parse_chat_id_value(subcat_chat_id)
                    parsed_config["subcategories"] = parsed_subcategories
                else:
                    parsed_config["subcategories"] = {}
                
                self._domains_map[domain_name] = parsed_config
            else:
                # Simple value format: number, null, or "muted"
                self._domains_map[domain_name] = self._parse_chat_id_value(domain_config)
        
        # Load and validate fallback (required)
        fallback_raw = data.get("fallback")
        if fallback_raw is None:
            raise DomainRouterError(
                "Domain routing configuration must have 'fallback' chat_id (required)"
            )
        
        try:
            self._fallback_chat_id = int(fallback_raw)
        except (ValueError, TypeError) as e:
            raise DomainRouterError(
                f"Invalid fallback chat_id in configuration: {fallback_raw}"
            ) from e
        
        # Load muted subcategories (optional)
        muted_subcategories_raw = data.get("muted_subcategories")
        if muted_subcategories_raw is not None:
            if isinstance(muted_subcategories_raw, list):
                self._muted_subcategories = {str(subcat) for subcat in muted_subcategories_raw}
            else:
                self._muted_subcategories = set()
        else:
            self._muted_subcategories = set()
    
    def _parse_chat_id_value(self, value: Any) -> int | str | None:
        """
        Parse chat_id value from config.
        
        Returns:
            int: Valid chat_id
            "muted": Domain/subcategory is muted
            None: Use fallback
        """
        if value == "muted" or value is False:
            return "muted"
        elif value is None:
            return None
        else:
            try:
                return int(value)
            except (ValueError, TypeError):
                return None

    def _normalize_location_value(self, value: Any) -> str | None:
        if value is None:
            return None
        s = str(value).strip().lower()
        return s if s else None

    def _normalize_locations(self, locations: Any) -> list[dict[str, str | None]]:
        if not isinstance(locations, list):
            return []
        out: list[dict[str, str | None]] = []
        for loc in locations:
            if not isinstance(loc, dict):
                continue
            city = self._normalize_location_value(loc.get("city"))
            district = self._normalize_location_value(loc.get("district"))
            if city is None and district is None:
                continue
            out.append({"city": city, "district": district})
        return out

    def _parse_location_overrides(self, overrides_raw: Any) -> list[dict[str, Any]]:
        if not isinstance(overrides_raw, list):
            return []
        parsed: list[dict[str, Any]] = []
        for entry in overrides_raw:
            if not isinstance(entry, dict):
                continue
            city = self._normalize_location_value(entry.get("city"))
            district = self._normalize_location_value(entry.get("district"))
            if city is None:
                continue
            parsed.append(
                {
                    "city": city,
                    "district": district,
                    "chat_id": self._parse_chat_id_value(entry.get("chat_id")),
                }
            )
        return parsed

    def _match_location_override(
        self,
        overrides: list[dict[str, Any]],
        locations: list[dict[str, str | None]],
    ) -> tuple[bool, int | None, bool]:
        if not overrides or not locations:
            return (False, None, False)

        # Prefer the most specific match: city + district
        for loc in locations:
            city = loc.get("city")
            district = loc.get("district")
            if not city or not district:
                continue
            for rule in overrides:
                if rule.get("city") == city and rule.get("district") == district:
                    resolved_chat_id, should_use_fallback = self._resolve_chat_id(rule.get("chat_id"))
                    return (True, resolved_chat_id, should_use_fallback)

        # Fallback to city-only match
        for loc in locations:
            city = loc.get("city")
            if not city:
                continue
            for rule in overrides:
                if rule.get("city") == city and not rule.get("district"):
                    resolved_chat_id, should_use_fallback = self._resolve_chat_id(rule.get("chat_id"))
                    return (True, resolved_chat_id, should_use_fallback)

        return (False, None, False)
    
    def _resolve_chat_id(self, chat_id_value: int | str | None) -> tuple[int | None, bool]:
        """
        Resolve chat_id value to actual chat_id.
        
        Returns:
            Tuple of (chat_id, should_use_fallback):
            - (int, False): Valid chat_id to use
            - (None, True): Should use fallback
            - (None, False): Muted - skip, don't use fallback
        """
        if chat_id_value == "muted":
            return (None, False)  # Muted - skip, don't use fallback
        elif isinstance(chat_id_value, int):
            return (chat_id_value, False)
        else:
            return (None, True)  # None - use fallback
    
    def get_chat_ids_for_domains(
        self,
        domains: list[DomainInfo],
        locations: list[dict[str, str | None]] | None = None,
    ) -> list[int]:
        """
        Get list of chat_ids for given domains.
        
        For each domain:
        - If domain config is an object with subcategories:
          * Check subcategories mapping first (if message has subcategories)
          * If subcategory found → use its chat_id (or "muted" to skip)
          * If subcategory not found or message has no subcategories → use "default"
          * If "default" is null → use fallback
        - If domain config is a simple value:
          * If domain is muted ("muted" or false in config) → skip it
          * If domain has assigned chat_id (not null) → use that chat_id
          * If domain has no assigned chat_id or is missing → use fallback
        - Global muted_subcategories list is also checked
        - If location overrides exist, match city+district first, then city-only
        
        If multiple domains map to the same chat_id, duplicates are preserved
        (message will be sent to the same group multiple times, which is acceptable).
        
        Args:
            domains: List of DomainInfo from message classification.
        
        Returns:
            List of chat_ids (integers) where message should be sent.
            Empty list if no domains provided or all domains are muted.
        """
        if not domains:
            return []
        
        chat_ids: list[int] = []
        normalized_locations = self._normalize_locations(locations)
        
        for domain_info in domains:
            domain_name: str | None = None
            subcategories: list[str] = []
            
            if isinstance(domain_info, DomainInfo):
                # Handle DomainInfo object
                domain_value = domain_info.domain
                if isinstance(domain_value, DomainType):
                    domain_name = domain_value.value
                else:
                    domain_name = str(domain_value)
                # Extract subcategories
                subcategories = domain_info.subcategories if hasattr(domain_info, 'subcategories') else []
            elif isinstance(domain_info, dict):
                # Handle dict format (from JSON/DB)
                domain_value = domain_info.get("domain")
                if domain_value is None:
                    # Use fallback for missing domain
                    if self._fallback_chat_id is not None:
                        chat_ids.append(self._fallback_chat_id)
                    continue
                # Extract domain name from dict
                if isinstance(domain_value, DomainType):
                    domain_name = domain_value.value
                else:
                    domain_name = str(domain_value)
                # Extract subcategories from dict
                subcategories = domain_info.get("subcategories", [])
                if not isinstance(subcategories, list):
                    subcategories = []
            else:
                # Use fallback for unknown format
                if self._fallback_chat_id is not None:
                    chat_ids.append(self._fallback_chat_id)
                continue
            
            if not domain_name:
                # Use fallback for empty domain name
                if self._fallback_chat_id is not None:
                    chat_ids.append(self._fallback_chat_id)
                continue
            
            # Get domain configuration
            domain_config = self._domains_map.get(domain_name)
            
            # Check global muted_subcategories first
            if subcategories:
                subcategory_strs = [str(subcat) for subcat in subcategories]
                if any(subcat in self._muted_subcategories for subcat in subcategory_strs):
                    continue
            
            # Handle domain config with subcategories
            if isinstance(domain_config, dict):
                # Check subcategories mapping if they exist
                subcategory_chat_id: int | str | None = None
                subcategory_is_muted = False
                subcategory_overrides: list[dict[str, Any]] = []
                if subcategories:
                    subcategories_config = domain_config.get("subcategories", {})
                    # Use first non-muted subcategory found
                    for subcat in subcategories:
                        subcat_str = str(subcat)
                        if subcat_str in subcategories_config:
                            candidate = subcategories_config[subcat_str]
                            if isinstance(candidate, dict):
                                subcategory_chat_id = candidate.get("default")
                                subcategory_overrides = candidate.get("location_overrides", []) or []
                            else:
                                subcategory_chat_id = candidate
                            if subcategory_chat_id == "muted":
                                subcategory_is_muted = True
                            break

                if subcategory_is_muted:
                    continue

                # Location overrides for subcategory (most specific)
                if subcategory_overrides:
                    matched, resolved_chat_id, should_use_fallback = self._match_location_override(
                        subcategory_overrides,
                        normalized_locations,
                    )
                    if matched:
                        if resolved_chat_id is not None:
                            chat_ids.append(resolved_chat_id)
                        elif should_use_fallback and self._fallback_chat_id is not None:
                            chat_ids.append(self._fallback_chat_id)
                        continue

                # Location overrides for domain (fallback)
                domain_overrides = domain_config.get("location_overrides", []) or []
                if domain_overrides:
                    matched, resolved_chat_id, should_use_fallback = self._match_location_override(
                        domain_overrides,
                        normalized_locations,
                    )
                    if matched:
                        if resolved_chat_id is not None:
                            chat_ids.append(resolved_chat_id)
                        elif should_use_fallback and self._fallback_chat_id is not None:
                            chat_ids.append(self._fallback_chat_id)
                        continue

                # Use subcategory chat_id if found, otherwise use default
                chat_id_to_use = subcategory_chat_id if subcategory_chat_id is not None else domain_config.get("default")
                resolved_chat_id, should_use_fallback = self._resolve_chat_id(chat_id_to_use)
                if resolved_chat_id is not None:
                    chat_ids.append(resolved_chat_id)
                elif should_use_fallback and self._fallback_chat_id is not None:
                    chat_ids.append(self._fallback_chat_id)
            else:
                # Simple value format
                resolved_chat_id, should_use_fallback = self._resolve_chat_id(domain_config)
                if resolved_chat_id is not None:
                    chat_ids.append(resolved_chat_id)
                elif should_use_fallback and self._fallback_chat_id is not None:
                    chat_ids.append(self._fallback_chat_id)
        
        return chat_ids
    
    def reload_config(self) -> None:
        """Reload configuration from file (useful for hot-reload scenarios)."""
        self._load_config()


# Global singleton instance
_router: DomainRouter | None = None


def get_domain_router() -> DomainRouter:
    """
    Get global DomainRouter instance (singleton).
    
    Returns:
        DomainRouter instance.
    """
    global _router
    if _router is None:
        _router = DomainRouter()
    return _router
