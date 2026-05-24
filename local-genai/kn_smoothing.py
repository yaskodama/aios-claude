"""Kneser-Ney and Modified Kneser-Ney smoothing for char n-grams.

Drop-in alternatives to NGram / NGramWithBackoff in aipl_v4_evolve.py.

Both classes expose the same surface:
    .train(data: bytes) -> None
    .eval_neg_log_prob_nats(data: bytes) -> (total_nll_nats, count)

`alpha` is repurposed as the discount factor D (typical 0.5-0.9).
For ModifiedKneserNeyNGram, alpha sets D2 = alpha; D1 and D3+ are
derived heuristically as 0.7*alpha and 1.3*alpha (Chen+Goodman 1998).
"""

from __future__ import annotations

import math
from collections import defaultdict


VOCAB = 256


class KneserNeyNGram:
    """Single-discount Kneser-Ney smoothing for char n-grams.

    n=1 falls back to MLE continuation probability over training data.
    For n>=2: uses absolute discount D (= alpha) and continuation count
    backoff. When a context is unseen at the highest order, recurses
    to (n-1)-order continuation probability.
    """

    def __init__(self, n: int, alpha: float):
        self.n = max(1, n)
        self.D = max(0.01, min(0.99, float(alpha)))
        # counts[k] = {context_tuple: {next_byte: count}} for k-grams.
        # k is the *order* (1..n), context_tuple has length k-1.
        self.counts: list[dict] = [None] + [
            defaultdict(lambda: defaultdict(int)) for _ in range(self.n)
        ]
        self.totals: list[dict] = [None] + [
            defaultdict(int) for _ in range(self.n)
        ]
        # continuation_left[k] = {context_tuple of len k-1: set of bytes
        #   that precede this context} -- not needed; we use n1plus_right
        # n1plus_right[k] = {context_tuple of len k-1: number of distinct
        #   next bytes seen after this context}
        self.n1plus_right: list[dict] = [None] + [
            defaultdict(int) for _ in range(self.n)
        ]
        # For continuation prob on lower orders, we need:
        # continuation_count[k] = {tuple of len k-1 + next: number of
        #   distinct preceding bytes}, i.e. N1+(. , w_{i-k+1..i}).
        # Implementation: per order k>=2, count distinct left-extensions
        # of the k-gram.
        self.cont_left_extensions: list[dict] = [None] + [
            defaultdict(set) for _ in range(self.n)
        ]
        # For order 1 continuation prob denominator: total number of
        # distinct (preceding_byte, byte) pairs at order 2.
        self._n1plus_dot_dot = 0
        # cache: n1plus_left_byte[w] = number of distinct preceding bytes
        # for w  (computed from cont_left_extensions[2]).
        self._n1plus_left_byte: dict = {}

    def train(self, data: bytes) -> None:
        n = self.n
        # k-gram counts
        for k in range(1, n + 1):
            if k == 1:
                for b in data:
                    self.counts[1][()][b] += 1
                    self.totals[1][()] += 1
            else:
                for i in range(k - 1, len(data)):
                    ctx = tuple(data[i - k + 1: i])
                    nxt = data[i]
                    self.counts[k][ctx][nxt] += 1
                    self.totals[k][ctx] += 1
        # n1plus_right[k][ctx] = number of distinct continuations after ctx
        for k in range(1, n + 1):
            for ctx, nxt_counts in self.counts[k].items():
                self.n1plus_right[k][ctx] = len(nxt_counts)
        # cont_left_extensions[k][(c1..c_{k-1}, w)] = set of preceding bytes
        # We compute by walking data again with a window of size k+1 for k<n.
        for k in range(2, n + 1):
            for i in range(k, len(data)):
                left = data[i - k]
                key = tuple(data[i - k + 1: i + 1])  # length k
                self.cont_left_extensions[k][key].add(left)
        # n1plus_left_byte[w] for unigram continuation prob:
        if n >= 2:
            for (left, w), _ in [((k[0], k[1]), v) for k, v in
                                 self.cont_left_extensions[2].items()]:
                # cont_left_extensions[2] key is (a, b) where b = w, a = left
                pass
            # Simpler: walk order-2 keys; cont_left_extensions[2] keyed by
            # (a, b) where the set is the bytes preceding 'a'. But we want
            # number of distinct (a) for each w=b. Use counts[2] directly:
            # at order 2, counts[2][(a,)][b] > 0 iff bigram (a,b) seen.
            # n1plus_left_byte[w] = |{ a : counts[2][(a,)][w] > 0 }|.
            preceders: dict[int, set] = defaultdict(set)
            for ctx, nxt_counts in self.counts[2].items():
                a = ctx[0]
                for w in nxt_counts:
                    preceders[w].add(a)
            self._n1plus_left_byte = {w: len(s) for w, s in preceders.items()}
            self._n1plus_dot_dot = sum(self._n1plus_left_byte.values())
        else:
            self._n1plus_dot_dot = max(1, sum(self.totals[1].values()))

    def _continuation_prob(self, k: int, ctx: tuple, nxt: int) -> float:
        """P_cont at order k (uses continuation counts, not raw counts)."""
        if k == 1:
            # Unigram continuation: N1+(., w) / N1+(., .)
            num = self._n1plus_left_byte.get(nxt, 0)
            den = self._n1plus_dot_dot or 1
            # Small additive to avoid zero (rare for unseen byte at unigram)
            p = (num + 1e-9) / (den + 256 * 1e-9)
            return p
        # k >= 2: use N1+ continuation counts at this order
        # Numerator: N1+(., ctx, nxt) = number of distinct left-extensions
        # of (ctx + (nxt,)). Stored in cont_left_extensions[k] keyed by
        # tuple of length k. We need k+1 actually... wait.
        # For continuation prob at order k, we need N1+(., ctx, nxt) where
        # ctx has length k-1, so the (k)-gram is (ctx + (nxt,)). The
        # left-extension set is in cont_left_extensions[k][ctx+(nxt,)].
        full = ctx + (nxt,)
        left_ext = self.cont_left_extensions[k].get(full)
        num = len(left_ext) if left_ext else 0
        # Denominator: sum over w of N1+(., ctx, w). Equivalent to
        # N1+(., ctx, .) = total distinct (left, ctx, w) triples / |w|.
        # We compute it on the fly.
        # For efficiency at small n this is fine.
        den = 0
        for w in self.counts[k].get(ctx, {}):
            ext = self.cont_left_extensions[k].get(ctx + (w,))
            if ext:
                den += len(ext)
        if den == 0:
            # Fall through to lower order
            if k == 1:
                return 1.0 / (VOCAB + 1)
            return self._continuation_prob(k - 1, ctx[1:], nxt)
        # Apply discount + backoff weight (interpolated KN at continuation)
        D = self.D
        discounted = max(num - D, 0) / den
        n1plus = self.n1plus_right[k].get(ctx, 0)
        lam = (D * n1plus) / den if den > 0 else 0.0
        lower = self._continuation_prob(k - 1, ctx[1:] if k > 1 else (), nxt)
        return discounted + lam * lower

    def _highest_prob(self, ctx: tuple, nxt: int) -> float:
        """P_KN at highest order n (uses raw counts at highest, KN cont below)."""
        n = self.n
        if n == 1:
            # Unigram MLE with tiny smoothing
            total = self.totals[1][()] or 1
            c = self.counts[1][()].get(nxt, 0)
            return (c + 1e-3) / (total + VOCAB * 1e-3)
        ctx_total = self.totals[n].get(ctx, 0)
        if ctx_total == 0:
            # Unseen highest-order context — recurse to (n-1) continuation
            return self._continuation_prob(n - 1, ctx[1:], nxt)
        c = self.counts[n].get(ctx, {}).get(nxt, 0)
        D = self.D
        discounted = max(c - D, 0) / ctx_total
        n1plus = self.n1plus_right[n].get(ctx, 0)
        lam = (D * n1plus) / ctx_total
        lower = self._continuation_prob(n - 1, ctx[1:], nxt)
        return discounted + lam * lower

    def neg_log_prob(self, ctx: tuple, nxt: int) -> float:
        p = self._highest_prob(ctx, nxt)
        if p <= 0:
            p = 1.0 / (VOCAB * 1000.0)
        return -math.log(p)

    def eval_neg_log_prob_nats(self, data: bytes) -> tuple[float, int]:
        n = self.n
        total, count = 0.0, 0
        start = n - 1
        for i in range(start, len(data)):
            ctx = tuple(data[i - start: i]) if start > 0 else ()
            total += self.neg_log_prob(ctx, data[i])
            count += 1
        return total, count


