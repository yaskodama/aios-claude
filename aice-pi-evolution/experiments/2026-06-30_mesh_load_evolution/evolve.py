#!/usr/bin/env python3
"""evolve.py — evolve the parallel load-distribution of an N-Queens workload
across a soft-Xinu mesh, minimising makespan (slowest node's finish time).

Workload  : count N-Queens(N) solutions, decomposed by row-0 column k (N units).
            Unit costs are *non-uniform* (centre columns explore far bigger
            subtrees than edge columns) — so an equal contiguous split is bad.
Mesh      : M soft-Xinu worker nodes (mesh.py), each runs its assigned columns
            sequentially; nodes run in parallel.  makespan = max_node sum(cost).
Evolution : a GA over the assignment vector a[k] in 0..M-1 minimises modelled
            makespan from *measured* per-column costs.  The champion is then
            re-dispatched live across the real mesh to confirm the speed-up.

Run:  python3 evolve.py [N=11] [M=4] [GEN=60]
"""
import random
import sys
import threading
import time

import mesh
from aipl_remote import remote_call_sync

random.seed(1234)  # Math.random() is unavailable in workflow scripts; fixed seed here is fine


# ---------------------------------------------------------------- cost model
def measure_costs(host, n, reps=2):
    """Median wall-clock ms to solve column k on one warm node, for every k."""
    costs, sols = [], []
    for k in range(n):
        ts = []
        sol = None
        for _ in range(reps):
            t0 = time.perf_counter()
            sol = remote_call_sync(host, "worker", "solve", [n, k], timeout_s=60)
            ts.append((time.perf_counter() - t0) * 1000.0)
        ts.sort()
        costs.append(ts[len(ts) // 2])
        sols.append(sol)
    return costs, sols


def makespan(assign, costs, m):
    load = [0.0] * m
    for k, node in enumerate(assign):
        load[node] += costs[k]
    return max(load), load


# ---------------------------------------------------------------- baselines
def naive_contiguous(n, m):
    """Split columns into M contiguous blocks — the obvious human split."""
    return [min(k * m // n, m - 1) for k in range(n)]


def round_robin(n, m):
    return [k % m for k in range(n)]


def greedy_lpt(costs, m):
    """Longest-Processing-Time: assign heaviest unit to lightest node. ~4/3-opt."""
    order = sorted(range(len(costs)), key=lambda k: -costs[k])
    load = [0.0] * m
    assign = [0] * len(costs)
    for k in order:
        node = min(range(m), key=lambda j: load[j])
        assign[k] = node
        load[node] += costs[k]
    return assign


# ---------------------------------------------------------------- GA
def evolve(costs, m, generations, pop_size=80, seeds=None):
    n = len(costs)
    fit = lambda a: -makespan(a, costs, m)[0]
    pop = []
    for s in (seeds or []):
        pop.append(list(s))
    while len(pop) < pop_size:
        pop.append([random.randrange(m) for _ in range(n)])

    best = max(pop, key=fit)
    for _ in range(generations):
        pop.sort(key=fit, reverse=True)
        elite = pop[: max(2, pop_size // 10)]
        nxt = list(elite)
        while len(nxt) < pop_size:
            pa = max(random.sample(pop, 3), key=fit)
            pb = max(random.sample(pop, 3), key=fit)
            child = [pa[i] if random.random() < 0.5 else pb[i] for i in range(n)]
            # mutation: nudge a few units to another node
            for i in range(n):
                if random.random() < 0.10:
                    child[i] = random.randrange(m)
            nxt.append(child)
        pop = nxt
        cand = max(pop, key=fit)
        if fit(cand) > fit(best):
            best = cand
    return best


# ---------------------------------------------------------------- live eval
def live_makespan(ports, assign, n):
    """Dispatch each node's columns sequentially in parallel threads; return
    real wall-clock makespan (ms) and per-node finish times."""
    buckets = [[] for _ in ports]
    for k, node in enumerate(assign):
        buckets[node].append(k)
    finish = [0.0] * len(ports)

    def run_node(j):
        host = f"localhost:{ports[j]}"
        t0 = time.perf_counter()
        for k in buckets[j]:
            remote_call_sync(host, "worker", "solve", [n, k], timeout_s=60)
        finish[j] = (time.perf_counter() - t0) * 1000.0

    threads = [threading.Thread(target=run_node, args=(j,)) for j in range(len(ports))]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = (time.perf_counter() - t0) * 1000.0
    return wall, finish


# ---------------------------------------------------------------- main
def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 11
    m = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    gen = int(sys.argv[3]) if len(sys.argv) > 3 else 60

    print(f"=== mesh load-distribution evolution: N-Queens N={n}, M={m} nodes ===")
    procs, ports = mesh.start_mesh(m)
    print(f"mesh up: {['localhost:%d' % p for p in ports]}")
    try:
        host0 = f"localhost:{ports[0]}"
        print("measuring per-column costs on one node ...")
        costs, sols = measure_costs(host0, n)
        total_sol = sum(sols)
        total_ms = sum(costs)
        print(f"  N-Queens({n}) total solutions = {total_sol}")
        print(f"  serial (1 node) modelled time = {total_ms:.0f} ms")
        print("  per-column cost ms: " +
              " ".join(f"{c:.0f}" for c in costs))
        ideal = total_ms / m
        print(f"  perfect-balance lower bound  = {ideal:.0f} ms  "
              f"(ideal speed-up x{m})")

        strategies = {
            "naive-contiguous": naive_contiguous(n, m),
            "round-robin":      round_robin(n, m),
            "greedy-LPT":       greedy_lpt(costs, m),
        }
        seeds = list(strategies.values())
        evolved = evolve(costs, m, gen, seeds=seeds)
        strategies["evolved-GA"] = evolved

        print("\n--- modelled makespan (from measured costs) ---")
        rows = []
        for name, a in strategies.items():
            mk, load = makespan(a, costs, m)
            spd = total_ms / mk
            rows.append((name, mk, spd, load))
            print(f"  {name:16s} makespan={mk:7.0f} ms  speed-up x{spd:4.2f}  "
                  f"loads=[{' '.join('%.0f' % x for x in load)}]")

        print("\n--- LIVE validation on the real mesh (parallel dispatch) ---")
        for name in ("naive-contiguous", "evolved-GA"):
            wall, finish = live_makespan(ports, strategies[name], n)
            print(f"  {name:16s} live wall={wall:7.0f} ms  "
                  f"node-finish=[{' '.join('%.0f' % x for x in finish)}]")

        # write a short results file
        best_mk = makespan(evolved, costs, m)[0]
        naive_mk = makespan(strategies["naive-contiguous"], costs, m)[0]
        with open("RESULTS.md", "w") as f:
            f.write(f"# Mesh load-distribution evolution — N={n}, M={m}\n\n")
            f.write(f"- N-Queens({n}) solutions: **{total_sol}**\n")
            f.write(f"- serial (1 node): {total_ms:.0f} ms; "
                    f"perfect-balance bound: {ideal:.0f} ms (x{m})\n")
            f.write(f"- per-column cost ms: {[round(c) for c in costs]}\n\n")
            f.write("| strategy | makespan ms | speed-up |\n|---|---|---|\n")
            for name, a in strategies.items():
                mk, _ = makespan(a, costs, m)
                f.write(f"| {name} | {mk:.0f} | x{total_ms / mk:.2f} |\n")
            f.write(f"\nGA cut makespan **{(1 - best_mk / naive_mk) * 100:.0f}%** "
                    f"below the naive contiguous split.\n")
        print("\nwrote RESULTS.md")
    finally:
        mesh.stop_mesh(procs)
        print("mesh stopped")


if __name__ == "__main__":
    main()
