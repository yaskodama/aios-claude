"""kn_ctx_mod search: MKN count-tier × kn_ctx context-tier orthogonal hybrid.

Same cross-corpus geomean evaluation as aipl_v4_evolve_knctx2.py. Strategy:

- Anchor on L5mkn neighborhood (n=5, alpha in [0.6, 1.0]) — the regime
  that already wins on count-tier alone.
- Vary only the context-tier multipliers and tier boundaries, looking for
  a non-trivial multiplier combo that beats the "do nothing" baseline
  (mult_sparse=mult_dense=1.0, which reduces exactly to MKN).
- Include a few hand-picked candidates that test specific hypotheses:
    * "trust dense" — mult_dense in [0.3, 0.6], mult_sparse = 1.0
    * "discount sparse" — mult_sparse in [1.3, 2.0], mult_dense = 1.0
    * symmetric — both moved together
    * narrow sparse band (sparse_max=1) vs wider (sparse_max=4)

If best beats L5mkn geomean (5.4803), write entry "Lkcm" to
served_genomes.json (champion-first), so a hot-reload picks it up.

Run:
    local-genai/.venv/bin/python local-genai/aipl_v4_evolve_knctxmod.py \\
        --trials 120 --seed 1 --add-to-manifest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from common import load_corpus, split_corpus  # noqa: E402
from kn_smoothing import KnCtxMod, ModifiedKneserNeyNGram  # noqa: E402


MANIFEST = HERE / "out" / "served_genomes.json"
LINEAGE = HERE / "out" / "aipl_v4_knctxmod_search.json"

# Champions used as search baselines.
LKCM_PARAMS = {"n": 5, "alpha": 0.95, "sparse_max": 3, "dense_min": 13,
                "mult_sparse": 0.88, "mult_dense": 0.80, "mult_mid": 1.0}
# grid2 winner — baseline for --mode grid3 (boundary-push grid).
LKCM2_PARAMS = {"n": 5, "alpha": 1.00, "sparse_max": 4, "dense_min": 16,
                 "mult_sparse": 0.80, "mult_dense": 0.70, "mult_mid": 0.95}


def load_kodama() -> bytes:
    path = HERE / "corpus" / "kodama_lab.txt"
    expected = "03a30d32ca9176a79c0b8cd33235427a9014120847a8c25793c3fe78cc5cecfc"
    raw = path.read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if got != expected:
        raise RuntimeError(f"kodama_lab.txt sha256 mismatch: expected {expected}, got {got}")
    return raw


def eval_pair(factory, train_p, hold_p, train_k, hold_k) -> dict:
    m_p = factory()
    m_p.train(train_p)
    nlp, c = m_p.eval_neg_log_prob_nats(hold_p)
    ppl_p = math.exp(nlp / c) if c else float("inf")
    m_k = factory()
    m_k.train(train_k)
    nlp, c = m_k.eval_neg_log_prob_nats(hold_k)
    ppl_k = math.exp(nlp / c) if c else float("inf")
    geo = math.sqrt(ppl_p * ppl_k)
    return {"ppl_pinned": ppl_p, "ppl_kodama": ppl_k, "geomean": geo}


def factory_for(g: dict):
    return lambda: KnCtxMod(
        g["n"], g["alpha"],
        sparse_max=g["sparse_max"], dense_min=g["dense_min"],
        mult_sparse=g["mult_sparse"], mult_dense=g["mult_dense"],
        mult_mid=g.get("mult_mid", 1.0),
    )


def random_genome(rng: random.Random) -> dict:
    n = rng.choice([4, 5, 5, 5])  # bias toward n=5 (known winner)
    alpha = round(rng.uniform(0.6, 1.0), 3)
    sparse_max = rng.choice([1, 2, 3, 4])
    dense_min = rng.choice([6, 8, 10, 13, 18])
    if dense_min <= sparse_max:
        dense_min = sparse_max + 4
    mult_sparse = round(rng.uniform(0.7, 2.2), 2)
    mult_dense = round(rng.uniform(0.3, 1.3), 2)
    return {
        "style": "kn_ctx_mod", "n": n, "alpha": alpha,
        "sparse_max": sparse_max, "dense_min": dense_min,
        "mult_sparse": mult_sparse, "mult_dense": mult_dense,
    }


def hand_picked_genomes() -> list[dict]:
    """Genomes that test specific hypotheses about which context regime
    benefits from extra/reduced discounting."""
    cases = []
    base = {"style": "kn_ctx_mod", "n": 5, "alpha": 0.8,
            "sparse_max": 2, "dense_min": 11}
    # Sanity: degenerate (must equal L5mkn)
    cases.append({**base, "mult_sparse": 1.0, "mult_dense": 1.0,
                  "_label": "degenerate (= L5mkn)"})
    # Trust dense ctx (reduce its discount)
    for md in (0.3, 0.5, 0.7):
        cases.append({**base, "mult_sparse": 1.0, "mult_dense": md,
                      "_label": f"trust dense md={md}"})
    # Discount sparse ctx more aggressively
    for ms in (1.3, 1.6, 2.0):
        cases.append({**base, "mult_sparse": ms, "mult_dense": 1.0,
                      "_label": f"discount sparse ms={ms}"})
    # Both moved together (kn_ctx2 prior preset)
    cases.append({**base, "mult_sparse": 1.3, "mult_dense": 0.6,
                  "_label": "kn_ctx2 prior preset"})
    # Narrow sparse band, very small mult_dense
    cases.append({**base, "sparse_max": 1, "dense_min": 13,
                  "mult_sparse": 0.87, "mult_dense": 0.83,
                  "_label": "Lctx2a-coords (kn_ctx2 best)"})
    # Asymmetric near-degenerate: only slight tweaks
    cases.append({**base, "mult_sparse": 1.1, "mult_dense": 0.9,
                  "_label": "mild asymmetric"})
    cases.append({**base, "mult_sparse": 0.9, "mult_dense": 1.1,
                  "_label": "inverted mild asymmetric"})
    # Wider sparse band
    cases.append({**base, "sparse_max": 4, "dense_min": 15,
                  "mult_sparse": 1.5, "mult_dense": 0.5,
                  "_label": "wider sparse band"})
    return cases


def grid_genomes():
    """Tight grid centered on the L5mkn neighborhood + best random hit
    from the 120-trial scan (sm=1, dm=10, ms=0.88, md=1.06 was top random).
    Used for the first kn_ctx_mod sweep (no mult_mid axis)."""
    alphas = [0.65, 0.70, 0.75, 0.78, 0.80, 0.82, 0.85, 0.90, 0.95, 1.00]
    sms = [1, 2, 3]
    dms = [8, 10, 13]
    mss = [0.80, 0.88, 0.95, 1.00, 1.05, 1.12, 1.20]
    mds = [0.80, 0.90, 1.00, 1.10, 1.20]
    for a in alphas:
        for sm in sms:
            for dm in dms:
                if dm <= sm:
                    continue
                for ms in mss:
                    for md in mds:
                        yield {"style": "kn_ctx_mod", "n": 5, "alpha": a,
                               "sparse_max": sm, "dense_min": dm,
                               "mult_sparse": ms, "mult_dense": md}


def grid2_genomes():
    """Lkcm-neighborhood grid that adds mult_mid as a search axis.

    Lkcm = (α=0.95, sm=3, dm=13, ms=0.88, md=0.80, mid=1.0) → geomean 5.4287.
    Vary all six axes locally; mid is the new degree of freedom."""
    alphas = [0.85, 0.90, 0.93, 0.95, 0.98, 1.00, 1.05]
    sms = [2, 3, 4]
    dms = [10, 13, 16]
    mss = [0.80, 0.85, 0.88, 0.92, 0.95]
    mds = [0.70, 0.75, 0.80, 0.85, 0.90]
    mids = [0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15]
    for a in alphas:
        for sm in sms:
            for dm in dms:
                if dm <= sm:
                    continue
                for ms in mss:
                    for md in mds:
                        for mid in mids:
                            yield {"style": "kn_ctx_mod", "n": 5, "alpha": a,
                                   "sparse_max": sm, "dense_min": dm,
                                   "mult_sparse": ms, "mult_dense": md,
                                   "mult_mid": mid}


def grid3_genomes():
    """Boundary-push grid: Lkcm2 sat on every grid edge (sm=4, dm=16,
    ms=0.80, md=0.70 were all extremes). Expand outward on each axis.
    α is pushed past 1.0 to probe whether moving D1 (the only unsaturated
    discount above α=1.0) still helps."""
    alphas = [0.95, 1.00, 1.10, 1.25, 1.50]
    sms = [4, 5, 6]
    dms = [16, 20, 25]
    mss = [0.60, 0.68, 0.75, 0.82]
    mds = [0.50, 0.58, 0.66, 0.74]
    mids = [0.80, 0.88, 0.95, 1.02]
    for a in alphas:
        for sm in sms:
            for dm in dms:
                if dm <= sm:
                    continue
                for ms in mss:
                    for md in mds:
                        for mid in mids:
                            yield {"style": "kn_ctx_mod", "n": 5, "alpha": a,
                                   "sparse_max": sm, "dense_min": dm,
                                   "mult_sparse": ms, "mult_dense": md,
                                   "mult_mid": mid}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=120)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--mode", choices=["random", "grid", "grid2", "grid3"], default="random")
    ap.add_argument("--add-to-manifest", action="store_true")
    args = ap.parse_args()

    raw_p = load_corpus("10KB")
    train_p, hold_p = split_corpus(raw_p)
    raw_k = load_kodama()
    train_k, hold_k = split_corpus(raw_k)
    print(f"[corpora] pinned: train {len(train_p)} hold {len(hold_p)}  "
          f"kodama: train {len(train_k)} hold {len(hold_k)}", flush=True)

    t0 = time.monotonic()
    if args.mode == "grid2":
        base = eval_pair(factory_for({**LKCM_PARAMS, "style": "kn_ctx_mod"}),
                          train_p, hold_p, train_k, hold_k)
        base_name = "Lkcm"
    elif args.mode == "grid3":
        base = eval_pair(factory_for({**LKCM2_PARAMS, "style": "kn_ctx_mod"}),
                          train_p, hold_p, train_k, hold_k)
        base_name = "Lkcm2"
    else:
        base = eval_pair(lambda: ModifiedKneserNeyNGram(5, 0.8),
                          train_p, hold_p, train_k, hold_k)
        base_name = "L5mkn"
    print(f"[baseline {base_name}] {base}  ({time.monotonic()-t0:.2f}s)", flush=True)

    # Hand-picked first (each labeled) so we can verify the degenerate case.
    results = []
    if args.mode in ("grid2", "grid3"):
        # Skip hand-picked — go straight to the grid sweep.
        hand = []
    else:
        hand = list(hand_picked_genomes())
    print("\n=== hand-picked ===" if hand else "")
    for g in hand:
        label = g.pop("_label")
        t1 = time.monotonic()
        res = eval_pair(factory_for(g), train_p, hold_p, train_k, hold_k)
        dur = time.monotonic() - t1
        marker = " ★" if res["geomean"] < base["geomean"] else ""
        results.append({"genome": g, "label": label, **res, "dur_s": dur})
        print(f"  [{label:40s}] "
              f"sm={g['sparse_max']} dm={g['dense_min']} "
              f"ms={g['mult_sparse']:.2f} md={g['mult_dense']:.2f}  "
              f"ppl_p={res['ppl_pinned']:.4f} ppl_k={res['ppl_kodama']:.4f} "
              f"geo={res['geomean']:.4f}{marker}  ({dur:.2f}s)", flush=True)

    if args.mode in ("grid", "grid2", "grid3"):
        grid_fn = {"grid": grid_genomes, "grid2": grid2_genomes,
                   "grid3": grid3_genomes}[args.mode]
        gs = list(grid_fn())
        print(f"\n=== {args.mode} ({len(gs)} cells) ===", flush=True)
        wins = 0
        for i, g in enumerate(gs):
            try:
                res = eval_pair(factory_for(g), train_p, hold_p, train_k, hold_k)
            except Exception as e:
                print(f"  [cell {i:4d}] error: {e}"); continue
            results.append({"genome": g, "label": args.mode, **res, "dur_s": 0.0})
            if res["geomean"] < base["geomean"]:
                wins += 1
                mid_str = f" mid={g.get('mult_mid', 1.0):.2f}" if args.mode in ("grid2", "grid3") else ""
                print(f"  ★ [cell {i:4d}] n={g['n']} α={g['alpha']:.2f} "
                      f"sm={g['sparse_max']} dm={g['dense_min']} "
                      f"ms={g['mult_sparse']:.2f} md={g['mult_dense']:.2f}{mid_str}  "
                      f"ppl_p={res['ppl_pinned']:.4f} ppl_k={res['ppl_kodama']:.4f} "
                      f"geo={res['geomean']:.4f}  BEATS {base_name}", flush=True)
        print(f"[{args.mode}] {wins}/{len(gs)} cells beat {base_name}", flush=True)
    else:
        print(f"\n=== random ({args.trials} trials, seed={args.seed}) ===")
        rng = random.Random(args.seed)
        seen = set()
        for i in range(args.trials):
            g = random_genome(rng)
            key = (g["n"], g["alpha"], g["sparse_max"], g["dense_min"],
                   g["mult_sparse"], g["mult_dense"])
            if key in seen:
                continue
            seen.add(key)
            t1 = time.monotonic()
            try:
                res = eval_pair(factory_for(g), train_p, hold_p, train_k, hold_k)
            except Exception as e:
                print(f"  [trial {i:3d}] {g}  -> error: {e}", flush=True)
                continue
            dur = time.monotonic() - t1
            marker = " ★" if res["geomean"] < base["geomean"] else ""
            results.append({"genome": g, "label": "random", **res, "dur_s": dur})
            if (i < 20) or marker or (i % 10 == 0):
                print(f"  [trial {i:3d}] n={g['n']} α={g['alpha']:.2f} "
                      f"sm={g['sparse_max']} dm={g['dense_min']} "
                      f"ms={g['mult_sparse']:.2f} md={g['mult_dense']:.2f}  "
                      f"ppl_p={res['ppl_pinned']:.4f} ppl_k={res['ppl_kodama']:.4f} "
                      f"geo={res['geomean']:.4f}{marker}  ({dur:.2f}s)", flush=True)

    results.sort(key=lambda r: r["geomean"])
    print()
    print(f"=== top 15 by geomean (baseline {base_name} = {base['geomean']:.4f}) ===")
    for r in results[:15]:
        g = r["genome"]
        marker = f" ★ BEATS {base_name}" if r["geomean"] < base["geomean"] else ""
        mid_str = f" mid={g.get('mult_mid', 1.0):.2f}" if "mult_mid" in g else ""
        print(f"  geo={r['geomean']:.4f} ppl_p={r['ppl_pinned']:.4f} "
              f"ppl_k={r['ppl_kodama']:.4f}  "
              f"n={g['n']} α={g['alpha']:.2f} sm={g['sparse_max']} dm={g['dense_min']} "
              f"ms={g['mult_sparse']:.2f} md={g['mult_dense']:.2f}{mid_str}  "
              f"[{r['label']}]{marker}")

    LINEAGE.write_text(json.dumps({
        "baseline_L5mkn": base,
        "trials": results,
    }, indent=2))
    print(f"\n[lineage saved] {LINEAGE.relative_to(HERE.parent)}")
    print(f"[elapsed] {time.monotonic()-t0:.1f}s")

    if not results:
        return
    best = results[0]
    if best["geomean"] >= base["geomean"]:
        print(f"[manifest] best geomean {best['geomean']:.4f} did NOT beat {base_name} "
              f"({base['geomean']:.4f}); not adding")
        return
    if not args.add_to_manifest:
        print(f"[manifest] best geomean {best['geomean']:.4f} BEATS {base_name} "
              f"({base['geomean']:.4f}). Re-run with --add-to-manifest")
        return
    g = best["genome"]
    entry_name = {"grid3": "Lkcm3", "grid2": "Lkcm2"}.get(args.mode, "Lkcm")
    title_suffix = ", mid free" if args.mode in ("grid2", "grid3") else ""
    entry = {
        "name": entry_name,
        "style": "kn_ctx_mod",
        "n": g["n"],
        "alpha": g["alpha"],
        "sparse_max": g["sparse_max"],
        "dense_min": g["dense_min"],
        "mult_sparse": g["mult_sparse"],
        "mult_dense": g["mult_dense"],
        "mult_mid": g.get("mult_mid", 1.0),
        "corpus": "10KB",
        "ppl_pinned": round(best["ppl_pinned"], 4),
        "ppl_kodama": round(best["ppl_kodama"], 4),
        "title": f"{entry_name} (NEW champion, kn_ctx_mod = MKN × kn_ctx{title_suffix})",
        "note": f"Orthogonal hybrid (count-tier × context-tier{title_suffix}). "
                f"Beat {base_name} (geomean {best['geomean']:.4f} vs {base['geomean']:.4f}, "
                f"-{(1 - best['geomean']/base['geomean'])*100:.2f}%).",
    }
    manifest = json.loads(MANIFEST.read_text())
    manifest = [e for e in manifest if e.get("name") != entry["name"]]
    manifest.insert(0, entry)
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"[manifest] appended {entry['name']} to {MANIFEST.relative_to(HERE.parent)}")
    print(f"[manifest] entry: {json.dumps(entry, indent=2)}")
    print()
    print("Restart the server to pick up the new style "
          "(reload alone is not enough on first deploy of kn_ctx_mod):")
    print("  pkill -f aipl_v4_serve.py")
    print("  nohup local-genai/.venv/bin/python local-genai/aipl_v4_serve.py "
          "--port 7862 > /tmp/aipl_v4_serve.log 2>&1 &")


if __name__ == "__main__":
    main()
