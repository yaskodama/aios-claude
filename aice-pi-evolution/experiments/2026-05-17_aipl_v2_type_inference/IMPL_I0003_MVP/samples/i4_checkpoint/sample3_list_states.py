#!/usr/bin/env python3
"""I-4 sample 3: save many actors, then list them all.

Demonstrates list_actor_states() as a recovery-time inventory tool.

Run:
    rm -rf /tmp/aipl_ck_list
    AIPL_DIST_ENABLE=1 AIPL_DIST_CHECKPOINT_DIR=/tmp/aipl_ck_list python3 sample3_list_states.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "..", "..", "src", "python-aipl")))
import aipl_dist  # noqa: E402

actors = ["Reviewer1", "Reviewer2", "Builder", "Evaluator", "Logger"]
for i, a in enumerate(actors):
    aipl_dist.save_actor_state(a, {"role": a, "tick": i})
states = aipl_dist.list_actor_states()
print(f"checkpointed actors ({len(states)}):")
for name, path in sorted(states.items()):
    st = aipl_dist.restore_actor_state(name)
    print(f"  {name:12s} {path}  state={st}")
