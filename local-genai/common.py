"""Shared utilities: corpus loader, byte tokenizer, perplexity helpers."""

import hashlib
import math
import os
import random
from pathlib import Path

HERE = Path(__file__).parent

CORPORA = {
    "10KB": (
        HERE / "corpus" / "tiny_corpus.txt",
        "9614a5a4d3f6474f004c982e8a2e89f8bdbda367fe55edc6d9d52d72cc48593e",
    ),
    "100KB": (
        HERE / "corpus" / "tinyshake_100KB.txt",
        "caad989adf87f2482e346c9a77d1fb03c6c033aa8689e2e97aee2de90b0f8839",
    ),
    "1MB": (
        HERE / "corpus" / "tinyshake_1MB.txt",
        "86c4e6aa9db7c042ec79f339dcb96d42b0075e16b8fc2e86bf0ca57e2dc565ed",
    ),
    "10MB": (
        HERE / "corpus" / "tinyshake_10MB.txt",
        "76bd8e4cd4be37ee1853452b115de6889863cb431bcc6a5244d7632055794bff",
    ),
    "60MB": (
        HERE / "corpus" / "tinyshake_60MB.txt",
        "48808768d4617016cc3f3b139c13fc30cc05c8003f414e6b2117f8e8ca2edd3c",
    ),
    "100MB_multi": (
        HERE / "corpus" / "tinyshake_100MB_multi.txt",
        "51e9c3d5d5d420ef7518e47eb16f62b72a679a4ca1c0f909effc1ae10166d7cb",
    ),
    "120MB_jp_heavy": (
        HERE / "corpus" / "tinyshake_120MB_jp_heavy.txt",
        "91a57e5cbd9b6f4cc08b4529ac0298290c9eb8b5398b712c2bb1f4d0584565e8",
    ),
}

CORPUS_PATH = CORPORA["10KB"][0]
CORPUS_SHA256 = CORPORA["10KB"][1]

SEED = 42


def load_corpus(size_class: str = "10KB") -> bytes:
    path, expected_hash = CORPORA[size_class]
    raw = path.read_bytes()
    h = hashlib.sha256(raw).hexdigest()
    if h != expected_hash:
        raise RuntimeError(f"corpus {size_class} hash mismatch: expected {expected_hash}, got {h}")
    return raw


def split_corpus(raw: bytes, train_frac: float = 0.95) -> tuple[bytes, bytes]:
    cut = int(len(raw) * train_frac)
    return raw[:cut], raw[cut:]


def make_rng() -> random.Random:
    return random.Random(SEED)


def perplexity_from_neg_log_prob_nats(total_neg_log_prob: float, count: int) -> float:
    if count == 0:
        return float("inf")
    return math.exp(total_neg_log_prob / count)


def fair_eval_neg_log_prob_nats(model, data: bytes, vocab: int = 256) -> tuple[float, int]:
    """Per-context renormalized held-out neg-log-prob in nats.

    Many of our n-gram smoothers do NOT self-normalize: the approximate
    Modified-KN backoff weight and the Laplace+backoff fallback leave
    Σ_w P(w|ctx) ≠ 1, which silently inflates or deflates the raw
    `eval_neg_log_prob_nats` score and makes cross-model ppl comparisons
    unfair. This evaluator divides each P(next|ctx) by Σ_w P(w|ctx) so
    every model is scored as a proper distribution.

    Works for any model exposing `.n` and `neg_log_prob(ctx, nxt)` —
    i.e. NGram, NGramWithBackoff, and every KN-family class. For models
    that already self-normalize (plain Laplace) this returns the same
    value as the raw evaluator (up to float error).

    Z is cached per context, so cost is O(vocab × distinct_contexts).
    """
    n = getattr(model, "n", 1)
    start = max(0, n - 1)
    total, count = 0.0, 0
    z_cache: dict = {}
    for i in range(start, len(data)):
        ctx = tuple(data[i - start:i]) if start > 0 else ()
        Z = z_cache.get(ctx)
        if Z is None:
            Z = 0.0
            for w in range(vocab):
                Z += math.exp(-model.neg_log_prob(ctx, w))
            z_cache[ctx] = Z
        p = math.exp(-model.neg_log_prob(ctx, data[i]))
        p = (p / Z) if Z > 0 else 1e-12
        if p <= 0:
            p = 1e-12
        total += -math.log(p)
        count += 1
    return total, count
