"""Re-evaluate every served genome under BOTH the raw and the fair
(per-context renormalized) metric, on the pinned 10KB corpus and the
kodama-lab corpus. Prints a leaderboard sorted by fair cross-corpus
geomean and writes out/reeval_fair.json.

The fair metric divides each P(next|ctx) by Σ_w P(w|ctx), so models that
don't self-normalize (approximate Modified-KN, Laplace+backoff) are scored
as proper distributions and can be compared apples-to-apples.

Run:
    local-genai/.venv/bin/python local-genai/reeval_fair.py
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from common import (load_corpus, split_corpus,  # noqa: E402
                    perplexity_from_neg_log_prob_nats,
                    fair_eval_neg_log_prob_nats)
from aipl_v4_serve import build_model  # noqa: E402
from kn_smoothing import (ModifiedKneserNeyExactNGram,  # noqa: E402
                          KnCtxModExact)

MANIFEST = HERE / "out" / "served_genomes.json"
OUT = HERE / "out" / "reeval_fair.json"


def load_kodama() -> bytes:
    path = HERE / "corpus" / "kodama_lab.txt"
    expected = "03a30d32ca9176a79c0b8cd33235427a9014120847a8c25793c3fe78cc5cecfc"
    raw = path.read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if got != expected:
        raise RuntimeError(f"kodama_lab.txt sha256 mismatch")
    return raw


def model_from_entry(entry: dict):
    extra = {k: entry[k] for k in
             ("sparse_max", "dense_min", "mult_sparse", "mult_dense",
              "mult_mid", "gamma_scale") if k in entry}
    return build_model(entry["style"], int(entry["n"]),
                       float(entry["alpha"]), **extra)


def eval_one(factory, train: bytes, hold: bytes) -> tuple[float, float]:
    m = factory()
    m.train(train)
    nlp, c = m.eval_neg_log_prob_nats(hold)
    raw = perplexity_from_neg_log_prob_nats(nlp, c)
    m2 = factory()
    m2.train(train)
    nlp2, c2 = fair_eval_neg_log_prob_nats(m2, hold)
    fair = perplexity_from_neg_log_prob_nats(nlp2, c2)
    return raw, fair


def main():
    train_p, hold_p = split_corpus(load_corpus("10KB"))
    train_k, hold_k = split_corpus(load_kodama())

    manifest = json.loads(MANIFEST.read_text())

    # Reference rows: the exact (self-normalizing) variants, not in manifest.
    extra_rows = [
        {"name": "mkn_exact", "style": "kn_ctx_mod_exact", "n": 5, "alpha": 0.8,
         "sparse_max": 2, "dense_min": 11, "mult_sparse": 1.0, "mult_dense": 1.0,
         "mult_mid": 1.0, "title": "mkn_exact (proper MKN, ref)"},
        {"name": "Lkcm3_exact", "style": "kn_ctx_mod_exact", "n": 5, "alpha": 1.0,
         "sparse_max": 6, "dense_min": 20, "mult_sparse": 0.82, "mult_dense": 0.66,
         "mult_mid": 0.95, "title": "Lkcm3-exact (proper, ref)"},
    ]
    rows = manifest + extra_rows

    results = []
    t0 = time.monotonic()
    for entry in rows:
        name = entry["name"]
        t1 = time.monotonic()
        factory = lambda e=entry: model_from_entry(e)
        rawp, fairp = eval_one(factory, train_p, hold_p)
        rawk, fairk = eval_one(factory, train_k, hold_k)
        raw_geo = math.sqrt(rawp * rawk)
        fair_geo = math.sqrt(fairp * fairk)
        results.append({
            "name": name, "style": entry["style"],
            "raw_pinned": rawp, "raw_kodama": rawk, "raw_geomean": raw_geo,
            "fair_pinned": fairp, "fair_kodama": fairk, "fair_geomean": fair_geo,
            "dur_s": time.monotonic() - t1,
        })
        print(f"  evaluated {name:12s}  raw_geo={raw_geo:.4f}  fair_geo={fair_geo:.4f}  "
              f"({time.monotonic()-t1:.1f}s)", flush=True)

    results.sort(key=lambda r: r["fair_geomean"])

    print()
    print("=== leaderboard by FAIR cross-corpus geomean ===")
    hdr = (f"{'rank':>4}  {'genome':12s} {'style':14s}  "
           f"{'raw_pin':>8} {'raw_kod':>8} {'raw_geo':>8} | "
           f"{'fair_pin':>8} {'fair_kod':>8} {'fair_geo':>8}")
    print(hdr)
    print("-" * len(hdr))
    for rank, r in enumerate(results, 1):
        print(f"{rank:>4}  {r['name']:12s} {r['style']:14s}  "
              f"{r['raw_pinned']:8.4f} {r['raw_kodama']:8.4f} {r['raw_geomean']:8.4f} | "
              f"{r['fair_pinned']:8.4f} {r['fair_kodama']:8.4f} {r['fair_geomean']:8.4f}")

    # Highlight ranking divergence between raw and fair.
    raw_order = [r["name"] for r in sorted(results, key=lambda r: r["raw_geomean"])]
    fair_order = [r["name"] for r in results]
    print()
    print(f"raw  champion: {raw_order[0]}")
    print(f"fair champion: {fair_order[0]}")

    OUT.write_text(json.dumps({"results": results,
                                "raw_order": raw_order,
                                "fair_order": fair_order}, indent=2))
    print(f"\n[saved] {OUT.relative_to(HERE.parent)}   [elapsed] {time.monotonic()-t0:.1f}s")


if __name__ == "__main__":
    main()
