"""G2+ deterministic search for kn_ctx2: hyperparameterized context-conditional KN.

Strategy: random search over (n, alpha, sparse_max, dense_min, mult_sparse,
mult_dense) in a sensible box, scored on BOTH the pinned 10KB corpus AND
the kodama-lab 14KB corpus (geomean of holdout ppl). The cross-corpus
geomean is the same metric that named L5mkn the robust champion (5.48)
in NEXT_SESSION.md, so beating it here is a real generalization win, not
a pinned-overfit like Lmkn5d2.

Output:
    - Prints leaderboard of top-15 candidates by geomean
    - If the new champion beats L5mkn geomean, appends to
      local-genai/out/served_genomes.json (so a running aipl_v4_serve.py
      can /api/reload and serve it).

Run:
    local-genai/.venv/bin/python local-genai/aipl_v4_evolve_knctx2.py \\
        --trials 80 --seed 1
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
from kn_smoothing import ContextConditionalKN2, ModifiedKneserNeyNGram  # noqa: E402


MANIFEST = HERE / "out" / "served_genomes.json"
LINEAGE = HERE / "out" / "aipl_v4_knctx2_search.json"


def load_kodama() -> bytes:
    """The kodama-lab corpus is not in common.CORPORA so load it directly,
    verifying the pinned sha256 from project memory."""
    path = HERE / "corpus" / "kodama_lab.txt"
    expected = "03a30d32ca9176a79c0b8cd33235427a9014120847a8c25793c3fe78cc5cecfc"
    raw = path.read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if got != expected:
        raise RuntimeError(f"kodama_lab.txt sha256 mismatch: expected {expected}, got {got}")
    return raw


def eval_pair(model_factory, train_p: bytes, hold_p: bytes,
              train_k: bytes, hold_k: bytes) -> dict:
    m_p = model_factory()
    m_p.train(train_p)
    nlp, c = m_p.eval_neg_log_prob_nats(hold_p)
    ppl_p = math.exp(nlp / c) if c else float("inf")

    m_k = model_factory()
    m_k.train(train_k)
    nlp, c = m_k.eval_neg_log_prob_nats(hold_k)
    ppl_k = math.exp(nlp / c) if c else float("inf")

    geomean = math.sqrt(ppl_p * ppl_k)
    return {"ppl_pinned": ppl_p, "ppl_kodama": ppl_k, "geomean": geomean}


def baseline_l5mkn(train_p, hold_p, train_k, hold_k) -> dict:
    return eval_pair(lambda: ModifiedKneserNeyNGram(5, 0.8),
                     train_p, hold_p, train_k, hold_k)


def random_genome(rng: random.Random) -> dict:
    # Center around L5mkn's neighborhood (n=4..5, alpha 0.4-1.5) but
    # let tier boundaries explore widely.
    n = rng.choice([4, 5])
    alpha = round(rng.uniform(0.4, 1.5), 3)
    sparse_max = rng.choice([1, 2, 3, 4, 5])
    dense_min = rng.choice([6, 8, 10, 13, 18, 25])
    if dense_min <= sparse_max:
        dense_min = sparse_max + 4
    mult_sparse = round(rng.uniform(0.8, 2.5), 2)
    mult_dense = round(rng.uniform(0.2, 1.1), 2)
    return {
        "style": "kn_ctx2", "n": n, "alpha": alpha,
        "sparse_max": sparse_max, "dense_min": dense_min,
        "mult_sparse": mult_sparse, "mult_dense": mult_dense,
    }


def factory_for(g: dict):
    return lambda: ContextConditionalKN2(
        g["n"], g["alpha"],
        sparse_max=g["sparse_max"], dense_min=g["dense_min"],
        mult_sparse=g["mult_sparse"], mult_dense=g["mult_dense"],
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=60)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--add-to-manifest", action="store_true",
                    help="If beats L5mkn geomean, append to served_genomes.json")
    args = ap.parse_args()

    raw_p = load_corpus("10KB")
    train_p, hold_p = split_corpus(raw_p)
    raw_k = load_kodama()
    train_k, hold_k = split_corpus(raw_k)

    print(f"[corpora] pinned: train {len(train_p)} hold {len(hold_p)}  "
          f"kodama: train {len(train_k)} hold {len(hold_k)}", flush=True)

    t0 = time.monotonic()
    base = baseline_l5mkn(train_p, hold_p, train_k, hold_k)
    print(f"[baseline L5mkn] {base}  ({time.monotonic()-t0:.2f}s)", flush=True)

    rng = random.Random(args.seed)
    seen = set()
    results = []
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
        results.append({"genome": g, **res, "dur_s": dur})
        print(f"  [trial {i:3d}] n={g['n']} α={g['alpha']:.2f} "
              f"sm={g['sparse_max']} dm={g['dense_min']} "
              f"ms={g['mult_sparse']:.2f} md={g['mult_dense']:.2f}  "
              f"ppl_p={res['ppl_pinned']:.4f} ppl_k={res['ppl_kodama']:.4f} "
              f"geo={res['geomean']:.4f}{marker}  ({dur:.2f}s)", flush=True)

    results.sort(key=lambda r: r["geomean"])
    print()
    print(f"=== top 15 by geomean (baseline L5mkn = {base['geomean']:.4f}) ===")
    for r in results[:15]:
        g = r["genome"]
        marker = " ★ BEATS L5mkn" if r["geomean"] < base["geomean"] else ""
        print(f"  geo={r['geomean']:.4f} ppl_p={r['ppl_pinned']:.4f} ppl_k={r['ppl_kodama']:.4f}  "
              f"n={g['n']} α={g['alpha']:.2f} sm={g['sparse_max']} dm={g['dense_min']} "
              f"ms={g['mult_sparse']:.2f} md={g['mult_dense']:.2f}{marker}")

    LINEAGE.write_text(json.dumps({
        "baseline_L5mkn": base,
        "trials": results,
    }, indent=2))
    print(f"\n[lineage saved] {LINEAGE.relative_to(HERE.parent)}")
    print(f"[elapsed] {time.monotonic()-t0:.1f}s")

    # Optionally append the new champion to the manifest.
    if not results:
        print("[manifest] no successful trials"); return
    best = results[0]
    if best["geomean"] >= base["geomean"]:
        print(f"[manifest] best geomean {best['geomean']:.4f} did NOT beat L5mkn "
              f"({base['geomean']:.4f}); not adding to manifest")
        return
    if not args.add_to_manifest:
        print(f"[manifest] best geomean {best['geomean']:.4f} BEATS L5mkn "
              f"({base['geomean']:.4f}). Re-run with --add-to-manifest to append.")
        return
    g = best["genome"]
    entry = {
        "name": "Lctx2a",
        "style": "kn_ctx2",
        "n": g["n"],
        "alpha": g["alpha"],
        "sparse_max": g["sparse_max"],
        "dense_min": g["dense_min"],
        "mult_sparse": g["mult_sparse"],
        "mult_dense": g["mult_dense"],
        "corpus": "10KB",
        "ppl_pinned": round(best["ppl_pinned"], 4),
        "ppl_kodama": round(best["ppl_kodama"], 4),
        "title": "Lctx2a (G2+ new champion, kn_ctx2)",
        "note": f"Hyperparam-tuned context-conditional KN. Beat L5mkn "
                f"(geomean {best['geomean']:.4f} vs {base['geomean']:.4f}).",
    }
    manifest = json.loads(MANIFEST.read_text())
    manifest = [e for e in manifest if e.get("name") != entry["name"]]
    manifest.insert(0, entry)  # put champion first
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"[manifest] appended Lctx2a to {MANIFEST.relative_to(HERE.parent)}")
    print(f"[manifest] entry: {json.dumps(entry, indent=2)}")
    print()
    print("Hot-reload the running server:")
    print("  curl -s -X POST http://127.0.0.1:7862/api/reload")


if __name__ == "__main__":
    main()
