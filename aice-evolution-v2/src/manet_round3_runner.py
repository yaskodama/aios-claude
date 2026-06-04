"""MANET drone routing MAP-Elites — Round 3 (resource/congestion awareness).

Round 2's open-axes search surfaced two design dimensions the curated schema
was missing: resource_awareness and congestion_awareness. Round 3 promotes
them to first-class axes (schemas/manet_routing_r3.schema.json) and re-searches
with the current designs seeded as "unaware" (both = none), so the GA shows
whether folding remaining battery/buffer/CPU and congestion into the routing
decision actually pays off (esp. for hybrid_ZRP).

Run from the project root:
  AIPL_AI_PROVIDER=gemini AIPL_GEMINI_MODEL=gemini-2.5-flash-lite \
  python3 -m aice-evolution-v2.src.manet_round3_runner
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .schema import GeneSchema
from .map_elites import run, dump_run
from .ai_evaluator import evaluate_ai, composite_fitness_ai
from .operators import set_proposer_mode
from .analysis import extract_trend, find_gaps, compute_meta_fitness
from .ranking import rank_all
from .reporter import write_report

EXP = Path("aice-pi-evolution/experiments/2026-06-04_manet_drone_evolution")
OUT = EXP / "out"
GA = OUT / "AIPL_DroneMANET_Round1.ga.json"          # reuse task / reviewers / ranking
SCHEMA = Path("aice-evolution-v2/schemas/manet_routing_r3.schema.json")
R1 = OUT / "AIPL_DroneMANET_Round1.lineage.json"
R2 = OUT / "AIPL_DroneMANET_Round2.lineage.json"

R3_AXES = ("resource_awareness", "congestion_awareness")


def champions(lineage_path):
    pop = json.loads(lineage_path.read_text(encoding="utf-8"))
    best = {}
    for ind in pop:
        p = ind["genome"]["routing_protocol"]
        if p not in best or ind["composite"] > best[p]["composite"]:
            best[p] = ind
    return best


def seeds_unaware():
    """Per-protocol champions (R1 curated + R2 bundle_forwarding), with the two
    new axes pinned to 'none' so evolution must *discover* that awareness helps."""
    best = champions(R1)
    bf = champions(R2).get("bundle_forwarding")
    if bf:
        best["bundle_forwarding"] = bf
    seeds = []
    for ind in best.values():
        # drop any stray/None-valued keys from R2's discovered axes, pin the two
        # new axes to the unaware baseline so evolution must discover their value
        g = {k: v for k, v in ind["genome"].items() if v is not None}
        g["resource_awareness"] = "none"
        g["congestion_awareness"] = "none"
        # minimal coherence repair (pure flooding must be congestion-aware;
        # heavy replication must be resource-aware) — keep the rest unaware
        if g.get("routing_protocol") == "gossip_flood":
            g["congestion_awareness"] = "queue_backpressure"
        if g.get("buffering_strategy") == "replicate_n_copies":
            g["resource_awareness"] = "battery_aware"
        seeds.append(g)
    return seeds


def main() -> int:
    spec = json.loads(GA.read_text(encoding="utf-8"))
    spec["name"] = "AIPL_DroneMANET_Round3"
    schema = GeneSchema.load(SCHEMA)

    spec["search"]["open_axes"] = False
    spec["search"]["seed_genomes"] = seeds_unaware()
    spec["search"]["seed_count"] = 4
    spec["search"]["generations"] = 32

    # validate seeds
    for s in spec["search"]["seed_genomes"]:
        v = schema.coherence_violations(s)
        if v:
            print(f"[warn] seed {s.get('routing_protocol')} coherence: {v}")

    set_proposer_mode("mock")            # closed axes — no LLM proposals this round
    reviewers = spec.get("evaluation", {}).get("reviewers", [])
    eval_fn = lambda g, sch, tasks: evaluate_ai(g, sch, tasks, reviewers)  # noqa: E731

    result = run(spec, schema, evaluate_fn=eval_fn, composite_fn=composite_fitness_ai)
    dump_run(result, str(OUT), spec["name"])

    trend = extract_trend(result)
    gaps = find_gaps(result, spec["search"]["cell_axes"])
    meta = compute_meta_fitness(result, trend)
    rankings = rank_all(spec, result, meta, use_ai_pairwise=True)
    write_report(str(OUT), spec["name"], spec, result, trend, gaps, meta, rankings)

    print(f"individuals : {len(result.population)}")
    print(f"cells filled: {len(result.elite_map)}")
    print("per-protocol elites (resource / congestion awareness shown):")
    for ind in sorted(result.champions(), key=lambda i: -i.composite):
        g = ind.genome
        print(f"  {g['routing_protocol']:18s} comp={ind.composite:.3f}  "
              f"res={g.get('resource_awareness','?'):18s} cong={g.get('congestion_awareness','?'):20s} (id={ind.id})")
    print("trend (top axes — does awareness trend upward?):")
    for axis, v in sorted(trend.normalized().items(), key=lambda kv: -abs(kv[1]))[:6]:
        mark = " <== NEW AXIS" if axis in R3_AXES else ""
        print(f"  {axis:24s} {v:+.2f}{mark}")
    for r in rankings:
        if r.entries:
            t = r.entries[0]
            print(f"scenario {r.scenario:18s} -> #1 id={t.individual_id} composite={t.composite:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
