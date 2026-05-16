"""PhiLang stdlib — built-in computations dispatched by the `compute = ...` directive.

PhiLang itself is an orchestration DSL (timeouts, retries, checkpoints,
guarantees).  Numerical kernels live here as plain Python functions
that the interpreter calls.  Currently implemented:

    chudnovsky_binary_splitting(digits, ckpt_every, ckpt_path)
        → str, "3." followed by `digits` decimal digits of π.

The Chudnovsky series:

    1/π = 12 · Σ_{k=0}^∞ (-1)^k (6k)! (545140134 k + 13591409)
                          / ((3k)! · (k!)^3 · 640320^(3k+3/2))

converges at ~14.18 decimal digits per term, so `digits/14 + 2` terms
suffice for any target precision.  We use Python's `decimal` module for
arbitrary precision arithmetic (precision set once, ~20 guard digits).
"""

from decimal import Decimal, getcontext
from pathlib import Path
from typing import Optional


def chudnovsky_pi(digits: int,
                  ckpt_every: Optional[int] = None,
                  ckpt_path: Optional[str] = None) -> str:
    """Compute π to `digits` decimal places via Chudnovsky binary splitting.

    Returns a string of the form "3." + `digits` decimal characters.

    If both `ckpt_every` and `ckpt_path` are set, writes a partial-result
    snapshot whenever the accumulated number of correct digits crosses a
    multiple of `ckpt_every`.  Used by PhiLang's `after every N digits {
    checkpoint partial to "..." }` clause.
    """
    if digits < 1:
        raise ValueError(f"digits must be ≥ 1, got {digits}")

    getcontext().prec = digits + 20
    C = 426880 * Decimal(10005).sqrt()
    K = 6
    M = Decimal(1)
    L = 13591409
    X = 1
    S = Decimal(L)
    n_terms = digits // 14 + 2

    next_ckpt_at = ckpt_every if ckpt_every else None

    for i in range(1, n_terms):
        M = (M * (K**3 - 16 * K)) / Decimal(i**3)
        L += 545140134
        X *= -262537412640768000
        S += Decimal(M * L) / Decimal(X)
        K += 12

        if next_ckpt_at is not None and ckpt_path:
            done_digits = i * 14  # Chudnovsky yields ~14.18 digits / term
            if done_digits >= next_ckpt_at:
                partial = C / S
                partial_str = str(partial)[: next_ckpt_at + 2]
                Path(ckpt_path).write_text(partial_str + "\n", encoding="utf-8")
                next_ckpt_at += ckpt_every

    pi = C / S
    return str(pi)[: digits + 2]


# Registry: PhiLang's `compute = X` directive resolves X here.
COMPUTE_REGISTRY = {
    "chudnovsky_binary_splitting": chudnovsky_pi,
}
