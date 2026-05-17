#!/usr/bin/env python3
"""IM-1 sample 1: quorum_replicate — fast provider wins.

Three "providers" simulate different latencies.  call_ai_quorum
returns whichever finishes first; the others either complete late
(logged as quorum_late) or are simply abandoned with their result.

Run:
    AIPL_DIST_ENABLE=1 AIPL_DIST_QUORUM_PROVIDERS="fast,med,slow" \\
    AIPL_DIST_LOG_FILE=/tmp/quorum.ndjson python3 sample1_first_wins.py
    grep quorum /tmp/quorum.ndjson
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "..", "..", "src", "python-aipl")))
import aipl_dist  # noqa: E402

DELAYS = {"fast": 0.05, "med": 0.15, "slow": 0.40}

def fake_call(prompt, **kw):
    prov = kw.get("provider_override", "?")
    time.sleep(DELAYS.get(prov, 0.1))
    return f"{prov}-reply"

t0 = time.time()
result = aipl_dist.call_ai_quorum("hello world", call_ai_fn=fake_call)
print(f"winner reply: {result}    ({time.time()-t0:.2f}s)")
