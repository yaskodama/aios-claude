"""AIPL-v4 MAP-Elites autoloop: archive-based diversity search for Stage-1.

Replaces the top-K elitist autoloop with a 3D MAP-Elites archive:

    cell = (smoothing_family, n, alpha_bin)
        smoothing_family in {plain, backoff, kneser_ney, modified_kn}     (4)
        n in {1,2,3,4,5}                                                   (5)
        alpha_bin in {tiny<0.05, small<0.2, mid<0.5, large<1.0, big>=1.0}  (5)
    total cells = 100

Each gen: LLM proposers see (champion, diverse elites, empty cells) and propose
N children; we accept a child into its cell iff the cell is empty OR the
child's ppl beats the current occupant. Stop on patience gens with neither a
new cell filled nor a champion improvement.

Seeds: N1/N2/N3 baselines + the 5 prior autoloop winners (L4, Lg4a, L3d, Lg6,
L5mkn) so the archive starts with 8 cells filled.

Run:
    .venv/bin/python aipl_v4_map_elites.py \
        --models gemma2:2b,llama3.2:3b --max-gens 8 --children 6 --patience 3
    .venv/bin/python aipl_v4_map_elites.py --no-llm   # seed-only sanity
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from common import CORPUS_SHA256, load_corpus, split_corpus
from candidates.ngram_real import candidate_N1, candidate_N2, candidate_N3
from reviewers import review_all
from stages import COMMON_REPRO

from aipl_v4_evolve import (
    evaluate_genome,
    build_estimate,
    baseline_genome_for,
    call_ollama,
    _extract_json_array,
    _validate,
)

OUT_DIR = HERE / "out"

SMOOTHINGS = ("plain", "backoff", "kneser_ney", "modified_kn")
N_VALUES = (1, 2, 3, 4, 5)
ALPHA_BINS = (
    ("tiny",  0.001, 0.05),
    ("small", 0.05,  0.2),
    ("mid",   0.2,   0.5),
    ("large", 0.5,   1.0),
    ("big",   1.0,   5.0),
)


def alpha_bin_of(alpha: float) -> str:
    a = float(alpha)
    for name, lo, hi in ALPHA_BINS:
        if lo <= a < hi:
            return name
    return ALPHA_BINS[-1][0]  # >=1.0 falls into "big"


def cell_of(genome: dict) -> tuple[str, int, str]:
    return (genome["style"], int(genome["n"]), alpha_bin_of(genome["alpha"]))


def all_cells() -> list[tuple[str, int, str]]:
    out = []
    for s in SMOOTHINGS:
        for n in N_VALUES:
            for ab, _, _ in ALPHA_BINS:
                out.append((s, n, ab))
    return out


TOTAL_CELLS = len(all_cells())  # 100


# ---------- LLM proposer prompt -----------------------------------------

PROMPT_TEMPLATE = """You are an evolutionary search agent for a character-level n-gram language model on a tiny 9.5KB ASCII corpus. Lower holdout perplexity (ppl) is better. We are running MAP-Elites: every (smoothing, n, alpha_bin) cell holds at most one genome — the lowest-ppl one seen for that cell.

Design space:
  - n: integer in {{1, 2, 3, 4, 5}}
  - alpha: float in 0.001..5.0
      alpha_bin = tiny (<0.05) | small (<0.2) | mid (<0.5) | large (<1.0) | big (>=1.0)
  - style (smoothing family):
      * "plain"       — Laplace +alpha, single n-gram
      * "backoff"     — Laplace with (n-1) fallback
      * "kneser_ney"  — Kneser-Ney continuation smoothing (alpha = discount D, 0.3-0.9 typical)
      * "modified_kn" — Modified Kneser-Ney (alpha sets D2, 0.3-0.9 typical)

Generation {gen} of MAP-Elites. Current champion (lowest ppl):
{champion_line}

Diverse elites currently in archive (sampled from {n_filled} filled cells of {total_cells}):
{elites_table}

Unfilled cells you can claim by proposing a genome that lands there
(cell = (smoothing, n, alpha_bin)); claiming an empty cell ALWAYS succeeds:
{empty_cells_table}

Empirical lessons:
  - "backoff + n>=3 + alpha in tiny/small" tends to be strong.
  - "plain + n>=4 + alpha=big" is almost always >100 ppl (kept only for diversity).
  - KN/modified_kn with n in 3-5 and alpha in mid/large is the current winning region.
  - For KN-family, alpha >= 1.0 (big bin) is semantically degenerate (D must be <1) but still represents one cell.

