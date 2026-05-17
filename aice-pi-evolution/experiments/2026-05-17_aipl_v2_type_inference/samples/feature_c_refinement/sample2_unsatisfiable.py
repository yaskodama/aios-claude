#!/usr/bin/env python3
"""Feature C (refinement types + Z3) — Sample 2: unsatisfiable predicates.

These predicates have NO Int that can satisfy them, and the Z3
backend correctly reports them as unsat — the inference engine
would refuse to admit such a refined type.

Run:
    python3 sample2_unsatisfiable.py
"""
import sys
sys.path.insert(0, "/Users/kodamay/ocaml-app/abclcp-project/src/python-aipl")
import aipl_inference as ai
import z3

# Predicates whose only solutions are empty.
cases = [
    ("Int where k >= 5 and k <= 3",    "k"),
    ("Int where x > 0 and x < 0",      "x"),
    ("Int where n >= 100 and n <= 10", "n"),
    ("Int where k == 1 and k == 2",    "k"),
    ("Int where a > b and a < b",      "a"),    # vacuous on common a, b
]

print(f"=== Feature C Sample 2: unsatisfiable refinements ({len(cases)}) ===")
for src, binder in cases:
    infer = ai.Inference()
    t = ai._parse_annotation(src, infer)
    if isinstance(t, ai.TRefined):
        t = ai.TRefined(t.base, binder, t.pred_src, t.pred_ast)
    ok, why = ai._z3_check(z3, t, binder)
    note = f"  ({why})" if why else ""
    mark = "✓" if not ok else "✗"   # we EXPECT unsat
    print(f"  {mark} {src:55s}  satisfiable = {ok}{note}")
print()
print("expected: all ✓ (= UNSAT, refinement rejected)")