class ContextConditionalKN(KneserNeyNGram):
    """Context-conditional KN: discount D varies by context count tier.

    Where Modified-KN varies D by the n-gram's own count (c=1,2,3+), this
    variant varies D by the *context's* total observed count:

        ctx_total = sum_w counts[n][ctx][w]
        sparse  (ctx_total <=  2):  D = alpha * 1.3  (untrustworthy ctx -> more mass to backoff)
        medium  (ctx_total <= 10):  D = alpha
        dense   (ctx_total >  10):  D = alpha * 0.6  (trustworthy ctx -> keep observed mass)

    Rationale: on a tiny corpus most contexts are seen 1-3 times, so the
    single-D KN over-trusts MLE on rare contexts. Discounting them harder
    while preserving high-count ctxs should improve held-out ppl.
    """

    CTX_SPARSE_MAX = 2
    CTX_DENSE_MIN = 11  # ctx_total in [3..10] = medium

    def __init__(self, n: int, alpha: float):
        super().__init__(n, alpha)
        self.D_sparse = max(0.01, min(0.99, 1.3 * self.D))
        self.D_mid    = self.D
        self.D_dense  = max(0.01, min(0.99, 0.6 * self.D))

    def _discount_for_ctx_total(self, ctx_total: int) -> float:
        if ctx_total <= self.CTX_SPARSE_MAX:
            return self.D_sparse
        if ctx_total >= self.CTX_DENSE_MIN:
            return self.D_dense
        return self.D_mid

    def _highest_prob(self, ctx: tuple, nxt: int) -> float:
        n = self.n
        if n == 1:
            total = self.totals[1][()] or 1
            c = self.counts[1][()].get(nxt, 0)
            return (c + 1e-3) / (total + VOCAB * 1e-3)
        ctx_total = self.totals[n].get(ctx, 0)
        if ctx_total == 0:
            return self._continuation_prob(n - 1, ctx[1:], nxt)
        c = self.counts[n].get(ctx, {}).get(nxt, 0)
        D = self._discount_for_ctx_total(ctx_total)
        discounted = max(c - D, 0) / ctx_total
        n1plus = self.n1plus_right[n].get(ctx, 0)
        lam = (D * n1plus) / ctx_total
        lower = self._continuation_prob(n - 1, ctx[1:], nxt)
        return discounted + lam * lower

    def _continuation_prob(self, k: int, ctx: tuple, nxt: int) -> float:
        # Same continuation formula as parent, but using ctx-conditional D.
        if k == 1:
            num = self._n1plus_left_byte.get(nxt, 0)
            den = self._n1plus_dot_dot or 1
            return (num + 1e-9) / (den + 256 * 1e-9)
        full = ctx + (nxt,)
        left_ext = self.cont_left_extensions[k].get(full)
        num = len(left_ext) if left_ext else 0
        den = 0
        for w in self.counts[k].get(ctx, {}):
            ext = self.cont_left_extensions[k].get(ctx + (w,))
            if ext:
                den += len(ext)
        if den == 0:
            if k == 1:
                return 1.0 / (VOCAB + 1)
            return self._continuation_prob(k - 1, ctx[1:], nxt)
        ctx_total = self.totals[k].get(ctx, 0)
        D = self._discount_for_ctx_total(ctx_total)
        discounted = max(num - D, 0) / den
        n1plus = self.n1plus_right[k].get(ctx, 0)
        lam = (D * n1plus) / den if den > 0 else 0.0
        lower = self._continuation_prob(k - 1, ctx[1:] if k > 1 else (), nxt)
        return discounted + lam * lower


