#!/usr/bin/env python3
"""I-2 sample 3: thread-safety stress test.

Spawns 10 threads that each emit 50 events.  Counts lines in the
output file and verifies no bytes interleave (each line parses as
valid JSON with a unique `thread_id` × `seq` pair).

Run:
    AIPL_DIST_ENABLE=1 AIPL_DIST_LOG_FILE=/tmp/stress.ndjson python3 sample3_multi_thread.py
"""
import json, os, sys, threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "..", "..", "src", "python-aipl")))
import aipl_dist  # noqa: E402

N_THREADS, N_EVENTS = 10, 50
path = os.environ.get("AIPL_DIST_LOG_FILE")
if path and os.path.exists(path):
    os.unlink(path)

def worker(tid):
    for seq in range(N_EVENTS):
        aipl_dist.log_event("stress", thread_id=tid, seq=seq)

threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
for t in threads: t.start()
for t in threads: t.join()

if not path:
    print("(no AIPL_DIST_LOG_FILE — set it to verify)")
    sys.exit(0)

with open(path) as f:
    lines = f.readlines()
print(f"wrote {len(lines)} lines (expected {N_THREADS*N_EVENTS})")
seen = set()
for line in lines:
    rec = json.loads(line)
    seen.add((rec["thread_id"], rec["seq"]))
print(f"unique (thread, seq) pairs: {len(seen)}")
assert len(seen) == N_THREADS * N_EVENTS, "lost events under concurrency"
print("OK — no events lost, no byte interleaving.")
