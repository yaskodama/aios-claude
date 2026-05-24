"""AIPL-v4: LLM-driven candidate proposer for Stage-1 (n-gram).

Replaces the failed `AIPL mock provider` line from RESUME.md. An Ollama-backed
LLM proposes N new n-gram genomes per stage; this driver trains them on the
pinned 9.5KB corpus alongside the hardcoded N1/N2/N3 baselines and picks the
winner from the combined pool via the existing reviewer suite.

Smoke-test scope: Stage-1 only. Other stages are left to evolve.py.

Run:
    .venv/bin/python aipl_v4_evolve.py --llm-candidates 4
    .venv/bin/python aipl_v4_evolve.py --model llama3.2:3b --llm-candidates 6

Disable LLM (= same as original Stage-1 baseline) for sanity:
    .venv/bin/python aipl_v4_evolve.py --no-llm
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from common import CORPUS_SHA256, load_corpus, split_corpus
from candidates.ngram_real import NGram, candidate_N1, candidate_N2, candidate_N3
from reviewers import review_all
from stages import STAGES, COMMON_REPRO


OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OUT_DIR = HERE / "out"


# ---------- generic n-gram runner ----------------------------------------

class NGramWithBackoff:
    """n-th order n-gram that falls back to (n-1) when the context is unseen.

    Generalizes the hardcoded `TrigramWithBackoff` to any n in 1..5.
    """

    def __init__(self, n: int, alpha: float):
        self.n = max(1, n)
        self.alpha = alpha
        self.models = [NGram(k, alpha) for k in range(1, self.n + 1)]

    def train(self, data: bytes) -> None:
        for m in self.models:
            m.train(data)

    def neg_log_prob(self, ctx: tuple, nxt: int) -> float:
        for k in range(self.n, 1, -1):
            m = self.models[k - 1]
            sub_ctx = ctx[-(k - 1):]
            if sub_ctx in m.context_totals:
                return m.neg_log_prob(sub_ctx, nxt)
        return self.models[0].neg_log_prob((), nxt)

    def eval_neg_log_prob_nats(self, data: bytes) -> tuple[float, int]:
        total, count = 0.0, 0
        start = self.n - 1
        for i in range(start, len(data)):
            ctx = tuple(data[i - start: i]) if start > 0 else ()
            total += self.neg_log_prob(ctx, data[i])
            count += 1
        return total, count


def _eval_plain(model: NGram, holdout: bytes) -> tuple[float, int]:
    n = model.n
    total, count = 0.0, 0
    if n == 1:
        for b in holdout:
            total += model.neg_log_prob((), b)
            count += 1
        return total, count
    for i in range(n - 1, len(holdout)):
        ctx = tuple(holdout[i - n + 1: i])
        total += model.neg_log_prob(ctx, holdout[i])
        count += 1
    return total, count


def evaluate_genome(genome: dict, train_bytes: bytes, holdout_bytes: bytes) -> dict:
    """Train + eval any genome whose style is 'plain', 'backoff',
    'kneser_ney', or 'modified_kn'."""
    n = int(genome["n"])
    alpha = float(genome["alpha"])
    style = genome["style"]
    if style == "backoff":
        model = NGramWithBackoff(n, alpha)
        model.train(train_bytes)
        nlp, count = model.eval_neg_log_prob_nats(holdout_bytes)
        params = sum(sum(len(d) for d in sub.counts.values()) for sub in model.models)
    elif style == "kneser_ney":
        from kn_smoothing import KneserNeyNGram
        model = KneserNeyNGram(n, alpha)
        model.train(train_bytes)
        nlp, count = model.eval_neg_log_prob_nats(holdout_bytes)
        params = sum(
            sum(len(d) for d in (model.counts[k] or {}).values())
            for k in range(1, model.n + 1)
        )
    elif style == "modified_kn":
        from kn_smoothing import ModifiedKneserNeyNGram
        model = ModifiedKneserNeyNGram(n, alpha)
        model.train(train_bytes)
        nlp, count = model.eval_neg_log_prob_nats(holdout_bytes)
        params = sum(
            sum(len(d) for d in (model.counts[k] or {}).values())
            for k in range(1, model.n + 1)
        )
    elif style == "kn_ctx":
        from kn_smoothing import ContextConditionalKN
        model = ContextConditionalKN(n, alpha)
        model.train(train_bytes)
        nlp, count = model.eval_neg_log_prob_nats(holdout_bytes)
        params = sum(
            sum(len(d) for d in (model.counts[k] or {}).values())
            for k in range(1, model.n + 1)
        )
    else:
        model = NGram(n, alpha)
        model.train(train_bytes)
        nlp, count = _eval_plain(model, holdout_bytes)
        params = sum(len(d) for d in model.counts.values())
    ppl = math.exp(nlp / count) if count else float("inf")
    return {
        "name": genome["name"],
        "style": f"llm:{style}:n={n}:alpha={alpha:g}",
        "n": n,
        "alpha": alpha,
        "params_observed": params,
        "holdout_ppl": ppl,
    }


# ---------- Ollama proposer ---------------------------------------------

PROMPT_TEMPLATE = """You are proposing variants for a character-level n-gram language model. The corpus is tiny (~9.5KB ASCII text). The existing baseline candidates are:
{existing}

