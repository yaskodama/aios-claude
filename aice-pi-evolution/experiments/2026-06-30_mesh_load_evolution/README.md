# Mesh load-distribution evolution (soft-Xinu mesh, Mac)

Evolve the **parallel load distribution** of an N-Queens workload across a mesh
of soft-Xinu worker nodes, minimising **makespan** (the slowest node's finish
time). Same actor HTTP wire protocol as a real Embedded-Xinu board, so the
orchestrator drives soft nodes on Mac today and real Pi boards later — only the
`host:port` list changes.

## Pieces

| File | Role |
|------|------|
| `nq_worker.tmpl.abcl` | One mesh node. Exposes actor `worker.solve(n,k)` → N-Queens subtree count for row-0 column `k`. `web_listen(__PORT__)` (rewritten per node). |
| `mesh.py` | Spawn / drive M worker nodes (`localhost:9101..`). Library + `python3 mesh.py start <M>`. |
| `evolve.py` | Measure per-column costs on one node, run a GA over the column→node assignment, compare vs naive / round-robin / greedy-LPT baselines, then **live-validate** the champion by dispatching it in parallel across the real mesh. |
| `RESULTS.md` | Latest run summary (auto-written by `evolve.py`). |

## Run

```
python3 evolve.py [N=11] [M=4] [GEN=60]
```

## Why it's not trivial

N-Queens columns are **non-uniform** in cost (centre columns explore far bigger
subtrees than edges), so the obvious contiguous equal-block split is unbalanced
and its makespan is dragged out by the heaviest block. The GA learns a balanced
column→node assignment; the modelled makespan is confirmed against real
parallel wall-clock on the live mesh.

## Result (N=10, M=4)

GA cut makespan ~9% below the naive contiguous split (speed-up x3.48 vs x3.17),
live-validated. Larger N widens the cost spread and the gap. See `RESULTS.md`.

## Next

- Scale to more nodes / larger N; add **work-stealing** (idle node pulls a
  pending column) as an evolvable axis alongside static assignment.
- Mix soft nodes with real Pi boards (rpi3/4/5) by adding their `host:port`.
