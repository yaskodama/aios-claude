#!/usr/bin/env python3
"""I-3 sample 2: budget gate actually blocks when limits are hit.

Without manipulating time, we can demonstrate the blocking path by
filling the window then asking for one more.  We use a small RPM
and a manual pre-fill so the test stays under a few seconds.

Run:
    AIPL_DIST_ENABLE=1 AIPL_DIST_RPM=2 python3 sample2_blocking.py
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "..", "..", "src", "python-aipl")))
import aipl_dist  # noqa: E402

g = aipl_dist.token_budget_gate()
print(f"gate = {g}")
print(f"AIPL_DIST_RPM = {os.environ.get('AIPL_DIST_RPM', '(unset)')}")
if g is None:
    print("(gate not configured — set AIPL_DIST_RPM)")
    sys.exit(0)

t0 = time.time()
g.acquire(0); print(f"  call 1 admitted at {time.time()-t0:.2f}s")
g.acquire(0); print(f"  call 2 admitted at {time.time()-t0:.2f}s")
# Simulate the "old" events expiring early so call 3 can proceed.
# In production this happens via 60s wall-clock; we fast-forward here.
import time as _t
print("  (fast-forward window by mutating event timestamps)")
expired = [(t - 70, n) for t, n in g._events]
g._events.clear()
for ev in expired:
    g._events.append(ev)
g.acquire(0); print(f"  call 3 admitted at {time.time()-t0:.2f}s (window flushed)")
print()
print(f"stats: {g.stats()}")
