"""AIPL-v4 autoloop: multi-generation LLM-directed evolution for Stage-1.

Extends aipl_v4_evolve.py from "1 round" to a full evolutionary loop:

  Gen 0: hardcoded baselines (N1/N2/N3) + LLM children (M)
  Gen 1..N: top-K parents (elitism) + LLM children informed by parents' ppl
  Stop:  max_gens reached OR best ppl unchanged for `patience` gens

Run:
    .venv/bin/python aipl_v4_autoloop.py --max-gens 5 --children 4 --parents-keep 3
    .venv/bin/python aipl_v4_autoloop.py --no-llm           # sanity (baselines only)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from common import CORPUS_SHA256, load_corpus, split_corpus
from candidates.ngram_real import candidate_N1, candidate_N2, candidate_N3
from reviewers import review_all
from stages import STAGES

from aipl_v4_evolve import (
    evaluate_genome,
    propose_stage1_candidates,
    build_estimate,
    baseline_genome_for,
)

OUT_DIR = HERE / "out"


PROMPT_HEADER_TEMPLATE = """You are an evolutionary search agent for a character-level n-gram language model.
Corpus: tiny (~9.5KB ASCII text). Lower holdout perplexity (ppl) is better.

Design space:
  - n: integer in {{1, 2, 3, 4, 5}} (1=unigram, ..., 5=quintgram)
  - alpha: float in 0.01..3.0 (smoothing strength)
  - style: ONE OF five smoothing families:
      * "plain"       — Laplace +alpha smoothing, single n-gram
      * "backoff"     — Laplace with (n-1) fallback when context unseen
      * "kneser_ney"  — Kneser-Ney continuation-count smoothing (alpha = discount D, 0.5-0.9 typical)
      * "modified_kn" — Modified Kneser-Ney with 3 discount levels by n-gram count (alpha sets D2)
      * "kn_ctx"      — G2 (new): context-conditional KN. D varies by CONTEXT count tier
                        (ctx_total<=2 -> 1.3*alpha, 3..10 -> alpha, >=11 -> 0.6*alpha).
                        Designed for tiny corpora with many sparse contexts.

Generation {gen}. Top performers so far (lower ppl wins):
{parents_table}

Empirical lessons from prior runs (very important):
  - "backoff + n>=3 + alpha<=0.2" tends to win for plain/backoff.
  - "plain + n>=5 + alpha>=1.0" almost always loses (ppl > 100) because high alpha smooths a sparse high-order distribution into unigram-like noise.
  - On a 9.5KB corpus, raw plain 5-grams are too sparse; backoff is needed for n>=4.
  - Kneser-Ney is known to outperform Laplace on small corpora. Typical D (alpha) is 0.5-0.9. Modified-KN n=5 alpha=0.8 is the current champion (ppl 3.54).
  - For KN-family, alpha < 0.3 is rare (too little discount); alpha > 1.0 makes no sense (D must be < 1).
  - kn_ctx is brand new — try n=4 or 5 with alpha 0.4-0.8. Should beat modified_kn when many contexts are sparse.

Your job: propose {num} NEW candidates that are *different from the parents above*
and likely to *beat the current best (ppl={best_ppl:.3f})*. Explore intelligently.
At least one candidate this generation MUST use "kn_ctx".
DO NOT repeat a parent's (style, n, alpha) tuple verbatim.

Output ONLY a JSON array of exactly {num} objects, no markdown fences, no commentary.
Each object MUST have these keys exactly:
  "name"      : short tag starting with "L" (e.g. "L1", "Lkn", "Lg3", "Lmkn", "Lctx")
  "style"     : "plain", "backoff", "kneser_ney", "modified_kn", or "kn_ctx"
  "n"         : integer 1..5
  "alpha"     : number in 0.01..3.0
  "rationale" : one sentence why this variant might beat the current best
