#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import pandas as pd


def main() -> None:
    input_path = Path("data/marked_kp.csv")
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    df = pd.read_csv(input_path)
    if "Статус канала" not in df.columns or "username" not in df.columns:
        raise SystemExit("Expected columns: 'Статус канала' and 'username'")

    status = pd.to_numeric(df["Статус канала"], errors="coerce")
    usernames = df.loc[status == 1, "username"].dropna().astype(str)

    for username in usernames:
        print(username)


if __name__ == "__main__":
    main()
