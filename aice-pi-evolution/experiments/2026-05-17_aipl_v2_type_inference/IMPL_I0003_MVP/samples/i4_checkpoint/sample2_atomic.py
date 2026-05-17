#!/usr/bin/env python3
"""I-4 sample 2: atomic save under concurrent updates.

Spawns 5 threads each rapidly overwriting the same actor's state.
Reads the final state — should be exactly one of the values written
(never a torn / partial JSON).

Run:
    rm -rf /tmp/aipl_ck_atomic
    AIPL_DIST_ENABLE=1 AIPL_DIST_CHECKPOINT_DIR=/tmp/aipl_ck_atomic python3 sample2_atomic.py
"""
import json, os, shutil, sys, threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "..", "..", "src", "python-aipl")))
import aipl_dist  # noqa: E402

d = aipl_dist.checkpoint_dir()
if not d:
    print("(no AIPL_DIST_CHECKPOINT_DIR set)"); sys.exit(0)

def writer(tid):
    for v in range(50):
        aipl_dist.save_actor_state("a", {"writer": tid, "value": v})

ts = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
for t in ts: t.start()
for t in ts: t.join()

# Final state must be a complete JSON record — no torn writes.
final = aipl_dist.restore_actor_state("a")
print(f"final state: {final}")
assert final is not None
assert "writer" in final and "value" in final
print("OK — atomic replace held under contention.")
