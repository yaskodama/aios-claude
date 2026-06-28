#!/usr/bin/env python3
"""dining_mesh_bench.py — time the 5-philosopher dining problem (50 meals each,
250 total) under different *load distributions* across the 3-board Xinu WiFi
mesh (rpi3/rpi4/rpi5).

Faithful executor of dining_mesh.abcl: 5 forks are coordinator-side locks
(deadlock-free, acquired in global id order); 5 philosophers run concurrently;
each meal's physical "eat" is one real HTTP round-trip to the philosopher's
assigned board (GET /fb).  The variable under test is the philosopher->board
assignment.  We report wall-clock to the 250th meal, median of N runs.
"""
import sys, time, threading, urllib.request
from statistics import median

# host id -> (ip, port, path).  0 = coordinator-local (no network).
BOARDS = {
    3: ("192.168.3.50", 8080, "/fb"),   # rpi3 (xinu-raz)  ~13 ms, fragile under concurrency
    4: ("192.168.3.100", 80,  "/fb"),   # rpi4 (xinu-rpi4) ~115 ms (slow net polling)
    5: ("192.168.3.101", 80,  "/fb"),   # rpi5 (xinu-rpi5) ~20 ms
}
MEALS = 50
NPHIL = 5
# ring: philosopher i (0..4) uses forks i and (i+1)%5
LEFT  = lambda i: i
RIGHT = lambda i: (i + 1) % NPHIL

_fail = 0
_fail_lock = threading.Lock()

def eat(host, pace):
    """One physical meal on `host`: a real HTTP round-trip, with retry."""
    global _fail
    if host == 0:
        return  # coordinator-local meal: negligible compute
    ip, port, path = BOARDS[host]
    url = f"http://{ip}:{port}{path}"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=3.0) as r:
                r.read(64)
            if pace:
                time.sleep(pace)
            return
        except Exception:
            time.sleep(0.05 * (attempt + 1))
    with _fail_lock:
        _fail += 1  # gave up after 4 tries (counted, run continues)

def philosopher(i, host, forks, pace, barrier):
    lo, hi = sorted((LEFT(i), RIGHT(i)))
    barrier.wait()  # all philosophers start together
    for _ in range(MEALS):
        forks[lo].acquire(); forks[hi].acquire()
        eat(host, pace)
        forks[hi].release(); forks[lo].release()

def run_once(assign, pace):
    """assign: dict philosopher_index(0..4) -> host id.  Returns elapsed ms."""
    global _fail
    _fail = 0
    forks = [threading.Lock() for _ in range(NPHIL)]
    barrier = threading.Barrier(NPHIL)
    threads = [threading.Thread(target=philosopher,
                                args=(i, assign[i], forks, pace, barrier))
               for i in range(NPHIL)]
    t0 = time.time()
    for t in threads: t.start()
    for t in threads: t.join()
    return (time.time() - t0) * 1000.0, _fail

def recover_rpi3():
    """rpi3's single-threaded webactor un-wedges when polling stops; give it a
    breather and one gentle probe before a config that uses it."""
    time.sleep(2.0)
    try:
        urllib.request.urlopen("http://192.168.3.50:8080/fb", timeout=6.0).read(16)
    except Exception:
        pass

# (name, assignment dict, human description, pace seconds for rpi3-heavy configs)
def cfg(name, hosts, desc, pace=0.0):
    return (name, {i: hosts[i] for i in range(NPHIL)}, desc, pace)

CONFIGS = [
    cfg("mac",        [0,0,0,0,0], "coordinator-local baseline (no boards)"),
    cfg("all_rpi4",   [4,4,4,4,4], "all 5 on rpi4 (slow RTT, single board)"),
    cfg("all_rpi5",   [5,5,5,5,5], "all 5 on rpi5 (fast RTT, single board)"),
    cfg("all_rpi3",   [3,3,3,3,3], "all 5 on rpi3 (fastest RTT but fragile)", pace=0.01),
    cfg("rpi45_3-2",  [4,4,4,5,5], "rpi4:3 rpi5:2 (2-board, slow-heavy)"),
    cfg("rpi45_2-3",  [4,4,5,5,5], "rpi4:2 rpi5:3 (2-board, fast-heavy)"),
    cfg("spread_2-2-1",[5,5,3,3,4], "rpi5:2 rpi3:2 rpi4:1 (3-board even)", pace=0.005),
    cfg("rtt_opt",    [5,5,5,3,3], "rpi5:3 rpi3:2, avoid slow rpi4 (predicted best)", pace=0.005),
]

def main():
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    out = open(sys.argv[2], "w") if len(sys.argv) > 2 else sys.stdout
    print(f"# dining-mesh benchmark: {NPHIL} phils x {MEALS} meals = {NPHIL*MEALS} meals/run, "
          f"{repeats} runs/config", file=out)
    print(f"# {'config':14s} {'median_ms':>10s} {'min':>8s} {'max':>8s} {'fails':>6s}  desc", file=out)
    results = {}
    for name, assign, desc, pace in CONFIGS:
        uses3 = any(h == 3 for h in assign.values())
        runs, fails = [], 0
        for k in range(repeats):
            if uses3:
                recover_rpi3()
            ms, f = run_once(assign, pace)
            runs.append(ms); fails += f
            print(f"  [{name}] run {k+1}/{repeats}: {ms:8.1f} ms  fails={f}",
                  file=sys.stderr)
        med = median(runs)
        results[name] = med
        print(f"  {name:14s} {med:10.1f} {min(runs):8.1f} {max(runs):8.1f} {fails:6d}  {desc}",
              file=out)
        out.flush()
    # rank board configs (exclude pure-local baseline) by median
    board_cfgs = {k: v for k, v in results.items() if k != "mac"}
    best = min(board_cfgs, key=board_cfgs.get)
    print(f"# fastest distribution (boards): {best}  ({results[best]:.1f} ms)", file=out)
    print(f"# coordinator-local floor: {results['mac']:.1f} ms", file=out)
    if out is not sys.stdout:
        out.close()
        print(f"\n==> fastest board distribution: {best} ({results[best]:.1f} ms); "
              f"floor(mac)={results['mac']:.1f} ms")

if __name__ == "__main__":
    main()
