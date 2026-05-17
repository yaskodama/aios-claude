#!/usr/bin/env python3
"""I-3 sample: token_budget_aware scheduling.

Demonstrates that the gate admits requests up to RPM, then blocks the
next.  Uses a fake `call_ai_fn` to avoid real LLM cost.

Run:
    AIPL_DIST_ENABLE=1 AIPL_DIST_RPM=3 python3 token_budget_demo.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PYABCL = os.path.normpath(
    os.path.join(HERE, "..", "..", "..", "..", "..", "..", "src", "python-aipl"))
sys.path.insert(0, PYABCL)

import aipl_dist  # noqa: E402


calls = 0
def fake_call_ai(prompt, **kw):
    global calls
    calls += 1
    return f"reply-{calls}"


print(f"is_enabled() = {aipl_dist.is_enabled()}")
print(f"AIPL_DIST_RPM = {os.environ.get('AIPL_DIST_RPM', '(unset)')}")
gate = aipl_dist.token_budget_gate()
print(f"gate = {gate}")
print()

# Three quick calls — should all admit.
for i in range(3):
    t0 = time.time()
    r = aipl_dist.call_ai_with_budget(f"hi {i}", call_ai_fn=fake_call_ai, max_tokens=8)
    print(f"  call {i+1}: {r}  ({time.time()-t0:.2f}s)")

if gate is not None:
    print()
    print(f"window stats: {gate.stats()}")