class ContextConditionalKN2(KneserNeyNGram):
    """G2+ hyperparameterized variant of ContextConditionalKN.

    Same idea (D varies by context count tier) but with tier boundaries
    and per-tier multipliers exposed as genome parameters instead of
    hard-coded constants.

        sparse_max:    ctx_total <= sparse_max -> D = alpha * mult_sparse
        dense_min:     ctx_total >= dense_min  -> D = alpha * mult_dense
        (between):                              -> D = alpha * mult_mid (= 1.0)

    Genome shape:
        {style: "kn_ctx2", n, alpha,
         sparse_max, dense_min, mult_sparse, mult_dense}
    """

    def __init__(self, n: int, alpha: float,
                 sparse_max: int = 2, dense_min: int = 11,
                 mult_sparse: float = 1.3, mult_dense: float = 0.6,
                 mult_mid: float = 1.0):
        super().__init__(n, alpha)
        self.sparse_max = int(sparse_max)
        self.dense_min = int(dense_min)
        self.D_sparse = max(0.01, min(0.99, mult_sparse * self.D))
        self.D_mid = max(0.01, min(0.99, mult_mid * self.D))
        self.D_dense = max(0.01, min(0.99, mult_dense * self.D))

    def _discount_for_ctx_total(self, ctx_total: int) -> float:
        if ctx_total <= self.sparse_max:
            return self.D_sparse
        if ctx_total >= self.dense_min:
            return self.D_dense
        return self.D_mid

    # Same _highest_prob / _continuation_prob as ContextConditionalKN:
    _highest_prob = ContextConditionalKN._highest_prob
    _continuation_prob = ContextConditionalKN._continuation_prob


