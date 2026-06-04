"""MANET drone routing MAP-Elites — Round 2 (open-axes discovery).

Round 1 explored a curated 8-protocol design space and judged hybrid_ZRP /
clustering-AODV the champions. Round 2 turns on open-axes evolution: the LLM
proposer may invent NEW routing-protocol values and ENTIRELY NEW design axes,
seeded from Round 1's per-protocol champions, to discover designs beyond the
curated set.

The stock proposer (ai_proposer) is hardcoded for programming-language design,
so this runner monkeypatches operators' proposer hooks with MANET-aware
versions (a disaster-rescue MANET researcher persona + routing-framed prompts).

Run from the project root:
  AIPL_AI_PROVIDER=gemini AIPL_GEMINI_MODEL=gemini-2.5-flash-lite \
  python3 -m aice-evolution-v2.src.manet_round2_runner
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .schema import GeneSchema
from .map_elites import run, dump_run
from .ai_evaluator import evaluate_ai, composite_fitness_ai
from . import operators
from .operators import set_proposer_mode
from .aice_parser import default_operators
from .ai_proposer import _parse_one_token  # reuse the robust token parser
from .analysis import extract_trend, find_gaps, compute_meta_fitness
from .ranking import rank_all
from .reporter import write_report

import aipl_ai  # made importable by ai_evaluator's sys.path insert

EXP = Path("aice-pi-evolution/experiments/2026-06-04_manet_drone_evolution")
OUT = EXP / "out"
GA = OUT / "AIPL_DroneMANET_Round1.ga.json"
R1_LINEAGE = OUT / "AIPL_DroneMANET_Round1.lineage.json"

MANET_SYS = "あなたは災害救助ドローンの MANET/DTN ルーティングプロトコル研究者です。"
CONTEXT = ("山間部災害救助 UAV スウォームを Xinu+Raspberry Pi の実 WiFi メッシュで運用する。"
           "頻繁なネットワーク分断・UAV の高モビリティ・限られた RAM/CPU/WiFi・SOS 低遅延・"
           "バッテリ制約という条件で報われる設計を探す。")


# ---- MANET-aware replacements for the proposer hooks bound inside operators ----
def manet_axis_value(axis, schema, task_context=""):
    existing = ", ".join(schema.axes.get(axis, []))
    prompt = (f"{CONTEXT}\n\nMANET ルーティング設計の遺伝子軸 '{axis}' の既存値: {existing}\n\n"
              "この軸に追加すべき、次世代の新しい値を1つだけ提案してください。"
              "MANET/DTN/routing の実在概念に基づく識別子1語のみ (snake_case)。説明・前置き禁止。")
    try:
        reply = aipl_ai.call_ai(prompt, system=MANET_SYS, max_tokens=24)
    except Exception:
        return None
    token = _parse_one_token(reply)
    if not token or token in schema.axes.get(axis, []):
        return None
    return token


def manet_new_axis(schema, task_context=""):
    existing = ", ".join(schema.axes.keys())
    prompt = (f"{CONTEXT}\n\n既存の設計軸: {existing}\n\n"
              "災害救助 MANET ルーティングを特徴づけるかもしれない、新しい設計軸を1つ提案してください。\n"
              "1行目: 軸名 (snake_case)\n"
              "2行目: 許容値をカンマ区切りで (3〜5個、最も貧弱→最も強力の順)\n"
              "MANET/DTN の実在概念に基づくこと。説明・前置き禁止。")
    try:
        reply = aipl_ai.call_ai(prompt, system=MANET_SYS, max_tokens=80)
    except Exception:
        return None
    lines = [ln.strip() for ln in (reply or "").splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    name = _parse_one_token(lines[0])
    values = [v.strip() for v in lines[1].replace("、", ",").split(",") if v.strip()]
    values = [v for v in values if v]
    if not name or name in schema.axes or len(values) < 2:
        return None
    return (name, values[:5])


def seeds_from_round1():
    """Per-protocol champions from Round 1 as Round 2 seeds."""
    pop = json.loads(R1_LINEAGE.read_text(encoding="utf-8"))
    best = {}
    for ind in pop:
        p = ind["genome"]["routing_protocol"]
        if p not in best or ind["composite"] > best[p]["composite"]:
            best[p] = ind
    return [dict(b["genome"]) for b in best.values()]


def main() -> int:
    spec = json.loads(GA.read_text(encoding="utf-8"))
    spec["name"] = "AIPL_DroneMANET_Round2"
    schema = GeneSchema.load(EXP / spec["schema_ref"])
    schema.open_axes = True                       # allow register_value / register_axis

    spec["search"]["open_axes"] = True
    spec["search"]["seed_genomes"] = seeds_from_round1()
    spec["search"]["seed_count"] = 4
    spec["search"]["generations"] = 30
    spec["operators"] = default_operators(open_axes=True)   # turn on llm_proposal / llm_new_axis

    # inject MANET-aware proposers (operators imported these names into its namespace)
    operators.propose_axis_value_ai = manet_axis_value
    operators.propose_new_axis_ai = manet_new_axis
    # llm_proposal only proposes for axes present in SPECULATIVE_VALUES (a
    # programming-paradigm bank); register our MANET axes so new VALUES get
    # proposed for them too (empty bank → AI proposer is the only source).
    operators.SPECULATIVE_VALUES = {**operators.SPECULATIVE_VALUES,
                                    **{a: [] for a in schema.axes.keys()}}
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
    print(f"discovered protocol values: {schema.discovered_values.get('routing_protocol', [])}")
    print(f"discovered values (all axes): { {k:v for k,v in schema.discovered_values.items()} }")
    print(f"discovered NEW axes: {schema.discovered_axes}")
    print("per-protocol elites:")
    for ind in sorted(result.champions(), key=lambda i: -i.composite):
        star = "  *NEW*" if ind.genome["routing_protocol"] not in (
            "reactive_AODV","proactive_OLSR","hybrid_ZRP","geographic_GPSR",
            "epidemic_DTN","spray_and_wait_DTN","gossip_flood","link_state_SR") else ""
        print(f"  {ind.cell:42s} composite={ind.composite:.3f} (id={ind.id}, gen={ind.generation}){star}")
    print("trend (top axes):")
    for axis, v in sorted(trend.normalized().items(), key=lambda kv: -abs(kv[1]))[:6]:
        print(f"  {axis:24s} {v:+.2f}")
    for r in rankings:
        if r.entries:
            t = r.entries[0]
            print(f"scenario {r.scenario:18s} -> #1 id={t.individual_id} composite={t.composite:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
