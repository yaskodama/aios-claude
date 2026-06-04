#!/usr/bin/env python3
"""Analyze the MANET drone routing MAP-Elites lineage.

Reads out/AIPL_DroneMANET_Round1.{lineage,elite_map,ranking}.json and reports:
  - per-protocol champion (full 7-axis genome + per-task scores)
  - task-dimension leaders (best genome for each evaluation scenario)
  - the reactive_AODV baseline (explicit seed) vs its evolved champion: axis diffs
  - scenario rankings (conservative / innovative / general_purpose)
Pure stdlib; reads JSON only.
"""
import json
from pathlib import Path

OUT = Path(__file__).parent / "out"
NAME = "AIPL_DroneMANET_Round1"
AXES = ["routing_protocol", "buffering_strategy", "link_metric", "topology_control",
        "mobility_handling", "neighbor_discovery", "qos_priority"]
TASKS = ["PartitionTolerance", "HighMobilityResilience", "SwarmScalability",
         "EmbeddedFeasibility", "SOSLatency", "EnergyEfficiency", "AODVCompatibility"]

pop = json.loads((OUT / f"{NAME}.lineage.json").read_text())
by_id = {i["id"]: i for i in pop}


def tasks_of(ind):
    c = ind.get("fitness_components", {})
    return {t: round(c.get(f"task::{t}", 0.0), 2) for t in TASKS}


def genome_line(g):
    return " ".join(f"{a.split('_')[0]}={g[a]}" for a in AXES)


print("=" * 78)
print(f"  MANET Drone Routing — Round 1  ({len(pop)} individuals)")
print("=" * 78)

# per-protocol champions
proto_best = {}
for ind in pop:
    p = ind["genome"]["routing_protocol"]
    if p not in proto_best or ind["composite"] > proto_best[p]["composite"]:
        proto_best[p] = ind

print("\n## Per-protocol champions (composite desc)\n")
for ind in sorted(proto_best.values(), key=lambda i: -i["composite"]):
    g = ind["genome"]
    print(f"[{ind['composite']:.3f}] {g['routing_protocol']:18s} id={ind['id']} gen={ind['generation']}")
    print(f"        {genome_line(g)}")
    ts = tasks_of(ind)
    print("        " + "  ".join(f"{t[:5]}={ts[t]}" for t in TASKS))

# task-dimension leaders
print("\n## Task-dimension leaders (who is best at each scenario)\n")
for t in TASKS:
    key = f"task::{t}"
    best = max(pop, key=lambda i: i.get("fitness_components", {}).get(key, 0.0))
    sc = best.get("fitness_components", {}).get(key, 0.0)
    print(f"  {t:24s} {sc:.2f}  {best['genome']['routing_protocol']:18s} (id={best['id']})")

# reactive_AODV baseline (gen0 explicit seed) vs evolved AODV champion
seed_aodv = next((i for i in pop if i["genome"]["routing_protocol"] == "reactive_AODV"
                  and i["generation"] == 0 and i.get("operator", "").startswith("seed:explicit")), None)
champ_aodv = proto_best.get("reactive_AODV")
if seed_aodv and champ_aodv:
    print("\n## Baseline (current drone-hil) vs evolved reactive_AODV\n")
    print(f"  baseline  [{seed_aodv['composite']:.3f}] {genome_line(seed_aodv['genome'])}")
    print(f"  evolved   [{champ_aodv['composite']:.3f}] {genome_line(champ_aodv['genome'])}")
    diffs = [(a, seed_aodv['genome'][a], champ_aodv['genome'][a])
             for a in AXES if seed_aodv['genome'][a] != champ_aodv['genome'][a]]
    if diffs:
        print("  changed axes:")
        for a, o, n in diffs:
            print(f"    {a:20s} {o}  ->  {n}")
    else:
        print("  (no axis changed — baseline already cell champion)")
    sb, cb = tasks_of(seed_aodv), tasks_of(champ_aodv)
    print("  per-task delta:")
    for t in TASKS:
        d = cb[t] - sb[t]
        mark = "+" if d > 0 else ""
        print(f"    {t:24s} {sb[t]:.2f} -> {cb[t]:.2f}  ({mark}{d:.2f})")

# scenario rankings
rk = json.loads((OUT / f"{NAME}.ranking.json").read_text())
print("\n## Scenario rankings (meta-fitness: trend/novelty/generality/...)\n")
scenarios = rk if isinstance(rk, list) else rk.get("scenarios", rk.get("rankings", []))
for r in (scenarios if isinstance(scenarios, list) else []):
    name = r.get("scenario", "?")
    entries = r.get("entries", [])
    print(f"  {name}:")
    for e in entries[:3]:
        iid = e.get("individual_id")
        g = by_id.get(iid, {}).get("genome", {})
        proto = g.get("routing_protocol", "?")
        print(f"    #{e.get('pareto_rank','?')} id={iid} {proto:18s} composite={e.get('composite',0):.3f}")
