#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from textwrap import dedent


def sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    cfg_path = root / "realtime_config.json"
    if not cfg_path.exists():
        raise SystemExit(f"Config file not found: {cfg_path}")

    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"Failed to read {cfg_path}: {e}")

    accounts = cfg.get("accounts") or []
    if not isinstance(accounts, list):
        raise SystemExit("Invalid realtime_config.json: 'accounts' must be a list")

    services_chunks: list[str] = []
    for acc in accounts:
        if not isinstance(acc, dict):
            continue
        account_id = str(acc.get("account_id") or acc.get("phone") or "").strip()
        if not account_id:
            continue
        safe = sanitize(account_id).lower()
        service_name = f"realtime_{safe}"
        container_name = f"telegram_parser_realtime_{safe}"
        chunk = (
            f"  {service_name}:\n"
            f"    build: .\n"
            f"    container_name: {container_name}\n"
            f"    restart: unless-stopped\n"
            f"    env_file: .env\n"
            f"    environment:\n"
            f"      TELEGRAM_ACCOUNT_ID: \"{account_id}\"\n"
            f"      CELERY_BROKER_URL: \"amqp://guest:guest@rabbitmq:5672/%2F\"\n"
            f"      REDIS_URL: \"redis://redis:6379/0\"\n"
            f"      DATABASE_URL: \"postgresql+asyncpg://${{POSTGRES_USER}}:${{POSTGRES_PASSWORD}}@postgres:5432/${{POSTGRES_DB}}\"\n"
            f"    depends_on:\n"
            f"      rabbitmq:\n"
            f"        condition: service_healthy\n"
            f"      redis:\n"
            f"        condition: service_healthy\n"
            f"    command: python -m workers.realtime_worker\n"
            f"    networks:\n"
            f"      - telegram_parser_net\n"
            f"    volumes:\n"
            f"      - ./realtime_config.json:/app/realtime_config.json:ro\n"
        )
        services_chunks.append(chunk)

    if not services_chunks:
        print("No accounts found in realtime_config.json; nothing to generate.")
        return

    content = (
        "services:\n"
        + "".join(services_chunks)
        + "\nnetworks:\n"
        + "  telegram_parser_net:\n"
        + "    external: true\n"
        + "    name: telegram_parser_telegram_parser_net\n"
    )
    out_path = root / "docker-compose.realtime.generated.yml"
    out_path.write_text(content, encoding="utf-8")
    print(f"Wrote {out_path}")
    print("Run:")
    print("  docker compose -f docker-compose.yml -f docker-compose.realtime.generated.yml up -d --remove-orphans")


if __name__ == "__main__":
    main()


