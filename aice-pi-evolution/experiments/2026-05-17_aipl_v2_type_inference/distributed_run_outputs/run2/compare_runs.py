#!/usr/bin/env python3
"""Compare Run 1 vs Run 2 lineages for AIPL v2 Distributed evolution.

Same RNG seed (31415930) was used, but R6 hard floor was relaxed from
0.5 to 0.3 between runs, and R6 persona was softened.  This script
verifies:

  1. The two runs sampled the *same* genomes in the same order
     (RNG is deterministic) — so any score delta is purely from
     R6 persona / hard-floor changes.
  2. composite scores became non-zero in Run 2 (Run 1 zeroed them
     all via R6 < 0.5).
  3. Top elites by composite (Run 2) vs Run 1's top.

Usage: python3 compare_runs.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
R1 = HERE / "full_run" / "AIPL_v2_Distributed.lineage.json"
R2 = HERE / "run2" / "AIPL_v2_Distributed.lineage.json"


def load(p: Path) -> list[dict]:
    if not p.exists():
        print(f"[!] missing: {p}")
        sys.exit(1)
    with p.open() as f:
        return json.load(f)


def main():
    r1 = load(R1)
    r2 = load(R2)

    print(f"Run 1 individuals: {len(r1)}")
    print(f"Run 2 individuals: {len(r2)}")
    print()

    # 1. Genome identity check (same RNG -> same exploration).
    n = min(len(r1), len(r2))
    mismatched = []
    for i in range(n):
        if r1[i]["genome"] != r2[i]["genome"]:
            mismatched.append(i)
    print(f"Genome equality: {n - len(mismatched)}/{n} match")
    if mismatched:
        print(f"  first mismatch at index {mismatched[0]}")
    print()

    # 2. composite delta
    nonzero_r1 = sum(1 for ind in r1 if ind["composite"] > 0)
    nonzero_r2 = sum(1 for ind in r2 if ind["composite"] > 0)
    print(f"Non-zero composite count: Run 1 = {nonzero_r1}/{len(r1)}, "
          f"Run 2 = {nonzero_r2}/{len(r2)}")
    print()

    # 3. Top 5 by composite — Run 2
    top2 = sorted(r2, key=lambda x: -x["composite"])[:5]
    print("=== Run 2 top 5 by composite ===")
    for ind in top2:
        c = ind["composite"]
        print(f"  {ind['id']} (gen={ind['generation']}, "
              f"op={ind.get('operator','?')[:25]}) composite={c:.3f}")
    print()

    # 4. Top 5 by composite — Run 1 (for comparison)
    top1 = sorted(r1, key=lambda x: -x["composite"])[:5]
    print("=== Run 1 top 5 by composite ===")
    for ind in top1:
        c = ind["composite"]
        print(f"  {ind['id']} (gen={ind['generation']}, "
              f"op={ind.get('operator','?')[:25]}) composite={c:.3f}")
    print()

    # 5. Per-individual composite delta (matching index)
    print("=== Per-individual composite delta (Run 2 - Run 1) ===")
    deltas = []
    for i in range(n):
        d = r2[i]["composite"] - r1[i]["composite"]
        deltas.append((r1[i]["id"], d))
    deltas.sort(key=lambda x: -abs(x[1]))
    print("Top 10 biggest changes:")
    for iid, d in deltas[:10]:
        sign = "+" if d > 0 else ""
        print(f"  {iid}: {sign}{d:.3f}")
    print()
    avg_delta = sum(d for _, d in deltas) / len(deltas) if deltas else 0
    print(f"Average composite delta: {avg_delta:+.3f}")


if __name__ == "__main__":
    main()
