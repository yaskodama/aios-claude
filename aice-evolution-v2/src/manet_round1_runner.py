"""MANET drone routing MAP-Elites runner with guaranteed protocol coverage.

The stock `cli --ai` seeds the population randomly, which (with a small budget)
visited only 4 of the 8 routing_protocol families and never evaluated the
current drone-hil design (reactive_AODV). This runner injects one coherent
seed genome per protocol family — including the *exact* current drone-hil
MANET layer config as the reactive_AODV baseline — via the additive
`spec["search"]["seed_genomes"]` hook, so every cell in the archive is filled
and the baseline is directly comparable to its evolved alternatives.

Run from the project root:
  AIPL_AI_PROVIDER=gemini AIPL_GEMINI_MODEL=gemini-2.5-flash-lite \
  python3 -m aice-evolution-v2.src.manet_round1_runner
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
GA = OUT / "AIPL_DroneMANET_Round1.ga.json"

# One coherent seed per routing_protocol family (satisfies the schema's
# coherence rules). reactive_AODV is the *current* drone-hil MANET layer.
SEEDS = [
    {  # === current drone-hil baseline ===
        "routing_protocol": "reactive_AODV", "buffering_strategy": "drop_on_partition",
        "link_metric": "hop_count", "topology_control": "range_pruning",
        "mobility_handling": "link_break_detect", "neighbor_discovery": "on_demand",
        "qos_priority": "sos_priority",
    },
    {
        "routing_protocol": "proactive_OLSR", "buffering_strategy": "drop_on_partition",
        "link_metric": "etx_quality", "topology_control": "clustering",
        "mobility_handling": "link_break_detect", "neighbor_discovery": "periodic_hello",
        "qos_priority": "sos_priority",
    },
    {
        "routing_protocol": "hybrid_ZRP", "buffering_strategy": "store_carry_forward",
        "link_metric": "etx_quality", "topology_control": "clustering",
        "mobility_handling": "link_break_detect", "neighbor_discovery": "periodic_hello",
        "qos_priority": "sos_priority",
    },
    {
        "routing_protocol": "geographic_GPSR", "buffering_strategy": "drop_on_partition",
        "link_metric": "hop_count", "topology_control": "power_control",
        "mobility_handling": "predictive_mobility", "neighbor_discovery": "beaconless",
        "qos_priority": "sos_priority",
    },
    {
        "routing_protocol": "epidemic_DTN", "buffering_strategy": "replicate_n_copies",
        "link_metric": "hop_count", "topology_control": "range_pruning",
        "mobility_handling": "link_break_detect", "neighbor_discovery": "on_demand",
        "qos_priority": "sos_priority",
    },
    {
        "routing_protocol": "spray_and_wait_DTN", "buffering_strategy": "store_carry_forward",
        "link_metric": "hop_count", "topology_control": "range_pruning",
        "mobility_handling": "predictive_mobility", "neighbor_discovery": "on_demand",
        "qos_priority": "sos_priority",
    },
    {
        "routing_protocol": "gossip_flood", "buffering_strategy": "store_carry_forward",
        "link_metric": "hop_count", "topology_control": "range_pruning",
        "mobility_handling": "link_break_detect", "neighbor_discovery": "on_demand",
        "qos_priority": "sos_priority",
    },
    {
        "routing_protocol": "link_state_SR", "buffering_strategy": "drop_on_partition",
        "link_metric": "etx_quality", "topology_control": "clustering",
        "mobility_handling": "link_break_detect", "neighbor_discovery": "periodic_hello",
        "qos_priority": "sos_priority",
    },
]


def main() -> int:
    spec = json.loads(GA.read_text(encoding="utf-8"))
    schema = GeneSchema.load(EXP / spec["schema_ref"])

    spec["search"]["seed_genomes"] = SEEDS
    spec["search"]["seed_count"] = 4         # a few randoms on top for intra-cell diversity
    spec["search"]["generations"] = 28       # refine each cell via mutation/crossover

    for s in SEEDS:
        viol = schema.coherence_violations(s)
        if viol:
            print(f"[warn] seed {s['routing_protocol']} violates coherence: {viol}")

    set_proposer_mode("ai")
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
    print("per-protocol elites:")
    for ind in sorted(result.champions(), key=lambda i: -i.composite):
        print(f"  {ind.cell:40s} composite={ind.composite:.3f}  (id={ind.id}, gen={ind.generation})")
    print("trend (top axes):")
    for axis, v in sorted(trend.normalized().items(), key=lambda kv: -abs(kv[1]))[:5]:
        print(f"  {axis:22s}  {v:+.2f}")
    for r in rankings:
        if r.entries:
            t = r.entries[0]
            print(f"scenario {r.scenario:18s} -> #1 id={t.individual_id} composite={t.composite:.3f} pareto={t.pareto_rank}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