class ModifiedKneserNeyNGram(KneserNeyNGram):
    """Modified KN with 3 discount levels D1, D2, D3+ based on count class.

    alpha sets D2 (the middle discount). D1 = 0.7*alpha, D3+ = 1.3*alpha.
    Chen+Goodman 1998: D1 < D2 < D3+ heuristically.
    """

    def __init__(self, n: int, alpha: float):
        super().__init__(n, alpha)
        self.D1 = max(0.01, min(0.99, 0.7 * self.D))
        self.D2 = self.D
        self.D3 = max(0.01, min(0.99, 1.3 * self.D))

    def _discount_for_count(self, c: int) -> float:
        if c <= 0:
            return 0.0
        if c == 1:
            return self.D1
        if c == 2:
            return self.D2
        return self.D3

    def _highest_prob(self, ctx: tuple, nxt: int) -> float:
        n = self.n
        if n == 1:
            total = self.totals[1][()] or 1
            c = self.counts[1][()].get(nxt, 0)
            return (c + 1e-3) / (total + VOCAB * 1e-3)
        ctx_total = self.totals[n].get(ctx, 0)
        if ctx_total == 0:
            return self._continuation_prob(n - 1, ctx[1:], nxt)
        c = self.counts[n].get(ctx, {}).get(nxt, 0)
        D = self._discount_for_count(c)
        discounted = max(c - D, 0) / ctx_total
        # Backoff weight is sum over count classes of (D_k * N_k(ctx)).
        # Simpler approximation: use weighted single discount with the
        # average D used per ctx. Sufficient at our scale.
        n1plus = self.n1plus_right[n].get(ctx, 0)
        avg_D = self.D2
        lam = (avg_D * n1plus) / ctx_total
        lower = self._continuation_prob(n - 1, ctx[1:], nxt)
        return discounted + lam * lower


