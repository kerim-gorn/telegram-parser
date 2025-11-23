import asyncio
from typing import Dict, List

from app.assignment import assign_channels_balanced, format_assignment_summary


def main() -> None:
    accounts: List[str] = ["+100000001", "+100000002", "+100000003"]
    channels = list(range(1, 21))
    eligible = {
        1: [accounts[0]],
        2: [accounts[0], accounts[1]],
        3: [accounts[1]],
        4: [accounts[1], accounts[2]],
        5: [accounts[2]],
        6: [accounts[0], accounts[2]],
        7: [accounts[0], accounts[1], accounts[2]],
        8: [accounts[0], accounts[1]],
        9: [accounts[1], accounts[2]],
        10: [accounts[0]],
        11: [accounts[0], accounts[1]],
        12: [accounts[0], accounts[2]],
        13: [accounts[1], accounts[2]],
        14: [accounts[0], accounts[1], accounts[2]],
        15: [accounts[2]],
        16: [accounts[0], accounts[1]],
        17: [accounts[1]],
        18: [accounts[0], accounts[2]],
        19: [accounts[1], accounts[2]],
        20: [accounts[0], accounts[1], accounts[2]],
    }
    weights: Dict[int, float] = {c: 1.0 for c in channels}
    capacities: Dict[str, float] = {a: 100.0 for a in accounts}

    new = assign_channels_balanced(channels, eligible, weights, accounts, capacities)
    prev = {a: set() for a in accounts}
    summary = format_assignment_summary(prev, new, weights, capacities, channels)
    print(summary)


if __name__ == "__main__":
    main()


