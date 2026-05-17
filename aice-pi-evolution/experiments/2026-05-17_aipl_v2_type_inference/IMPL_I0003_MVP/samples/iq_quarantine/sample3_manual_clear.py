#!/usr/bin/env python3
"""IQ sample 3: explicit clear_quarantine().

Useful for ops scenarios: an actor was quarantined automatically,
the operator fixes the underlying issue, and wants to re-enable
the actor immediately without waiting for the TTL.

Run:
    AIPL_DIST_ENABLE=1 python3 sample3_manual_clear.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "..", "..", "src", "python-aipl")))
import aipl_dist  # noqa: E402

# Quarantine 3 actors with a long TTL.
for name in ["A", "B", "C"]:
    aipl_dist.quarantine_actor(name, ttl=3600)
print(f"after bulk quarantine: status = {sorted(aipl_dist.quarantine_status())}")
print()

# Clear one explicitly.
print(f"  clear_quarantine('B')   = {aipl_dist.clear_quarantine('B')}")
print(f"  clear_quarantine('Z')   = {aipl_dist.clear_quarantine('Z')} (no entry)")
print(f"  is_quarantined('B')     = {aipl_dist.is_quarantined('B')}")
print(f"  status (A, C remain)    = {sorted(aipl_dist.quarantine_status())}")
