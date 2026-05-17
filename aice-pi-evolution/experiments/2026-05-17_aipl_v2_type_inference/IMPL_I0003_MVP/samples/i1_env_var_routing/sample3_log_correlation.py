#!/usr/bin/env python3
"""I-1 sample 3: combine routing with structured_log so each routing
decision becomes a queryable event in the NDJSON stream.

Run:
    AIPL_DIST_ENABLE=1 AIPL_ROUTE="Greeter:fast,Bench:slow" \\
    AIPL_DIST_LOG_FILE=/tmp/route_audit.ndjson python3 sample3_log_correlation.py
    cat /tmp/route_audit.ndjson
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "..", "..", "src", "python-aipl")))
import aipl_dist  # noqa: E402

def route_with_audit(name: str) -> str:
    tag = aipl_dist.route_for(name)
    aipl_dist.log_event("route_resolution", actor=name, tag=tag or "default")
    return tag or "default"

for actor in ["Greeter", "Bench", "Unknown1", "Unknown2", "Greeter"]:
    placement = route_with_audit(actor)
    print(f"  {actor:10s} -> {placement}")
print()
print("→ check the log file for 5 route_resolution events.")
