import json
from argparse import ArgumentParser
from pathlib import Path


def _build_parser() -> ArgumentParser:
    p = ArgumentParser(description="Filter jsonl results to groups only.")
    p.add_argument("input", help="Path to .jsonl file with results")
    p.add_argument("--output", help="Path to output .json file")
    return p


def main() -> None:
    args = _build_parser().parse_args()
    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    output_path = Path(args.output) if args.output else input_path.with_suffix(".groups.json")

    groups: list[dict] = []
    for line in input_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if item.get("entity_type") == "group":
            groups.append(item)

    output_path.write_text(json.dumps(groups, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {len(groups)} groups to {output_path}")


if __name__ == "__main__":
    main()
