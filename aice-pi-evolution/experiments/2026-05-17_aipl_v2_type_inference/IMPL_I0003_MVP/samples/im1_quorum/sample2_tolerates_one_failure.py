#!/usr/bin/env python3
"""IM-1 sample 2: one provider fails, the rest succeed → caller never sees the failure.

Mirrors the PsiLang-v3 silent-hang remedy at the call level: with
multiple providers running in parallel, a single bad one doesn't
stop the caller.

Run:
    AIPL_DIST_ENABLE=1 AIPL_DIST_QUORUM_PROVIDERS="broken,working,backup" \\
    python3 sample2_tolerates_one_failure.py
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "..", "..", "src", "python-aipl")))
import aipl_dist  # noqa: E402

def fake_call(prompt, **kw):
    prov = kw.get("provider_override", "?")
    if prov == "broken":
        raise RuntimeError("simulated 503")
    delay = 0.1 if prov == "working" else 0.3
    time.sleep(delay)
    return f"{prov}-reply"

t0 = time.time()
result = aipl_dist.call_ai_quorum("hello", call_ai_fn=fake_call)
print(f"winner reply: {result}    ({time.time()-t0:.2f}s)")
print("→ broken provider's exception was swallowed; caller continues.")