Your job: propose {num} candidates. Prioritize:
  (a) filling empty cells listed above (CHEAP wins for diversity), and
  (b) beating the champion in cells near its region.
Aim for variety — do NOT cluster proposals in the same cell.

Output ONLY a JSON array of exactly {num} objects, no markdown fences, no commentary.
Each object MUST have:
  "name"      : short tag starting with "L" (e.g. "Le1", "LkE", "LmE3")
  "style"     : "plain" | "backoff" | "kneser_ney" | "modified_kn"
  "n"         : integer 1..5
  "alpha"     : number in 0.001..5.0
  "rationale" : one short sentence (mention the cell or what it explores)

Example:
[{{"name":"Le1","style":"kneser_ney","n":2,"alpha":0.04,"rationale":"fill (kneser_ney,2,tiny)"}},{{"name":"Le2","style":"modified_kn","n":5,"alpha":0.35,"rationale":"new (modified_kn,5,mid) — current champion is large bin"}}]
"""


def _champion_line(champion: dict | None) -> str:
    if not champion:
        return "  (none yet)"
    g = champion["genome"]
    return (f"  {g['name']}: style={g['style']}, n={g['n']}, alpha={g['alpha']:g} "
            f"(cell={cell_of(g)}), ppl={champion['ppl']:.4f}")


def _elites_table(elites: list[dict]) -> str:
    if not elites:
        return "  (none)"
    rows = []
    for e in elites:
        g = e["genome"]
        rows.append(f"  - cell={cell_of(g)}: {g['name']} alpha={g['alpha']:g} ppl={e['ppl']:.3f}")
    return "\n".join(rows)


def _empty_cells_table(empty: list[tuple[str, int, str]], max_show: int = 18) -> str:
    if not empty:
        return "  (none — archive is full)"
    shown = empty[:max_show]
    rows = [f"  - {c}" for c in shown]
    if len(empty) > max_show:
        rows.append(f"  ... and {len(empty) - max_show} more")
    return "\n".join(rows)


# ---------- archive -----------------------------------------------------

def make_entry(genome: dict, measured: dict) -> dict:
    est = build_estimate(measured, genome)
    review = review_all(est, genome)
    return {
        "genome": genome,
        "measured": measured,
        "estimate": est,
        "review": review,
        "ppl": measured["holdout_ppl"],
        "cell": list(cell_of(genome)),
        "kind": measured.get("source", genome.get("source", "?")),
    }


def try_insert(archive: dict[tuple, dict], entry: dict) -> tuple[bool, str]:
    """Insert into MAP-Elites archive. Returns (accepted, reason)."""
    cell = tuple(entry["cell"])
    occupant = archive.get(cell)
    if occupant is None:
        archive[cell] = entry
        return True, "new-cell"
    if entry["ppl"] < occupant["ppl"] - 1e-9:
        archive[cell] = entry
        return True, f"beat {occupant['ppl']:.4f} -> {entry['ppl']:.4f}"
    return False, f"keep {occupant['genome']['name']} ppl={occupant['ppl']:.4f}"


# ---------- seeding -----------------------------------------------------

PRIOR_WINNERS = [
    {"name": "L4",    "style": "backoff",     "n": 3, "alpha": 0.2,  "source": "prior-winner",
     "rationale": "gemma2:2b autoloop gen-1 (ppl 11.34)"},
    {"name": "Lg4a",  "style": "backoff",     "n": 4, "alpha": 0.05, "source": "prior-winner",
     "rationale": "gemma2:2b autoloop final (ppl 9.96)"},
    {"name": "L3d",   "style": "backoff",     "n": 3, "alpha": 0.08, "source": "prior-winner",
     "rationale": "llama3.2:3b autoloop final (ppl 8.30)"},
    {"name": "Lg6",   "style": "backoff",     "n": 4, "alpha": 0.01, "source": "prior-winner",
     "rationale": "gemma+llama ensemble winner (ppl 7.15)"},
    {"name": "L5mkn", "style": "modified_kn", "n": 5, "alpha": 0.8,  "source": "prior-winner",
     "rationale": "G1 KN-aware ensemble champion (ppl 3.54)"},
]


def seed_archive(train_b: bytes, hold_b: bytes) -> tuple[dict[tuple, dict], list[str]]:
    archive: dict[tuple, dict] = {}
    log: list[str] = []
    # Hardcoded baselines (use the existing candidate functions so they share params_observed).
    for fn in (candidate_N1, candidate_N2, candidate_N3):
        m = fn(train_b, hold_b)
        m["source"] = "baseline"
        g = baseline_genome_for(m)
        # Baselines lack the LLM-style genome keys — derive from candidate name.
        g = {**g, "name": m["name"]}
        if g["name"] == "N1":
            g.update({"style": "plain",   "n": 1, "alpha": 1.0})
        elif g["name"] == "N2":
            g.update({"style": "plain",   "n": 2, "alpha": 1.0})
        elif g["name"] == "N3":
            g.update({"style": "backoff", "n": 3, "alpha": 1.0})
        entry = make_entry(g, m)
        ok, _ = try_insert(archive, entry)
        log.append(f"  [baseline] {m['name']:<5} cell={cell_of(g)} ppl={m['holdout_ppl']:.4f} {'+' if ok else '='}")

    # Prior winners — retrain on the same corpus to get current ppl numbers.
    for g0 in PRIOR_WINNERS:
        g = {**g0, "param_class": "32K", **{k: COMMON_REPRO[k] for k in COMMON_REPRO}}
        m = evaluate_genome(g, train_b, hold_b)
        m["source"] = "prior-winner"
        m["rationale"] = g.get("rationale", "")
        entry = make_entry(g, m)
        ok, _ = try_insert(archive, entry)
        log.append(f"  [prior]    {g['name']:<5} cell={cell_of(g)} ppl={m['holdout_ppl']:.4f} {'+' if ok else '='}")
    return archive, log


# ---------- proposer driver ---------------------------------------------

def _split_children(total: int, n_models: int) -> list[int]:
    if n_models <= 0:
        return []
    base, rem = divmod(total, n_models)
    return [base + (1 if i < rem else 0) for i in range(n_models)]


def _diverse_elites(archive: dict[tuple, dict], k: int, rng: random.Random,
                    exclude_champion: bool = True) -> list[dict]:
    if not archive:
        return []
    entries = list(archive.values())
    entries.sort(key=lambda e: e["ppl"])
    champion = entries[0]
    pool = entries[1:] if exclude_champion else entries
    # bucket by smoothing family to encourage variety
    by_family: dict[str, list[dict]] = {}
    for e in pool:
        by_family.setdefault(e["genome"]["style"], []).append(e)
    out: list[dict] = []
    families = list(by_family.keys())
    rng.shuffle(families)
    while len(out) < k and any(by_family[f] for f in families):
        for f in families:
            if not by_family[f]:
                continue
            out.append(by_family[f].pop(0))
            if len(out) >= k:
                break
    return out


def _empty_cells(archive: dict[tuple, dict], rng: random.Random,
                 limit: int | None = None) -> list[tuple[str, int, str]]:
    empty = [c for c in all_cells() if c not in archive]
    rng.shuffle(empty)
    return empty if limit is None else empty[:limit]


def _ask_model(prompt: str, model: str, num: int, temperature: float,
               timeout: float, max_retries: int,
               existing_names: set[str]) -> tuple[list[dict], dict]:
    telemetry = {"model": model, "temperature": temperature, "requested": num,
                 "attempts": [], "prompt_chars": len(prompt)}
    validated: list[dict] = []
    seen_local: set[str] = set()
    for attempt in range(1, max_retries + 1):
        t0 = time.monotonic()
        try:
            raw = call_ollama(prompt, model, temperature, timeout)
        except (urllib.error.URLError, TimeoutError) as exc:
            telemetry["attempts"].append({"attempt": attempt,
                                          "error": f"transport: {exc}",
                                          "elapsed": time.monotonic() - t0})
            continue
        elapsed = time.monotonic() - t0
        parsed = _extract_json_array(raw)
        att = {"attempt": attempt, "elapsed": round(elapsed, 2),
               "raw_chars": len(raw),
               "parsed_count": len(parsed) if isinstance(parsed, list) else None,
               "rejections": []}
        if not isinstance(parsed, list):
            att["error"] = "no JSON array"
            telemetry["attempts"].append(att)
            continue
        for c in parsed:
            reason = _validate(c)
            if reason is not None:
                att["rejections"].append({"candidate": c, "reason": reason})
                continue
            uniq = c["name"]
            while uniq in existing_names or uniq in seen_local:
                uniq += "+"
                if len(uniq) > 14:
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
            seen_local.add(uniq)
        telemetry["attempts"].append(att)
        if len(validated) >= num:
            break
    telemetry["validated_count"] = len(validated)
    return validated[:num], telemetry


# ---------- main loop ---------------------------------------------------

def run_loop(args) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    print(f"corpus sha256 = {CORPUS_SHA256}")
    raw = load_corpus()
    train, holdout = split_corpus(raw)
    print(f"corpus: {len(raw)} bytes, train {len(train)}, holdout {len(holdout)}")

    print(f"\n========== Seed (Gen 0) ==========")
    t0 = time.monotonic()
    archive, seed_log = seed_archive(train, holdout)
    for line in seed_log:
        print(line)
    print(f"  -- gen 0 archive: {len(archive)}/{TOTAL_CELLS} cells filled "
          f"in {time.monotonic()-t0:.2f}s")

    champion = min(archive.values(), key=lambda e: e["ppl"])
    print(f"  -- gen 0 champion: {champion['genome']['name']} "
          f"ppl={champion['ppl']:.4f} cell={tuple(champion['cell'])}")

    history = [{
        "gen": 0,
        "filled_cells": len(archive),
        "champion_name": champion["genome"]["name"],
        "champion_ppl": champion["ppl"],
        "champion_cell": list(cell_of(champion["genome"])),
        "elapsed_sec": round(time.monotonic() - t0, 2),
    }]

    models = [m.strip() for m in (args.models or args.model).split(",") if m.strip()]
    per_model = _split_children(args.children, len(models))

    stagnation = 0

    for gen in range(1, args.max_gens):
        if args.no_llm:
            print(f"\n  (skip gen {gen}: --no-llm)")
            break
        print(f"\n========== Generation {gen} ==========")
        t_gen = time.monotonic()

        elites = _diverse_elites(archive, k=args.elite_show, rng=rng, exclude_champion=True)
        empty = _empty_cells(archive, rng=rng)
        prompt = PROMPT_TEMPLATE.format(
            gen=gen,
            champion_line=_champion_line({"genome": champion["genome"], "ppl": champion["ppl"]}),
            n_filled=len(archive),
            total_cells=TOTAL_CELLS,
            elites_table=_elites_table(elites),
            empty_cells_table=_empty_cells_table(empty),
            num=args.children,
        )

        gen_tel: list[dict] = []
        all_validated: list[dict] = []
        existing_names = {e["genome"]["name"] for e in archive.values()}

        for mi, model in enumerate(models):
            n_req = per_model[mi]
            if n_req == 0:
                continue
            validated, tel = _ask_model(
                prompt=prompt,
                model=model,
                num=n_req,
                temperature=args.temperature,
                timeout=args.timeout,
                max_retries=args.max_retries,
                existing_names=existing_names,
            )
            tel["proposer_model"] = model
            gen_tel.append(tel)
            for g in validated:
                g["proposed_by"] = model
                existing_names.add(g["name"])
            all_validated.extend(validated)
            print(f"  -> {model} validated {len(validated)} / {n_req} "
                  f"(empty cells: {len(empty)})")

        # Evaluate + try to insert
        accepted = 0
        new_cells = 0
        for g in all_validated:
            m = evaluate_genome(g, train, holdout)
            m["source"] = "llm"
            m["rationale"] = g.get("rationale", "")
            m["proposed_by"] = g.get("proposed_by", "?")
            entry = make_entry(g, m)
            had_cell = tuple(entry["cell"]) in archive
            ok, why = try_insert(archive, entry)
            tag_model = g.get("proposed_by", "llm")[:11]
            mark = "+" if ok else "="
            print(f"  [{tag_model:<11}] {g['name']:<6} {mark} cell={tuple(entry['cell'])} "
                  f"ppl={m['holdout_ppl']:.4f}  ({why})")
            if ok:
                accepted += 1
                if not had_cell:
                    new_cells += 1

        prev_champion_ppl = champion["ppl"]
        champion = min(archive.values(), key=lambda e: e["ppl"])
        improved_ppl = champion["ppl"] < prev_champion_ppl - 1e-9
        progress = improved_ppl or new_cells > 0

        history.append({
            "gen": gen,
            "filled_cells": len(archive),
            "new_cells_this_gen": new_cells,
            "accepted_this_gen": accepted,
            "candidates_evaluated": len(all_validated),
            "champion_name": champion["genome"]["name"],
            "champion_ppl": champion["ppl"],
            "champion_cell": list(cell_of(champion["genome"])),
            "telemetry": gen_tel,
            "elapsed_sec": round(time.monotonic() - t_gen, 2),
        })
        print(f"\n  -- gen {gen}: filled={len(archive)}/{TOTAL_CELLS} "
              f"(+{new_cells} new), accepted={accepted}/{len(all_validated)}, "
              f"champion={champion['genome']['name']} ppl={champion['ppl']:.4f}"
              f" {'(improved)' if improved_ppl else ''}")

        if progress:
            stagnation = 0
        else:
            stagnation += 1
            if stagnation >= args.patience:
                print(f"\n  >> early stop at gen {gen}: no progress (no new cell, no ppl gain) "
                      f"for {args.patience} gens")
                break

    # ---------- finalize -------------------------------------------------
    print("\n========== ARCHIVE SUMMARY ==========")
    print(f"  cells filled: {len(archive)} / {TOTAL_CELLS} ({100*len(archive)/TOTAL_CELLS:.1f}%)")
    print(f"  champion: {champion['genome']['name']} "
          f"style={champion['genome']['style']} n={champion['genome']['n']} "
          f"alpha={champion['genome']['alpha']:g} cell={tuple(champion['cell'])} "
          f"ppl={champion['ppl']:.4f}")

    print("\n  per-family coverage:")
    for s in SMOOTHINGS:
        cnt = sum(1 for k in archive if k[0] == s)
        per_n = {n: sum(1 for k in archive if k[0] == s and k[1] == n) for n in N_VALUES}
        print(f"    {s:<12}: {cnt:>2} cells   per-n: {per_n}")

    print("\n  top-10 by ppl:")
    for e in sorted(archive.values(), key=lambda x: x["ppl"])[:10]:
        g = e["genome"]
        print(f"    [{e['kind']:<12}] {g['name']:<6} cell={tuple(e['cell'])} "
              f"alpha={g['alpha']:g} ppl={e['ppl']:.4f}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = args.out_name or f"aipl_v4_map_elites_{ts}.json"
    archive_json = []
    for cell, entry in sorted(archive.items()):
        archive_json.append({
            "cell": list(cell),
            "genome": entry["genome"],
            "measured": entry["measured"],
            "estimate": entry["estimate"],
            "review": entry["review"],
            "ppl": entry["ppl"],
            "kind": entry["kind"],
        })
    lineage = {
        "schema": "aipl_v4_map_elites.v1",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "corpus_sha256": CORPUS_SHA256,
        "args": {
            "models": models,
            "max_gens": args.max_gens,
            "children": args.children,
            "patience": args.patience,
            "temperature": args.temperature,
            "elite_show": args.elite_show,
            "no_llm": args.no_llm,
            "seed": args.seed,
        },
        "axes": {
            "smoothing": list(SMOOTHINGS),
            "n": list(N_VALUES),
            "alpha_bins": [{"name": n, "lo": lo, "hi": hi} for n, lo, hi in ALPHA_BINS],
            "total_cells": TOTAL_CELLS,
        },
        "history": history,
        "archive": archive_json,
        "champion": {
            "name": champion["genome"]["name"],
            "cell": list(cell_of(champion["genome"])),
            "kind": champion["kind"],
            "holdout_ppl": champion["ppl"],
            "genome": champion["genome"],
        },
        "coverage": {
            "filled": len(archive),
            "total": TOTAL_CELLS,
            "ratio": round(len(archive) / TOTAL_CELLS, 4),
        },
    }
    out_path = OUT_DIR / out_name
    out_path.write_text(json.dumps(lineage, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nlineage saved: {out_path}")
    return lineage


def main():
    p = argparse.ArgumentParser(description="AIPL-v4 MAP-Elites autoloop (G4)")
    p.add_argument("--model", default="gemma2:2b")
    p.add_argument("--models", default="gemma2:2b,llama3.2:3b",
                   help="Comma-separated proposer models; children split across them per gen")
    p.add_argument("--max-gens", type=int, default=8)
    p.add_argument("--children", type=int, default=6)
    p.add_argument("--patience", type=int, default=3,
                   help="Stop after this many gens with neither a new cell nor a champion improvement")
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--timeout", type=float, default=180.0)
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--elite-show", type=int, default=6,
                   help="Number of diverse elites shown to the LLM each gen")
    p.add_argument("--no-llm", action="store_true", help="Seed-only sanity run")
    p.add_argument("--out-name", default=None)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    run_loop(args)


if __name__ == "__main__":
    main()
