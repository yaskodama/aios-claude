#!/usr/bin/env python3
# run_dining_rpi4.py — distributed dining philosophers, 3 on the Mac + 2 on the
# Pi4 (xinu-rpi4 @ 192.168.3.100), DYNAMIC variant:
#
#   Xinu boots with 0 philosophers.  The Mac translates the philosopher AIPL to
#   C, POSTs the source to Xinu's /actor/load, where the on-device cc JIT
#   compiles it and main() spawns the 2 resident philosopher actors.  The Mac
#   then runs the dinner: it owns all 5 forks (fork arbitration = mutual
#   exclusion, deadlock-free by taking the lower-numbered fork first) and the 3
#   local philosophers, and drives the 2 Xinu philosophers over HTTP
#   /actor/send (m=eat / m=think) — their meal counters live in AIPL on the Pi.
#
# Usage: python3 run_dining_rpi4.py [meals_each]   (default 5)

import sys, time, subprocess, urllib.request, urllib.parse, os

HOST   = "192.168.3.100"
PROJ   = "/Users/kodamay/ocaml-app/abclcp-project"
ABCL   = os.path.join(PROJ, "aice-pi-evolution/experiments/2026-05-29_dining_rpi4/xinu_phil.abcl")
CSRC   = "/tmp/xinu_phil.c"
MEALS  = int(sys.argv[1]) if len(sys.argv) > 1 else 5

# Seats 0..4 around the table; philosopher i shares fork i (left) and fork
# (i+1)%5 (right).  Seats 3 and 4 are the Xinu (AIPL/JIT) diners -> Xinu actor
# ids 0 and 1.  Seats 0,1,2 are local (Mac) diners.
XINU_SEATS = {3: 0, 4: 1}     # table seat -> Xinu resident actor id

def http(path, data=None, timeout=15):
    url = "http://%s%s" % (HOST, path)
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace").strip()

def send(seat, method):
    """Drive a Xinu philosopher (returns its AIPL-side meal count as int)."""
    aid = XINU_SEATS[seat]
    body = http("/actor/send?to=%d&m=%s" % (aid, method))
    try:    return int(body.strip().split()[0])
    except: return -1

# ---- 1. DYNAMIC: translate AIPL -> C on the Mac, send to Xinu for JIT ----
print("=== [Mac] translate philosopher AIPL -> C (aipl2c --xinu-jit) ===")
subprocess.run(["dune", "exec", "src/aipl2c.exe", "--",
                ABCL, "--xinu-jit", "--no-typecheck", "-o", CSRC],
               cwd=PROJ, check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
src = open(CSRC, "rb").read()
print("    generated %d bytes of C" % len(src))

print("=== [Xinu] philosophers before load ===")
try:    print("   ", http("/api/actors", timeout=8))
except Exception as e: print("    (/api/actors:", e, ")")

print("=== [Mac->Xinu] POST source to /actor/load (Xinu JIT-compiles + spawns) ===")
print("    Xinu:", http("/actor/load", data=src))

# ---- 2. run the distributed dinner ----
print("\n=== dinner: 3 Mac + 2 Xinu philosophers, %d meals each ===" % MEALS)
forks  = [None] * 5           # fork f held by philosopher id, or None
local_meals = {0: 0, 1: 0, 2: 0}
done = set()
order = []                    # eat trace

def forks_of(i):
    a, b = i, (i + 1) % 5
    return (min(a, b), max(a, b))     # lower-numbered first => deadlock-free

rounds = 0
while len(done) < 5 and rounds < 10000:
    rounds += 1
    for i in range(5):
        if i in done:
            continue
        lo, hi = forks_of(i)
        if forks[lo] is None and forks[hi] is None:
            forks[lo] = forks[hi] = i                  # acquire both
            where = "Xinu" if i in XINU_SEATS else "Mac "
            if i in XINU_SEATS:
                n = send(i, "eat")                      # AIPL actor on the Pi eats
            else:
                local_meals[i] += 1; n = local_meals[i]
            order.append("P%d" % i)
            print("  [%s] P%d eating  (meal %d)" % (where, i, n))
            forks[lo] = forks[hi] = None                # put both down
            if n >= MEALS:
                done.add(i)
                if i in XINU_SEATS:
                    send(i, "think")                    # settle to thinking
                print("        P%d finished after %d meals" % (i, n))

# ---- 3. report ----
print("\n=== final meal counts ===")
for i in range(5):
    if i in XINU_SEATS:
        n = send(i, "count"); tag = "Xinu (AIPL/JIT, actor %d)" % XINU_SEATS[i]
    else:
        n = local_meals[i];  tag = "Mac  (Python)"
    print("  P%d: %2d meals   [%s]" % (i, n, tag))
print("\n  eat order (first 40):", " ".join(order[:40]))
print("  total eats:", len(order))
