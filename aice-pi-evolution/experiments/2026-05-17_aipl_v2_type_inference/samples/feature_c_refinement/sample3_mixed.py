#!/usr/bin/env python3
"""Feature C (refinement types + Z3) — Sample 3: mixed-shape predicates.

Exercises the Python-AST → Z3 translator on more complex predicates:
chained compares, parentheses, `not`, modular arithmetic, multi-variable
constraints.  Each case prints expected vs actual.

Run:
    python3 sample3_mixed.py
"""
import sys
sys.path.insert(0, "/Users/kodamay/ocaml-app/abclcp-project/src/python-aipl")
import aipl_inference as ai
import z3

# (predicate, binder, expected_satisfiable)
cases = [
    # chained compare (lowered into conjunction by ast.Compare)
    ("Int where 0 <= x and x <= 100",        "x", True),
    # `not` and parens
    ("Int where not (x == 0)",                "x", True),
    # multi-variable disjunction
    ("Int where (k == 0) or (k > 5 and k < 10)", "k", True),
    # arithmetic in predicate
    ("Int where 2 * x + 1 == 7",              "x", True),     # x == 3
    # contradictions hidden behind boolean structure
    ("Int where (x > 10) and not (x > 5)",    "x", False),
    # absolute contradiction with arithmetic
    ("Int where x + 1 == x",                  "x", False),
    # 'mod' is a Python keyword absent from `ast` → falls back to
    # conservative documentation (no rejection).
    ("Int where k mod 2 == 0",                "k", True),
]

print(f"=== Feature C Sample 3: mixed refinements ({len(cases)}) ===")
pass_ = 0
for src, binder, expected in cases:
    infer = ai.Inference()
    t = ai._parse_annotation(src, infer)
    if isinstance(t, ai.TRefined):
        t = ai.TRefined(t.base, binder, t.pred_src, t.pred_ast)
    ok, why = ai._z3_check(z3, t, binder)
    matched = ok == expected
    pass_ += int(matched)
    mark = "✓" if matched else "✗"
    note = f"  ({why})" if why else ""
    print(f"  {mark} {src:50s}  sat={ok} (expected={expected}){note}")
print()
print(f"{pass_}/{len(cases)} cases match expectation.")
