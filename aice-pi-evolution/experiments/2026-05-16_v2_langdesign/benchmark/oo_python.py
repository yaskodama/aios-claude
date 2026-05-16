#!/usr/bin/env python3
"""oo_python.py — π to N decimal digits via Chudnovsky binary splitting,
                  in OO Python (Python 3.14).

Idiomatic object-oriented: encapsulate the partial-sum state in a
`PQT` value-object (immutable; combine() returns a new instance),
and the overall computation in a `ChudnovskyPi` calculator class
that holds configuration (digits, precision) and exposes a single
`compute() -> str` method.  Demonstrates Python's class system,
operator-free decimal arithmetic via mpmath-style `Decimal`, and
the standard `time.perf_counter()` timer.

Run:  python3 oo_python.py            # default 10000
      python3 oo_python.py 1000
"""
from __future__ import annotations
import sys
import time
from dataclasses import dataclass
from decimal import Decimal, getcontext


@dataclass(frozen=True)
class PQT:
    """Immutable triple from Chudnovsky binary splitting."""
    p: int
    q: int
    t: int

    def combine(self, other: "PQT") -> "PQT":
        return PQT(
            p=self.p * other.p,
            q=self.q * other.q,
            t=self.t * other.q + self.p * other.t,
        )


class ChudnovskyPi:
    """π calculator using Chudnovsky's series with binary splitting.

    Construction takes the target digit count.  Internal precision is
    set automatically to `digits + guard`.
    """

    A     = 13591409
    B     = 545140134
    C3_24 = 10_939_058_860_032_000   # 640320^3 / 24

    def __init__(self, digits: int, guard: int = 20) -> None:
        self.digits = digits
        self.n_terms = digits // 14 + 2
        self.precision = digits + guard

    def _leaf(self, k: int) -> PQT:
        if k == 0:
            return PQT(p=1, q=1, t=self.A)
        p = -(6 * k - 5) * (2 * k - 1) * (6 * k - 1)
        q = k * k * k * self.C3_24
        t = p * (self.A + self.B * k)
        return PQT(p=p, q=q, t=t)

    def _bsplit(self, a: int, b: int) -> PQT:
        if b - a == 1:
            return self._leaf(a)
        m = (a + b) // 2
        left  = self._bsplit(a, m)
        right = self._bsplit(m, b)
        return left.combine(right)

    def compute(self) -> str:
        getcontext().prec = self.precision
        root = self._bsplit(0, self.n_terms)
        # S = T / Q;  π = 426880·√10005 / S
        sqrt10005 = Decimal(10005).sqrt()
        pi = Decimal(426880) * sqrt10005 * Decimal(root.q) / Decimal(root.t)
        # render as "3." + `digits` decimal characters
        s = format(pi, f".{self.digits}f")
        return s


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
    sys.setrecursionlimit(100_000)

    calc = ChudnovskyPi(digits=n)
    t0 = time.perf_counter()
    s = calc.compute()
    t1 = time.perf_counter()
    print(s)
    print(f"elapsed_ms={(t1 - t0) * 1000:.3f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
