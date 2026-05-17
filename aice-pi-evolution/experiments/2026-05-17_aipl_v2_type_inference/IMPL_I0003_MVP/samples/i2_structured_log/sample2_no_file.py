#!/usr/bin/env python3
"""I-2 sample 2: log_event is a graceful no-op when AIPL_DIST_LOG_FILE
is not configured.  Returns False; never raises.

Run:
    AIPL_DIST_ENABLE=1 python3 sample2_no_file.py          # no log file
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "..", "..", "src", "python-aipl")))
import aipl_dist  # noqa: E402

print(f"AIPL_DIST_ENABLE={os.environ.get('AIPL_DIST_ENABLE', '(unset)')}")
print(f"AIPL_DIST_LOG_FILE={os.environ.get('AIPL_DIST_LOG_FILE', '(unset)')}")
for i in range(5):
    rc = aipl_dist.log_event(f"event_{i}", value=i)
    print(f"  log_event(event_{i}) -> {rc}")
print()
print("→ With AIPL_DIST_ENABLE=1 but no file, every call returns False.")
print("→ With AIPL_DIST_LOG_FILE set, every call returns True and writes a line.")
