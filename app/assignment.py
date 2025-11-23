from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple


Assignment = Dict[str, Set[int]]


def assign_channels_balanced(
    channels: List[int],
    eligible: Dict[int, List[str]],
    channel_weight: Dict[int, float],
    accounts: List[str],
    account_capacity: Dict[str, float],
) -> Assignment:
    """
    Greedy balanced maximum coverage:
      - rarest-first by number of eligible accounts, then heavier channels first
      - choose least-loaded account (by current total weight), tie-broken by residual flexibility
    """
    load: Dict[str, float] = {a: 0.0 for a in accounts}
    assigned: Assignment = {a: set() for a in accounts}

    def eligible_count(c: int) -> int:
        return len(eligible.get(c, []))

    def weight(c: int) -> float:
        return float(channel_weight.get(c, 1.0))

    # only channels that have at least one eligible account
    pool = [c for c in channels if eligible.get(c)]
    channels_sorted = sorted(pool, key=lambda c: (eligible_count(c), -weight(c)))

    # Pre-compute residual flexibility counts lazily per account as we go
    # We recompute on demand using remaining channels for simplicity; fast enough for ~1e3 scale
    def residual_flex(a: str) -> int:
        return sum(1 for cc in channels_sorted if cc not in assigned[a] and a in eligible.get(cc, []))

    for c in channels_sorted:
        w = weight(c)
        candidates = [a for a in eligible[c] if load[a] + w <= account_capacity.get(a, float("inf"))]
        if not candidates:
            continue
        chosen = min(candidates, key=lambda a: (load[a], residual_flex(a)))
        assigned[chosen].add(c)
        load[chosen] += w

    return assigned


def diff_assignments(prev: Assignment, new: Assignment) -> Tuple[Assignment, Assignment]:
    """
    Returns (adds, removes), where for each account_id:
      - adds[account] = channels present in new but not in prev
      - removes[account] = channels present in prev but not in new
    """
    accounts: Set[str] = set(prev.keys()) | set(new.keys())
    adds: Assignment = {}
    removes: Assignment = {}
    for a in accounts:
        p = prev.get(a, set())
        n = new.get(a, set())
        adds[a] = n - p
        removes[a] = p - n
    return adds, removes


def compute_loads(assignment: Assignment, weights: Dict[int, float]) -> Dict[str, float]:
    return {a: sum(float(weights.get(c, 1.0)) for c in chans) for a, chans in assignment.items()}


def format_assignment_summary(
    prev: Assignment,
    new: Assignment,
    weights: Dict[int, float],
    capacities: Dict[str, float],
    target_channels: Iterable[int],
) -> str:
    """
    Produce a compact, human-readable multi-line summary of redistribution.
    """
    target_set = set(int(x) for x in target_channels)
    prev_union = set().union(*(prev.values() or [set()])) if prev else set()
    new_union = set().union(*(new.values() or [set()])) if new else set()

    adds, removes = diff_assignments(prev, new)
    added_total = sum(len(v) for v in adds.values())
    removed_total = sum(len(v) for v in removes.values())

    prev_loads = compute_loads(prev, weights) if prev else {}
    new_loads = compute_loads(new, weights)

    def summarize_loads(loads: Dict[str, float]) -> Tuple[float, float, float]:
        if not loads:
            return 0.0, 0.0, 0.0
        values = list(loads.values())
        return min(values), max(values), (sum(values) / len(values)) if values else 0.0

    min_prev, max_prev, avg_prev = summarize_loads(prev_loads)
    min_new, max_new, avg_new = summarize_loads(new_loads)
    imbalance_prev = max_prev - min_prev
    imbalance_new = max_new - min_new

    covered_prev = len(prev_union & target_set)
    covered_new = len(new_union & target_set)
    coverage_total = len(target_set)
    coverage_prev_pct = (covered_prev / coverage_total * 100.0) if coverage_total else 0.0
    coverage_new_pct = (covered_new / coverage_total * 100.0) if coverage_total else 0.0

    lines: List[str] = []
    lines.append("[Assign] Realtime redistribution summary")
    lines.append(
        f"- coverage: {covered_prev}->{covered_new} of {coverage_total} "
        f"({coverage_prev_pct:.1f}% -> {coverage_new_pct:.1f}%, Δ {coverage_new_pct-coverage_prev_pct:+.1f} pp)"
    )
    lines.append(
        f"- changes: +{added_total} assigned, -{removed_total} removed "
        f"(net {added_total-removed_total:+d})"
    )
    lines.append(
        f"- load imbalance: {imbalance_prev:.2f} -> {imbalance_new:.2f} "
        f"(avg {avg_prev:.2f} -> {avg_new:.2f})"
    )
    # Per-account compact summary
    lines.append("- per-account:")
    for a in sorted(new.keys()):
        cap = capacities.get(a, float("inf"))
        new_count = len(new.get(a, set()))
        new_load = new_loads.get(a, 0.0)
        used_pct = (new_load / cap * 100.0) if cap and cap != float("inf") else 0.0
        add_n = len(adds.get(a, set()))
        rem_n = len(removes.get(a, set()))
        lines.append(
            f"  • {a}: channels={new_count}, load={new_load:.2f}"
            + (f"/{cap:.2f} ({used_pct:.0f}%)" if cap != float('inf') else "")
            + f", Δ +{add_n}/-{rem_n}"
        )

    # Optionally, list a short sample of added/removed channels for observability
    sample_limit = 5
    for a in sorted(new.keys()):
        add_sample = sorted(list(adds.get(a, set())))[:sample_limit]
        rem_sample = sorted(list(removes.get(a, set())))[:sample_limit]
        if add_sample or rem_sample:
            lines.append(
                f"  ◦ {a} samples: add={add_sample or []}, remove={rem_sample or []}"
            )

    return "\n".join(lines)