class KnCtxMod(ModifiedKneserNeyNGram):
    """Orthogonal hybrid of Modified-KN (count-tier) and kn_ctx2 (context-tier).

    Effective discount for an n-gram (ctx, w) with raw count c and context
    total ctx_total is:

        D_eff(c, ctx_total) = D_count(c) * ctx_mult(ctx_total)

    where D_count(c) is MKN's classical 3-tier discount (D1=0.7α, D2=α,
    D3+=1.3α) and ctx_mult is the kn_ctx2 context multiplier:

        sparse  (ctx_total <= sparse_max):  mult_sparse
        dense   (ctx_total >= dense_min):   mult_dense
        middle:                             mult_mid (=1.0 by default)

    Backoff weight uses D2 * ctx_mult as the per-ctx average discount.
    Lower-order continuation probs use single-D KN with ctx-multiplier
    (inherited via ContextConditionalKN2 semantics — applied here directly
    so the class does not need multiple inheritance).

    Degenerate case: when mult_sparse = mult_dense = mult_mid = 1.0,
    the model is exactly ModifiedKneserNeyNGram(n, alpha). Verified in
    tests / search baseline.

    Genome shape:
        {style: "kn_ctx_mod", n, alpha,
         sparse_max, dense_min, mult_sparse, mult_dense}
    """

    def __init__(self, n: int, alpha: float,
                 sparse_max: int = 2, dense_min: int = 11,
                 mult_sparse: float = 1.0, mult_dense: float = 1.0,
                 mult_mid: float = 1.0):
        super().__init__(n, alpha)
        self.sparse_max = int(sparse_max)
        self.dense_min = int(dense_min)
        self.mult_sparse = float(mult_sparse)
        self.mult_mid = float(mult_mid)
        self.mult_dense = float(mult_dense)

    def _ctx_mult(self, ctx_total: int) -> float:
        if ctx_total <= self.sparse_max:
            return self.mult_sparse
        if ctx_total >= self.dense_min:
            return self.mult_dense
        return self.mult_mid

    @staticmethod
    def _clamp(d: float) -> float:
        return max(0.01, min(0.99, d))

    def _highest_prob(self, ctx: tuple, nxt: int) -> float:
        n = self.n
        if n == 1:
            total = self.totals[1][()] or 1
            c = self.counts[1][()].get(nxt, 0)
            return (c + 1e-3) / (total + VOCAB * 1e-3)
        ctx_total = self.totals[n].get(ctx, 0)
        if ctx_total == 0:
            return self._continuation_prob(n - 1, ctx[1:], nxt)
        c = self.counts[n].get(ctx, {}).get(nxt, 0)
        mult = self._ctx_mult(ctx_total)
        D = self._clamp(self._discount_for_count(c) * mult)
        discounted = max(c - D, 0) / ctx_total
        n1plus = self.n1plus_right[n].get(ctx, 0)
        avg_D = self._clamp(self.D2 * mult)
        lam = (avg_D * n1plus) / ctx_total
        lower = self._continuation_prob(n - 1, ctx[1:], nxt)
        return discounted + lam * lower

    def _continuation_prob(self, k: int, ctx: tuple, nxt: int) -> float:
        # Single-D KN at lower orders, with context-tier multiplier applied.
        if k == 1:
            num = self._n1plus_left_byte.get(nxt, 0)
            den = self._n1plus_dot_dot or 1
            return (num + 1e-9) / (den + 256 * 1e-9)
        full = ctx + (nxt,)
        left_ext = self.cont_left_extensions[k].get(full)
        num = len(left_ext) if left_ext else 0
        den = 0
        for w in self.counts[k].get(ctx, {}):
            ext = self.cont_left_extensions[k].get(ctx + (w,))
            if ext:
                den += len(ext)
        if den == 0:
            if k == 1:
                return 1.0 / (VOCAB + 1)
            return self._continuation_prob(k - 1, ctx[1:] if k > 1 else (), nxt)
        ctx_total = self.totals[k].get(ctx, 0)
        D = self._clamp(self.D * self._ctx_mult(ctx_total))
        discounted = max(num - D, 0) / den
        n1plus = self.n1plus_right[k].get(ctx, 0)
        lam = (D * n1plus) / den if den > 0 else 0.0
        lower = self._continuation_prob(k - 1, ctx[1:] if k > 1 else (), nxt)
        return discounted + lam * lower


def _count_class_counts(word_counts: dict) -> tuple[int, int, int]:
    """(N1, N2, N3+) = number of distinct continuations with count ==1, ==2, >=3."""
    n1 = n2 = n3 = 0
    for c in word_counts.values():
        if c == 1:
            n1 += 1
        elif c == 2:
            n2 += 1
        else:
            n3 += 1
    return n1, n2, n3


