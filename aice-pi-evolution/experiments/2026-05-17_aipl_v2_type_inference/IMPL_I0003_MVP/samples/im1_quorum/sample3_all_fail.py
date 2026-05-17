#!/usr/bin/env python3
"""IM-1 sample 3: every provider fails → caller sees a synthesised RuntimeError.

This is the "all bets off" path.  call_ai_quorum collects every
provider's exception text into one error message so the operator
can see what each provider returned.

Run:
    AIPL_DIST_ENABLE=1 AIPL_DIST_QUORUM_PROVIDERS="p1,p2,p3" python3 sample3_all_fail.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "..", "..", "src", "python-aipl")))
import aipl_dist  # noqa: E402

def all_broken(prompt, **kw):
    prov = kw.get("provider_override", "?")
    raise RuntimeError(f"{prov}: simulated outage")

try:
    aipl_dist.call_ai_quorum("hi", call_ai_fn=all_broken)
except RuntimeError as e:
    print(f"caught: {e}")
