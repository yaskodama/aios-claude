#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Distributed N-Queens benchmark across a Mac AIPL runtime and a 3-board Xinu cluster.

Work is split by the *first-queen column*: the N solutions of the board are the
disjoint union of the sub-counts for first-queen placed in column 0..N-1.

Compute nodes
-------------
  * Mac    : the AIPL interpreter (Py-I runtime) running nqueens_subset.abcl
             over a contiguous column range [c0,c1).
  * rpi3/4/5: native Xinu kernels exposing GET /nqpart?n=N&c0=A&c1=B which
             SMP-parallelises the columns [A,B) across that board's cores and
             replies  "nqueens-partial n=.. c0=.. c1=.. solutions=.. ms=.. cores=..".

Configurations (the four the user asked for)
--------------------------------------------
  mac            : Mac AIPL computes all N columns by itself.
  mac+rpi3       : columns split equally over {rpi3}            (Mac = orchestrator).
  mac+rpi3+rpi4  : columns split equally over {rpi3,rpi4}.
  mac+rpi3+rpi4+rpi5 : columns split equally over {rpi3,rpi4,rpi5}.

Because the Mac AIPL interpreter is ~10^4x slower than a single board, in any
multi-board configuration the Mac contributes 0 columns and acts purely as the
orchestrator (this is the honest, measured outcome — see the report). Columns are
split equally and contiguously over the active boards; each board runs ONE /nqpart
call so its internal SMP can parallelise its block across cores.