Propose {num} NEW candidates that explore the design space. You may vary:
  - n: integer in {{1, 2, 3, 4, 5}} (1=unigram, 5=quintgram)
  - alpha: float in 0.01..3.0 (smoothing strength)
  - style: ONE OF five smoothing families:
      * "plain"       — Laplace +alpha, single n-gram
      * "backoff"     — Laplace with (n-1) fallback when context unseen
      * "kneser_ney"  — Kneser-Ney continuation smoothing (alpha = discount D, 0.5-0.9 typical)
      * "modified_kn" — Modified Kneser-Ney with 3 discount levels by n-gram COUNT (alpha sets D2)
      * "kn_ctx"      — Context-conditional KN (G2): D varies by CONTEXT count tier
                        (sparse ctx_total<=2 -> 1.3*alpha, medium -> alpha, dense >=11 -> 0.6*alpha).
                        Targets small corpora where most contexts are sparse. Try n in 4-5 and alpha 0.4-0.8.

Tradeoffs:
  - Higher n captures longer dependency but suffers data sparsity on 9.5KB corpus.
  - "backoff" mitigates sparsity at higher n.
  - Kneser-Ney/Modified-KN are known to beat Laplace on small corpora; try them with n in 3-5 and alpha in 0.4-0.9.
  - kn_ctx is a new G2 family expected to beat modified_kn when many contexts have low counts.
  - Small alpha (<0.1) is sharper but risks zero probabilities; large alpha (>1.5) blurs.

Output ONLY a JSON array of exactly {num} objects. NO markdown fences. NO commentary.
Each object MUST have these keys exactly:
  "name"      : short tag starting with "L" (e.g. "L1", "Lkn", "Lmkn", "Lctx")
  "style"     : "plain", "backoff", "kneser_ney", "modified_kn", or "kn_ctx"
  "n"         : integer 1..5
  "alpha"     : number in 0.01..3.0
  "rationale" : one sentence why this variant might do well

