#!/usr/bin/env python3
"""I-1 sample 2: actor names not in AIPL_ROUTE return None.

Demonstrates the lookup miss path of `route_for()` — useful for
checking whether to apply a default placement policy.

Run:
    AIPL_DIST_ENABLE=1 AIPL_ROUTE="A:fast,B:slow" python3 sample2_no_match.py
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "..", "..", "src", "python-aipl")))
import aipl_dist  # noqa: E402

for name in ["A", "B", "C", "Unknown"]:
    tag = aipl_dist.route_for(name)
    print(f"  route_for({name!r:10s}) = {tag!r}")
print()
print(f"  parse_route_table('X:1,bad:no:colon,Y:2') = "
      f"{aipl_dist.parse_route_table('X:1,bad:no:colon,Y:2')}")