Wall-clock for a configuration = orchestrator-measured time from concurrent
dispatch until the last worker returns. The total solution count is the sum of the
partials and is verified against the known N-Queens value.
"""
import argparse, concurrent.futures as cf, json, os, re, subprocess, sys, tempfile, time, urllib.request

REPO     = os.path.expanduser("~/ocaml-app/abclcp-project")
AIPL_MAIN= os.path.join(REPO, "src/python-aipl/aipl_main.py")
ABCL_TPL = os.path.expanduser("~/projects/xinu-rpi5/bench/nqueens_subset.abcl")

BOARDS = {                       # name -> (host, port)
    "rpi3": ("192.168.3.50", 8080),
    "rpi4": ("192.168.3.100", 80),
    "rpi5": ("192.168.3.101", 80),
}

# OEIS A000170 — number of solutions to the N-queens problem.
KNOWN = {1:1, 2:0, 3:0, 4:2, 5:10, 6:4, 7:40, 8:92, 9:352, 10:724,
         11:2680, 12:14200, 13:73712, 14:365596, 15:2279184}

CONFIGS = [
    ("mac",                []),
    ("mac+rpi3",           ["rpi3"]),
    ("mac+rpi3+rpi4",      ["rpi3", "rpi4"]),
    ("mac+rpi3+rpi4+rpi5", ["rpi3", "rpi4", "rpi5"]),
]


# ----------------------------------------------------------------------- workers
def board_nqpart(board, n, c0, c1, timeout=600, retries=4):
    host, port = BOARDS[board]
    url = "http://%s:%d/nqpart?n=%d&c0=%d&c1=%d" % (host, port, n, c0, c1)
    last = None
    for attempt in range(retries):
        try:
            t0 = time.perf_counter()
            with urllib.request.urlopen(url, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
            wall = time.perf_counter() - t0
            break
        except Exception as e:        # transient network blip (e.g. DHCP renew) -> retry
            last = e
            time.sleep(1.5 * (attempt + 1))
    else:
        raise RuntimeError("%s unreachable after %d tries: %s" % (board, retries, last))
    sol = re.search(r"solutions=(\d+)", body)
    ms  = re.search(r"ms=(\d+)", body)
    cor = re.search(r"cores=(\d+)", body)
    if not sol:
        raise RuntimeError("%s bad response: %r" % (board, body[:160]))
    return {"worker": board, "c0": c0, "c1": c1,
            "solutions": int(sol.group(1)),
            "dev_ms": int(ms.group(1)) if ms else None,
            "cores": int(cor.group(1)) if cor else None,
            "wall_s": wall}


def mac_aipl(n, c0, c1, timeout=2000):
    if c0 >= c1:
        return {"worker": "mac", "c0": c0, "c1": c1, "solutions": 0,
                "dev_ms": 0, "cores": 1, "wall_s": 0.0}
    src = open(ABCL_TPL).read()
    src = re.sub(r"(?m)^var\s+N\b.*?;",       "var N = %d;"       % n,  src, count=1)
    src = re.sub(r"(?m)^var\s+K_FIRST\b.*?;", "var K_FIRST = %d;" % c0, src, count=1)
    src = re.sub(r"(?m)^var\s+K_LAST\b.*?;",  "var K_LAST = %d;"  % c1, src, count=1)
    tf = tempfile.NamedTemporaryFile("w", suffix=".abcl", delete=False)
    tf.write(src); tf.close()
    env = dict(os.environ); env["AIPL_AI_PROVIDER"] = "mock"
    t0 = time.perf_counter()
    out = subprocess.check_output([sys.executable, AIPL_MAIN, tf.name],
                                  env=env, text=True, timeout=timeout)
    wall = time.perf_counter() - t0
    os.unlink(tf.name)
    sub = re.search(r"subtotal=(\d+)", out)
    dev = re.search(r"elapsed_ms=(\d+)", out)
    return {"worker": "mac", "c0": c0, "c1": c1,
            "solutions": int(sub.group(1)) if sub else 0,
            "dev_ms": int(dev.group(1)) if dev else None,
            "cores": 1, "wall_s": wall}


# ------------------------------------------------------------------- assignment
def split_equal(n, k):
    """Split [0,n) into k contiguous near-equal ranges. Returns list of (c0,c1)."""
    base, rem = divmod(n, k)
    out, c = [], 0
    for i in range(k):
        w = base + (1 if i < rem else 0)
        out.append((c, c + w)); c += w
    return out


def warmup(boards):
    """Wake each board's HTTP server / WiFi connection with a tiny request so the
    first *timed* call is not penalised by webactor cold-start latency (the single
    -threaded rpi3 webactor can stall ~35s on its first post-idle round-trip)."""
    for b in boards:
        try:
            board_nqpart(b, 4, 0, 4, timeout=60)
        except Exception:
            pass


def run_config(name, boards, n):
    tasks = []   # (callable, label)
    if not boards:                       # mac alone — all columns
        tasks.append((lambda: mac_aipl(n, 0, n), "mac"))
    else:
        warmup(boards)                   # pre-warm board connections before timing
        for (c0, c1), b in zip(split_equal(n, len(boards)), boards):
            tasks.append(((lambda b=b, c0=c0, c1=c1: board_nqpart(b, n, c0, c1)), b))

    t0 = time.perf_counter()
    parts = []
    with cf.ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        futs = [ex.submit(fn) for fn, _ in tasks]
        for f in futs:
            parts.append(f.result())
    wall = time.perf_counter() - t0

    total = sum(p["solutions"] for p in parts)
    ok = (KNOWN.get(n) == total)
    return {"config": name, "n": n, "wall_s": wall, "total": total,
            "known": KNOWN.get(n), "correct": ok, "parts": parts}


# -------------------------------------------------------------------------- cli
def best_of(name, boards, n, reps):
    """Run a config `reps` times, keep the trial with the smallest wall-clock
    (best-of-N factors out network/OS jitter — standard benchmark practice).
    The Mac-alone config is CPU-bound and deterministic, so it runs once."""
    runs = 1 if not boards else reps
    best = None
    for i in range(runs):
        if i:
            time.sleep(0.5)   # let the single-threaded rpi3 webactor settle
        r = run_config(name, boards, n)
        if best is None or r["wall_s"] < best["wall_s"]:
            best = r
    best["reps"] = runs
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nmin", type=int, default=8)
    ap.add_argument("--nmax", type=int, default=12)
    ap.add_argument("--mac-nmax", type=int, default=11,
                    help="skip the mac-alone config above this N (it is too slow)")
    ap.add_argument("--reps", type=int, default=1,
                    help="trials per board config; report the minimum wall-clock")
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "results.json"))
    args = ap.parse_args()

    results = []
    for n in range(args.nmin, args.nmax + 1):
        for name, boards in CONFIGS:
            if not boards and n > args.mac_nmax:
                print("[skip] %-20s N=%d (mac-alone too slow)" % (name, n)); continue
            try:
                r = best_of(name, boards, n, args.reps)
            except Exception as e:
                print("[FAIL] %-20s N=%d : %s" % (name, n, e)); continue
            results.append(r)
            mark = "OK " if r["correct"] else "BAD"
            print("[%s] %-20s N=%2d  wall=%8.3fs  total=%-8d (known=%s)"
                  % (mark, name, n, r["wall_s"], r["total"], r["known"]))
            for p in r["parts"]:
                print("        %-5s cols[%d,%d) sol=%-7d dev_ms=%s cores=%s wall=%.3fs"
                      % (p["worker"], p["c0"], p["c1"], p["solutions"],
                         p["dev_ms"], p["cores"], p["wall_s"]))
            with open(args.out, "w") as f:
                json.dump(results, f, indent=2)
    print("\nwrote", args.out, "(%d rows)" % len(results))


if __name__ == "__main__":
    main()