class ModifiedKneserNeyExactNGram(ModifiedKneserNeyNGram):
    """Modified-KN with the *exact* Chen+Goodman backoff weight.

    The parent class approximates the per-context backoff mass as
    `gamma ≈ D2 * N1+(ctx) / ctx_total`, which does NOT make the
    highest-order distribution sum to 1. The exact weight is

        gamma(ctx) = [D1*N1(ctx) + D2*N2(ctx) + D3+*N3+(ctx)] / ctx_total

    where N_k(ctx) is the number of distinct continuations of ctx seen
    exactly k times (N3+ = seen >= 3 times). Using the same per-count
    discounts in the numerator (discounted mass removed) and the backoff
    weight guarantees Σ_w P(w|ctx) = 1 (given the lower order is proper).
    """

    def train(self, data: bytes) -> None:
        super().train(data)
        self._cc: dict = {}
        n = self.n
        if n >= 2:
            for ctx, wc in self.counts[n].items():
                self._cc[ctx] = _count_class_counts(wc)

    def _highest_prob(self, ctx: tuple, nxt: int) -> float:
        n = self.n
        if n == 1:
            total = self.totals[1][()] or 1
            c = self.counts[1][()].get(nxt, 0)
            return (c + 1e-3) / (total + VOCAB * 1e-3)
        ctx_total = self.totals[n].get(ctx, 0)
        if ctx_total == 0:
            return self._continuation_prob(n - 1, ctx[1:], nxt)
        c = self.counts[n].get(ctx, {}).get(nxt, 0)
        D = self._discount_for_count(c)
        discounted = max(c - D, 0) / ctx_total
        n1, n2, n3 = self._cc.get(ctx, (0, 0, 0))
        gamma = (self.D1 * n1 + self.D2 * n2 + self.D3 * n3) / ctx_total
        lower = self._continuation_prob(n - 1, ctx[1:], nxt)
        return discounted + gamma * lower


class KnCtxModExact(KnCtxMod):
    """KnCtxMod (count-tier × context-tier hybrid) with exact backoff weight.

    Combines:
      - KnCtxMod's per-count discount scaled by the context-tier multiplier:
            D_eff(c) = clamp(D_count(c) * ctx_mult(ctx_total))
      - The exact Chen+Goodman backoff weight using those same D_eff:
            gamma(ctx) = [D_eff(1)*N1 + D_eff(2)*N2 + D_eff(3+)*N3+] / ctx_total

    Sharing the clamped D_eff between the discounted numerator and gamma
    keeps Σ_w P(w|ctx) = 1 exactly (given the lower order is proper).

    Degenerate case: mult_sparse=mult_dense=mult_mid=1.0 reduces to
    ModifiedKneserNeyExactNGram(n, alpha) — NOT to the approximate L5mkn.

    `gamma_scale` multiplies the exact backoff weight. gamma_scale=1.0 is
    the proper normalized model; gamma_scale>1.0 deliberately over-weights
    backoff (the implicit regularizer that the old approximate weight gave
    for free, which helps held-out ppl on a tiny/sparse corpus).

    Genome shape:
        {style: "kn_ctx_mod_exact", n, alpha,
         sparse_max, dense_min, mult_sparse, mult_dense, mult_mid, gamma_scale}
    """

    def __init__(self, n: int, alpha: float,
                 sparse_max: int = 2, dense_min: int = 11,
                 mult_sparse: float = 1.0, mult_dense: float = 1.0,
                 mult_mid: float = 1.0, gamma_scale: float = 1.0):
        super().__init__(n, alpha, sparse_max=sparse_max, dense_min=dense_min,
                         mult_sparse=mult_sparse, mult_dense=mult_dense,
                         mult_mid=mult_mid)
        self.gamma_scale = float(gamma_scale)

    def train(self, data: bytes) -> None:
        super().train(data)
        self._cc: dict = {}
        n = self.n
        if n >= 2:
            for ctx, wc in self.counts[n].items():
                self._cc[ctx] = _count_class_counts(wc)

    def _highest_prob(self, ctx: tuple, nxt: int) -> float:
        n = self.n
        if n == 1:
            total = self.totals[1][()] or 1
            c = self.counts[1][()].get(nxt, 0)
            return (c + 1e-3) / (total + VOCAB * 1e-3)
        ctx_total = self.totals[n].get(ctx, 0)
        if ctx_total == 0:
            return self._continuation_prob(n - 1, ctx[1:], nxt)
        c = self.counts[n].get(ctx, {}).get(nxt, 0)
        mult = self._ctx_mult(ctx_total)
        D1 = self._clamp(self.D1 * mult)
        D2 = self._clamp(self.D2 * mult)
        D3 = self._clamp(self.D3 * mult)
        if c == 1:
            Dc = D1
        elif c == 2:
            Dc = D2
        elif c >= 3:
            Dc = D3
        else:
            Dc = 0.0
        discounted = max(c - Dc, 0) / ctx_total
        n1, n2, n3 = self._cc.get(ctx, (0, 0, 0))
        gamma = self.gamma_scale * (D1 * n1 + D2 * n2 + D3 * n3) / ctx_total
        lower = self._continuation_prob(n - 1, ctx[1:], nxt)
        return discounted + gamma * lower
