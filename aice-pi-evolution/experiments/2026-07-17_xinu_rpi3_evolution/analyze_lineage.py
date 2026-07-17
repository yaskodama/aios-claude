#!/usr/bin/env python3
"""Analyze a Xinu_RPi5_InternalEvolution lineage.json (8-axis genome, cell=smp_model).

Repairs transient None scores (from 503/timeout poisoning) to 0.0 before parsing,
then prints champion, top-N, per-generation best, per-smp_model best, and axis
frequency histograms — with smp_model (the round's focus) highlighted.

Usage: python3 analyze_lineage.py <lineage.json>
"""
import json, re, sys
from collections import defaultdict

AXES = ["scheduler", "memory_alloc", "ipc_primitive", "isolation",
        "arch_target", "power_mgmt", "concurrency_safety", "smp_model"]


def load_repaired(path):
    raw = open(path, encoding="utf-8").read()
    # Repair poisoned scores: "score":None0 / "score":None  ->  "score":0.0
    raw = re.sub(r'"score"\s*:\s*None\d*', '"score":0.0', raw)
    raw = raw.replace("None", "0.0")  # any stragglers
    return json.loads(raw)


def decode(genome):
    d = {}
    for pair in genome.split("|"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            d[k] = v
    return d


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "out/Xinu_RPi5_InternalEvolution.abcl_lineage.json"
    pop = load_repaired(path)
    for x in pop:
        x["_g"] = decode(x.get("genome", ""))
        x["score"] = float(x.get("score") or 0.0)

    gens = [x.get("generation", 0) for x in pop]
    print(f"=== lineage: {len(pop)} individuals, generations {min(gens)}..{max(gens)} ===\n")

    ranked = sorted(pop, key=lambda x: x["score"], reverse=True)
    champ = ranked[0]
    print("### CHAMPION")
    print(f"  id={champ['id']}  score={champ['score']:.4f}  "
          f"gen={champ.get('generation')}  cell={champ.get('cell')}  "
          f"op={champ.get('operator')}")
    for a in AXES:
        print(f"    {a:20s} = {champ['_g'].get(a, '?')}")
    print()

    print("### TOP 5")
    for x in ranked[:5]:
        g = x["_g"]
        print(f"  {x['score']:.4f}  smp={g.get('smp_model','?'):11s} "
              f"sched={g.get('scheduler','?'):14s} conc={g.get('concurrency_safety','?'):16s} "
              f"mem={g.get('memory_alloc','?'):12s} arch={g.get('arch_target','?')}")
    print()

    print("### BEST PER GENERATION")
    by_gen = defaultdict(list)
    for x in pop:
        by_gen[x.get("generation", 0)].append(x["score"])
    for gn in sorted(by_gen):
        s = by_gen[gn]
        print(f"  gen {gn:2d}: best={max(s):.4f}  mean={sum(s)/len(s):.4f}  n={len(s)}")
    print()

    print("### BEST PER smp_model  (the round's focus: full_smp vs worker_pool vs single_core)")
    by_smp = defaultdict(list)
    for x in pop:
        by_smp[x["_g"].get("smp_model", "?")].append(x)
    for smp in ["full_smp", "worker_pool", "single_core", "?"]:
        if smp in by_smp:
            best = max(by_smp[smp], key=lambda x: x["score"])
            print(f"  {smp:12s} best={best['score']:.4f}  (n={len(by_smp[smp])})  "
                  f"sched={best['_g'].get('scheduler')}  conc={best['_g'].get('concurrency_safety')}")
    print()

    print("### AXIS FREQUENCY (value: count)")
    for a in AXES:
        freq = defaultdict(int)
        for x in pop:
            freq[x["_g"].get(a, "?")] += 1
        items = sorted(freq.items(), key=lambda kv: -kv[1])
        marker = "  <<< FOCUS" if a == "smp_model" else ""
        print(f"  {a:20s} " + ", ".join(f"{v}:{c}" for v, c in items) + marker)


if __name__ == "__main__":
    main()
