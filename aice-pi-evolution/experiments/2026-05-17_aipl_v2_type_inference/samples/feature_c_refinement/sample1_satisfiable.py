#!/usr/bin/env python3
"""Feature C (refinement types + Z3) — Sample 1: satisfiable predicates.

Demonstrates that `Int where <predicate>` annotations whose
predicate is satisfiable are accepted by the Z3 backend.  Note
that AIPL's surface grammar does not yet accept `where` clauses,
so we drive the inference engine directly via its public API.

Run:
    python3 sample1_satisfiable.py
"""
import sys
sys.path.insert(0, "/Users/kodamay/ocaml-app/abclcp-project/src/python-aipl")
import aipl_inference as ai
import z3

# Cases the Phase C / D inference engine should accept.
cases = [
    ("Int where k >= 0",                          "k"),
    ("Int where n_terms >= 2",                    "n_terms"),
    ("Int where sign == 1 or sign == -1",         "sign"),
    ("Int where m > a and m < b",                 "m"),
    ("Int where x >= 0 and x <= 100 and x != 50", "x"),
]

print(f"=== Feature C Sample 1: satisfiable refinements ({len(cases)}) ===")
for src, binder in cases:
    infer = ai.Inference()
    t = ai._parse_annotation(src, infer)
    if isinstance(t, ai.TRefined):
        t = ai.TRefined(t.base, binder, t.pred_src, t.pred_ast)
    ok, why = ai._z3_check(z3, t, binder)
    note = f"  ({why})" if why else ""
    mark = "✓" if ok else "✗"
    print(f"  {mark} {src:55s}  satisfiable = {ok}{note}")
print()
print("expected: all ✓ (satisfiable)")