"""


def _parents_table(parents_with_ppl: list[tuple[dict, float]]) -> str:
    lines = []
    for g, ppl in parents_with_ppl:
        style = g.get("style", "?")
        n = g.get("n", "?")
        alpha = g.get("alpha", "?")
        src = g.get("source", "baseline")
        lines.append(f"  - {g['name']}: style={style}, n={n}, alpha={alpha}, ppl={ppl:.3f} [{src}]")
    return "\n".join(lines)


class GenLogger:
    """Captures per-generation summaries for the lineage file."""

    def __init__(self):
        self.generations: list[dict] = []

    def add(self, gen_idx: int, population: list[dict], elapsed: float, llm_telemetry: dict | None):
        # population entries are {"genome", "measured", "estimate", "review", "kind"}
        ranked = sorted(population, key=lambda r: r["measured"]["holdout_ppl"])
        self.generations.append({
            "gen": gen_idx,
            "elapsed_sec": round(elapsed, 2),
            "llm_telemetry": llm_telemetry,
            "population": ranked,
            "best_ppl": ranked[0]["measured"]["holdout_ppl"] if ranked else None,
            "best_name": ranked[0]["measured"]["name"] if ranked else None,
        })


def _parse_models(args) -> list[str]:
    """Return the ordered list of proposer model tags. `--models` (comma-sep) wins over `--model`."""
    if getattr(args, "models", None):
        raw = [m.strip() for m in args.models.split(",") if m.strip()]
        if raw:
            return raw
    return [args.model]


def _split_children(total: int, n_models: int) -> list[int]:
    """Split `total` children across `n_models` (extras go to early models)."""
    if n_models <= 0:
        return []
    base, rem = divmod(total, n_models)
    return [base + (1 if i < rem else 0) for i in range(n_models)]


def _propose_from_model(
    *,
    prompt: str,
    model: str,
    num: int,
    temperature: float,
    timeout: float,
    max_retries: int,
    seen_genome_keys: set,
    existing_names: set,
) -> tuple[list[dict], dict]:
    """Ask one Ollama model for `num` children given a fully-formed prompt.
    Validates + dedupes against shared seen_genome_keys/existing_names sets.
    """
    from aipl_v4_evolve import call_ollama, _extract_json_array, _validate
    import urllib.error
    from stages import COMMON_REPRO

    telemetry = {"model": model, "temperature": temperature, "requested": num,
                 "attempts": [], "prompt_chars": len(prompt)}
    validated: list[dict] = []
    seen_names_local: set[str] = set()
    for attempt in range(1, max_retries + 1):
        t0 = time.monotonic()
        try:
            raw = call_ollama(prompt, model, temperature, timeout)
        except (urllib.error.URLError, TimeoutError) as exc:
            telemetry["attempts"].append({"attempt": attempt, "error": f"transport: {exc}",
                                          "elapsed": time.monotonic() - t0})
            continue
        elapsed = time.monotonic() - t0
        parsed = _extract_json_array(raw)
        att_log = {"attempt": attempt, "elapsed": round(elapsed, 2), "raw_chars": len(raw),
                   "parsed_count": len(parsed) if isinstance(parsed, list) else None,
                   "rejections": []}
        if not isinstance(parsed, list):
            att_log["error"] = "no JSON array in response"
            telemetry["attempts"].append(att_log)
            continue
        for c in parsed:
            reason = _validate(c)
            if reason is not None:
                att_log["rejections"].append({"candidate": c, "reason": reason})
                continue
            key = (c["style"], int(c["n"]), float(c["alpha"]))
            if key in seen_genome_keys:
                att_log["rejections"].append({"candidate": c, "reason": "duplicate genome key"})
                continue
            name = c["name"]
            if name in seen_names_local:
                att_log["rejections"].append({"candidate": c, "reason": f"duplicate name {name}"})
                continue
            # Rename if name already taken (across generations / models)
            uniq = name
            while uniq in existing_names or uniq in seen_names_local:
                uniq = uniq + "+"
                if len(uniq) > 12:
                    break
            validated.append({
                "name": uniq,
                "style": c["style"],
                "n": int(c["n"]),
                "alpha": float(c["alpha"]),
                "rationale": c.get("rationale", ""),
                "source": "llm",
                "param_class": "32K",
                **{k: COMMON_REPRO[k] for k in COMMON_REPRO},
            })
            seen_names_local.add(uniq)
        telemetry["attempts"].append(att_log)
        if len(validated) >= num:
            break
    telemetry["validated_count"] = len(validated)
    return validated[:num], telemetry


def _hardcoded_baselines(train_bytes: bytes, holdout_bytes: bytes) -> list[dict]:
    out = []
    for fn in (candidate_N1, candidate_N2, candidate_N3):
        m = fn(train_bytes, holdout_bytes)
        m["source"] = "baseline"
        out.append(m)
    return out


def _measure(genome: dict, train_b: bytes, hold_b: bytes) -> dict:
    """Train + evaluate one LLM-style genome (style in {plain,backoff})."""
    m = evaluate_genome(genome, train_b, hold_b)
    m["source"] = "llm"
    m["rationale"] = genome.get("rationale", "")
    return m


def _wrap(genome: dict, measured: dict) -> dict:
    est = build_estimate(measured, genome)
    review = review_all(est, genome)
    return {"genome": genome, "measured": measured, "estimate": est, "review": review,
            "kind": measured.get("source", "?")}


def run_loop(args) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"corpus sha256 = {CORPUS_SHA256}")
    raw = load_corpus()
    train, holdout = split_corpus(raw)
    print(f"corpus: {len(raw)} bytes, train {len(train)}, holdout {len(holdout)}")

    logger = GenLogger()

    # ---------- Gen 0: baselines + (optional) LLM children -------------
    print("\n========== Generation 0 ==========")
    t_gen = time.monotonic()
    baseline_measured = _hardcoded_baselines(train, holdout)
    population = []
    for m in baseline_measured:
        g = baseline_genome_for(m)
        population.append(_wrap(g, m))
        print(f"  [baseline] {m['name']:<3} ppl={m['holdout_ppl']:.4f} params={m['params_observed']:,}")

    models = _parse_models(args)
    per_model = _split_children(args.children, len(models))

    telemetry_list: list[dict] = []
    if not args.no_llm:
        baseline_genomes = [r["genome"] for r in population]
        for mi, model in enumerate(models):
            n_req = per_model[mi]
            if n_req == 0:
                continue
            print(f"\n  -> asking {model} for {n_req} children")
            proposals, tel = propose_stage1_candidates(
                baseline_genomes,
                num=n_req,
                model=model,
                temperature=args.temperature,
                timeout=args.timeout,
                max_retries=args.max_retries,
            )
            tel["proposer_model"] = model
            telemetry_list.append(tel)
            print(f"     validated: {len(proposals)} / {n_req}")
            for g in proposals:
                g["proposed_by"] = model
                m = _measure(g, train, holdout)
                m["proposed_by"] = model
                population.append(_wrap(g, m))
                print(f"  [{model[:11]:<11}] {m['name']:<5} style={g['style']:<8} n={g['n']} alpha={g['alpha']:.3g} "
                      f"ppl={m['holdout_ppl']:.4f} params={m['params_observed']:,}")

    logger.add(0, population, time.monotonic() - t_gen, telemetry_list)
    best_ppl_history = [min(r["measured"]["holdout_ppl"] for r in population)]
    print(f"\n  -- gen 0 best ppl = {best_ppl_history[-1]:.4f}")

    # ---------- Gen 1..N --------------------------------------------------
    stagnation = 0
    seen_genome_keys: set[tuple] = set()
    for r in population:
        g = r["genome"]
        seen_genome_keys.add((g.get("style"), g.get("n"), g.get("alpha")))

    for gen in range(1, args.max_gens):
        if args.no_llm:
            print(f"\n  (skip gen {gen}: --no-llm)")
            break

        print(f"\n========== Generation {gen} ==========")
        t_gen = time.monotonic()

        # Elitism: top-K from current population
        ranked = sorted(population, key=lambda r: r["measured"]["holdout_ppl"])
        parents = ranked[: args.parents_keep]
        parents_with_ppl = [(p["genome"], p["measured"]["holdout_ppl"]) for p in parents]
        best_ppl = parents_with_ppl[0][1]

        prompt_header = PROMPT_HEADER_TEMPLATE.format(
            gen=gen,
            parents_table=_parents_table(parents_with_ppl),
            num=args.children,
            best_ppl=best_ppl,
        )
        prompt_tail = (
            "Example output:\n"
            '[{"name":"L1","style":"backoff","n":4,"alpha":0.1,"rationale":"deeper context with sharp smoothing"},'
            '{"name":"L2","style":"plain","n":2,"alpha":0.3,"rationale":"modest bigram baseline"}]'
        )

        prompt = prompt_header + "\n" + prompt_tail
        gen_telemetry: list[dict] = []
        all_validated: list[dict] = []
        existing_names = {r["genome"].get("name") for r in population}

        for mi, model in enumerate(models):
            n_req = per_model[mi]
            if n_req == 0:
                continue
            validated, tel = _propose_from_model(
                prompt=prompt,
                model=model,
                num=n_req,
                temperature=args.temperature,
                timeout=args.timeout,
                max_retries=args.max_retries,
                seen_genome_keys=seen_genome_keys,
                existing_names=existing_names,
            )
            tel["proposer_model"] = model
            gen_telemetry.append(tel)
            for g in validated:
                g["proposed_by"] = model
                existing_names.add(g["name"])
                seen_genome_keys.add((g["style"], g["n"], g["alpha"]))
            all_validated.extend(validated)
            print(f"  -> {model} validated {len(validated)} / {n_req} children "
                  f"(best parent ppl={best_ppl:.3f})")

        # Evaluate children, combine with elite parents
        next_gen_population: list[dict] = list(parents)  # elitism keeps parents
        for g in all_validated:
            m = _measure(g, train, holdout)
            m["proposed_by"] = g.get("proposed_by", "?")
            next_gen_population.append(_wrap(g, m))
            tag_model = g.get("proposed_by", "llm")[:11]
            print(f"  [{tag_model:<11}] {m['name']:<5} style={g['style']:<8} n={g['n']} alpha={g['alpha']:.3g} "
                  f"ppl={m['holdout_ppl']:.4f}")

        population = next_gen_population
        logger.add(gen, population, time.monotonic() - t_gen, gen_telemetry)
        cur_best = min(r["measured"]["holdout_ppl"] for r in population)
        best_ppl_history.append(cur_best)
        improved = cur_best < best_ppl_history[-2] - 1e-9
        print(f"\n  -- gen {gen} best ppl = {cur_best:.4f}"
              f" {'(improved)' if improved else f'(stagnation {stagnation+1}/{args.patience})'}")
        if improved:
            stagnation = 0
        else:
            stagnation += 1
            if stagnation >= args.patience:
                print(f"\n  >> early stop at gen {gen}: no improvement for {args.patience} generations")
                break

    # ---------- finalize ------------------------------------------------
    final_ranked = sorted(population, key=lambda r: r["measured"]["holdout_ppl"])
    winner = final_ranked[0]
    print("\n========== FINAL RANKING ==========")
    for r in final_ranked[:10]:
        m = r["measured"]
        rv = r["review"]
        print(f"  [{r['kind']:<8}] {m['name']:<5} ppl={m['holdout_ppl']:.4f}  "
              f"norm={rv['normalized_total']:.3f}")
    print(f"\nwinner: {winner['measured']['name']} (kind={winner['kind']}) "
          f"ppl={winner['measured']['holdout_ppl']:.4f}")

    print("\nbest ppl trajectory:")
    for i, p in enumerate(best_ppl_history):
        delta = ""
        if i > 0:
            d = (best_ppl_history[i - 1] - p) / best_ppl_history[i - 1] * 100
            delta = f"  ({d:+.1f}% vs prev)"
        print(f"  gen {i}: {p:.4f}{delta}")

    # save lineage
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = args.out_name or f"aipl_v4_autoloop_{ts}.json"
    lineage = {
        "schema": "aipl_v4_autoloop.v1",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "corpus_sha256": CORPUS_SHA256,
        "args": {
            "model": args.model if not args.no_llm else None,
            "models": _parse_models(args) if not args.no_llm else None,
            "max_gens": args.max_gens,
            "children": args.children,
            "parents_keep": args.parents_keep,
            "patience": args.patience,
            "temperature": args.temperature,
            "no_llm": args.no_llm,
        },
        "generations": logger.generations,
        "best_ppl_history": best_ppl_history,
        "winner": {
            "name": winner["measured"]["name"],
            "kind": winner["kind"],
            "proposed_by": winner["measured"].get("proposed_by", "baseline"),
            "holdout_ppl": winner["measured"]["holdout_ppl"],
            "genome": winner["genome"],
        },
    }
    out_path = OUT_DIR / out_name
    out_path.write_text(json.dumps(lineage, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nlineage saved: {out_path}")
    return lineage


def main():
    p = argparse.ArgumentParser(description="AIPL-v4 multi-generation LLM-directed loop")
    p.add_argument("--model", default="gemma2:2b")
    p.add_argument("--models", default=None,
                   help="Comma-separated list of proposer models for ensemble mode. Overrides --model. "
                        "Children are split across them per gen.")
    p.add_argument("--max-gens", type=int, default=5, help="Maximum number of generations")
    p.add_argument("--children", type=int, default=4, help="LLM children per generation")
    p.add_argument("--parents-keep", type=int, default=3, help="Elite parents carried forward")
    p.add_argument("--patience", type=int, default=2, help="Stop after this many non-improving gens")
    p.add_argument("--temperature", type=float, default=0.6)
    p.add_argument("--timeout", type=float, default=180.0)
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--no-llm", action="store_true", help="Run only baselines (sanity)")
    p.add_argument("--out-name", default=None)
    args = p.parse_args()
    run_loop(args)


if __name__ == "__main__":
    main()
