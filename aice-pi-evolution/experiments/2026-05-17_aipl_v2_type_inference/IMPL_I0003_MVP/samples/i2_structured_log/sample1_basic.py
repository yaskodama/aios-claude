#!/usr/bin/env python3
"""I-2 sample: structured_log demonstrated as a Python script (AIPL
itself cannot conveniently call aipl_dist directly without further
runtime integration; this is the MVP-level demonstration).

Run:
    AIPL_DIST_ENABLE=1 AIPL_DIST_LOG_FILE=/tmp/aipl_dist_demo.ndjson \\
        python3 structured_log_demo.py
    cat /tmp/aipl_dist_demo.ndjson
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PYABCL = os.path.normpath(
    os.path.join(HERE, "..", "..", "..", "..", "..", "..", "src", "python-aipl"))
sys.path.insert(0, PYABCL)

import aipl_dist  # noqa: E402

print(f"is_enabled() = {aipl_dist.is_enabled()}")
print(f"log_event('startup', who='alice') -> {aipl_dist.log_event('startup', who='alice')}")
print(f"log_event('work', task=1, ms=42) -> {aipl_dist.log_event('work', task=1, ms=42)}")
print(f"log_event('shutdown') -> {aipl_dist.log_event('shutdown')}")
if aipl_dist.is_enabled():
    p = os.environ.get("AIPL_DIST_LOG_FILE", "")
    if p:
        print(f"\nLog written to: {p}")
        print("Tail:")
        try:
            with open(p) as f:
                for line in f.readlines()[-3:]:
                    print("  " + line.rstrip())
        except Exception as e:
            print("  (could not read)", e)
