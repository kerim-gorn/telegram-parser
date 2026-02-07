import json
from argparse import ArgumentParser
from pathlib import Path

import pandas as pd


def _build_parser() -> ArgumentParser:
    p = ArgumentParser(description="Convert JSON list to CSV via pandas.")
    p.add_argument("input", help="Path to .json file with a list of objects")
    p.add_argument("--output", help="Path to output .csv file")
    return p


def main() -> None:
    args = _build_parser().parse_args()
    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    output_path = Path(args.output) if args.output else input_path.with_suffix(".csv")

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("Input JSON must be a list of objects")

    df = pd.DataFrame(payload)
    df.to_csv(output_path, index=False)
    print(f"Saved {len(df)} rows to {output_path}")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


def _load_json(path: Path) -> Any:
    if path.suffix.lower() == ".jsonl":
        return pd.read_json(path, lines=True)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _output_path(input_path: Path) -> Path:
    if input_path.suffix:
        return input_path.with_suffix(".csv")
    return input_path.with_name(f"{input_path.name}.csv")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert a JSON/JSONL file to CSV using pandas.",
    )
    parser.add_argument("input_path", type=Path, help="Path to .json/.jsonl file")
    args = parser.parse_args()

    input_path = args.input_path.expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    data = _load_json(input_path)
    if isinstance(data, pd.DataFrame):
        df = data
    else:
        df = pd.DataFrame(data)

    output_path = _output_path(input_path)
    df.to_csv(output_path, index=False)
    print(f"Saved CSV to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
