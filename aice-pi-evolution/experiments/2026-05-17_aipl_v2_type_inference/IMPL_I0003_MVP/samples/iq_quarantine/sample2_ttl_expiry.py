#!/usr/bin/env python3
"""IQ sample 2: quarantine expires after TTL.

Marks an actor quarantined for 0.5s, waits 0.6s, then verifies it
becomes eligible again (quarantine_status() returns it gone).

Run:
    AIPL_DIST_ENABLE=1 python3 sample2_ttl_expiry.py
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "..", "..", "src", "python-aipl")))
import aipl_dist  # noqa: E402

# Explicit ttl override (env default is 60s).
print(f"quarantine_ttl env default = {aipl_dist.quarantine_ttl()}s")
print()
ok = aipl_dist.quarantine_actor("Flaky", ttl=0.5)
print(f"  quarantine_actor('Flaky', ttl=0.5) = {ok}")
print(f"  is_quarantined('Flaky') = {aipl_dist.is_quarantined('Flaky')}")
print(f"  status = {aipl_dist.quarantine_status()}")
print()
print("  sleep 0.6s ...")
time.sleep(0.6)
print(f"  is_quarantined('Flaky') = {aipl_dist.is_quarantined('Flaky')}")
print(f"  status = {aipl_dist.quarantine_status()}")