Example output:
[{{"name":"Lkn","style":"kneser_ney","n":4,"alpha":0.7,"rationale":"KN with deep context for small corpus"}},{{"name":"L2","style":"backoff","n":3,"alpha":0.2,"rationale":"known winner pattern"}}]"""


def call_ollama(prompt: str, model: str, temperature: float, timeout: float) -> str:
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": 1024},
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("response", "")


def _extract_json_array(raw: str) -> list | None:
    raw = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw, re.S)
    if fenced:
        raw = fenced.group(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[\s*\{.*\}\s*\]", raw, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _validate(c: dict) -> str | None:
    """Return None if valid, else the reason it was rejected."""
    if not isinstance(c, dict):
        return "not a dict"
    name = c.get("name")
    if not (isinstance(name, str) and 1 <= len(name) <= 16 and name[0].upper() == "L"):
        return f"bad name: {name!r}"
    if c.get("style") not in {"plain", "backoff", "kneser_ney", "modified_kn", "kn_ctx"}:
        return f"bad style: {c.get('style')!r}"
    n = c.get("n")
    if not (isinstance(n, int) and 1 <= n <= 5):
        return f"bad n: {n!r}"
    alpha = c.get("alpha")
    if not (isinstance(alpha, (int, float)) and 0.001 <= float(alpha) <= 5.0):
        return f"bad alpha: {alpha!r}"
    return None


def propose_stage1_candidates(
    parent_genomes: list[dict],
    *,
    num: int = 4,
    model: str = "gemma2:2b",
    temperature: float = 0.8,
    max_retries: int = 3,
    timeout: float = 180.0,
) -> tuple[list[dict], dict]:
    """Ask the LLM for N candidates. Returns (validated, telemetry)."""
    existing = "\n".join(
        f"  - {g['name']}: style={g.get('style')}, n={g.get('n')}, alpha={g.get('alpha')}"
        for g in parent_genomes
    )
    prompt = PROMPT_TEMPLATE.format(existing=existing, num=num)

    telemetry = {
        "model": model,
        "temperature": temperature,
        "requested": num,
        "attempts": [],
        "prompt_chars": len(prompt),
    }

    validated: list[dict] = []
    seen_names: set[str] = set()
    for attempt in range(1, max_retries + 1):
        t0 = time.monotonic()
        try:
            raw = call_ollama(prompt, model, temperature, timeout)
        except (urllib.error.URLError, TimeoutError) as exc:
            telemetry["attempts"].append({
                "attempt": attempt, "error": f"transport: {exc}", "elapsed": time.monotonic() - t0,
            })
            continue
        elapsed = time.monotonic() - t0
        parsed = _extract_json_array(raw)
        attempt_log = {
            "attempt": attempt,
            "elapsed": round(elapsed, 2),
            "raw_chars": len(raw),
            "parsed_count": len(parsed) if isinstance(parsed, list) else None,
            "rejections": [],
        }
        if not isinstance(parsed, list):
            attempt_log["error"] = "no JSON array in response"
            telemetry["attempts"].append(attempt_log)
            continue
        for c in parsed:
            reason = _validate(c)
            if reason is not None:
                attempt_log["rejections"].append({"candidate": c, "reason": reason})
                continue
            name = c["name"]
            if name in seen_names:
                attempt_log["rejections"].append({"candidate": c, "reason": f"duplicate name {name}"})
                continue
            validated.append({
                "name": name,
                "style": c["style"],
                "n": int(c["n"]),
                "alpha": float(c["alpha"]),
                "rationale": c.get("rationale", ""),
                "source": "llm",
                "param_class": "32K",
                **{k: COMMON_REPRO[k] for k in COMMON_REPRO},
            })
            seen_names.add(name)
        telemetry["attempts"].append(attempt_log)
        if len(validated) >= num:
            break
    telemetry["validated_count"] = len(validated)
    return validated[:num], telemetry


# ---------- driver ------------------------------------------------------

def hardcoded_baselines(train_bytes: bytes, holdout_bytes: bytes) -> list[dict]:
    """Re-run N1/N2/N3 so they share the exact same holdout bytes as LLM ones."""
    out = []
    for fn in (candidate_N1, candidate_N2, candidate_N3):
        m = fn(train_bytes, holdout_bytes)
        m["source"] = "baseline"
        out.append(m)
    return out


def build_estimate(measured: dict, genome: dict) -> dict:
    return {
        "params": measured["params_observed"],
        "param_class": "32K",
        "param_budget": 64_000,
        "over_budget": measured["params_observed"] > 64_000,
        "expected_holdout_ppl": round(measured["holdout_ppl"], 3),
        "flops_per_token": 2,
        "train_time_min_estimate": 0.05,
        "inference_throughput_factor": 1.0,
        "coherence_violations": [],
        "measurement_kind": "real_ngram_training_on_pinned_corpus",
        "source": measured.get("source", genome.get("source", "baseline")),
    }


def baseline_genome_for(measured: dict) -> dict:
    """Reconstruct the hardcoded baseline's genome dict for reviewer scoring."""
    for stage in STAGES:
        if stage["name"] != "NGramFreq":
            continue
        for cand in stage["candidates"]:
            if cand["name"] == measured["name"]:
                return cand
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="AIPL-v4 Stage-1 LLM-augmented driver")
    parser.add_argument("--model", default="gemma2:2b", help="Ollama model tag")
    parser.add_argument("--llm-candidates", type=int, default=4,
                        help="Number of LLM-proposed candidates to request")
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip LLM call (sanity baseline = original Stage-1)")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--out-name", default=None,
                        help="Lineage filename (default: aipl_v4_stage1_<ts>.json)")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"corpus sha256 = {CORPUS_SHA256}")
    raw = load_corpus()
    train, holdout = split_corpus(raw)
    print(f"corpus: {len(raw)} bytes, train {len(train)}, holdout {len(holdout)}")

    print("\n=== baseline candidates (N1/N2/N3) ===")
    baselines = hardcoded_baselines(train, holdout)
    for m in baselines:
        print(f"  {m['name']:<3} style={m['style']:<28} ppl={m['holdout_ppl']:.4f} params={m['params_observed']:,}")

    proposals: list[dict] = []
    telemetry: dict = {"skipped": True}
    if not args.no_llm:
        print(f"\n=== asking {args.model} for {args.llm_candidates} candidates ===")
        baseline_genomes = [baseline_genome_for(m) for m in baselines]
        proposals, telemetry = propose_stage1_candidates(
            baseline_genomes,
            num=args.llm_candidates,
            model=args.model,
            temperature=args.temperature,
            timeout=args.timeout,
            max_retries=args.max_retries,
        )
        for att in telemetry["attempts"]:
            err = att.get("error")
            print(f"  attempt {att['attempt']}: parsed={att.get('parsed_count')} "
                  f"rejections={len(att.get('rejections', []))} "
                  f"elapsed={att.get('elapsed')}s"
                  + (f" [error: {err}]" if err else ""))
        print(f"  validated: {len(proposals)} / requested {args.llm_candidates}")
        if not proposals:
            print("  WARNING: no valid proposals returned, continuing with baselines only.")

    print("\n=== training LLM-proposed candidates ===")
    llm_measured = []
    for g in proposals:
        t0 = time.monotonic()
        m = evaluate_genome(g, train, holdout)
        m["source"] = "llm"
        m["rationale"] = g.get("rationale", "")
        elapsed = time.monotonic() - t0
        print(f"  {m['name']:<4} style={g['style']:<8} n={g['n']} alpha={g['alpha']:.3g} "
              f"ppl={m['holdout_ppl']:.4f} params={m['params_observed']:,} ({elapsed:.2f}s)")
        llm_measured.append((g, m))

    print("\n=== reviewer scoring ===")
    all_results = []
    for m in baselines:
        g = baseline_genome_for(m)
        est = build_estimate(m, g)
        review = review_all(est, g)
        all_results.append({"genome": g, "measured": m, "estimate": est, "review": review})
    for g, m in llm_measured:
        est = build_estimate(m, g)
        review = review_all(est, g)
        all_results.append({"genome": g, "measured": m, "estimate": est, "review": review})

    for r in sorted(all_results, key=lambda x: -x["review"]["normalized_total"]):
        g, m, rv = r["genome"], r["measured"], r["review"]
        src = m.get("source", "?")
        print(f"  [{src:<8}] {m['name']:<4} ppl={m['holdout_ppl']:.4f}  "
              f"q={rv['quality']['total']}/12 e={rv['efficiency']['total']}/12 "
              f"r={rv['reproducibility']['total']}/10  norm={rv['normalized_total']:.3f}")

    winner = max(all_results, key=lambda r: r["review"]["normalized_total"])
    w_src = winner["measured"].get("source", "?")
    print(f"\nwinner: {winner['measured']['name']} (source={w_src}) "
          f"ppl={winner['measured']['holdout_ppl']:.4f} "
          f"norm={winner['review']['normalized_total']:.3f}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = args.out_name or f"aipl_v4_stage1_{ts}.json"
    lineage = {
        "schema": "aipl_v4_stage1.v1",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "corpus_sha256": CORPUS_SHA256,
        "model": args.model if not args.no_llm else None,
        "llm_candidates_requested": args.llm_candidates if not args.no_llm else 0,
        "llm_telemetry": telemetry,
        "candidates": all_results,
        "winner": {
            "name": winner["measured"]["name"],
            "source": w_src,
            "normalized_total": winner["review"]["normalized_total"],
            "holdout_ppl": winner["measured"]["holdout_ppl"],
        },
    }
    out_path = OUT_DIR / out_name
    out_path.write_text(json.dumps(lineage, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nlineage saved: {out_path}")


if __name__ == "__main__":
    main()
