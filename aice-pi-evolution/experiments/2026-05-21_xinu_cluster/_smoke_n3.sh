#!/bin/bash
# _smoke_n3.sh — Phase A host-side gate for N3 multi-Pi actor cluster.
#
# What this validates today (xinu-raz untouched while
# Xinu_KernelEvolution_Round1 is in progress on that tree):
#
#   A1. AIPL source `abclc/ClusterPingPongXinu.abcl` type-checks under
#       the OCaml HM inferer (`aipl2c --check`).
#   A2. The same source compiles to Xinu C (`aipl2c --xinu`) and the
#       generated .c contains extern declarations for the three new
#       builtins (cluster_send, cluster_node_id, cluster_size).
#   A3. The host-side bridge `cluster_bridge.py` correctly routes
#       XSEND lines between fake nodes — 7 assertions in
#       `_test_bridge.py`.
#
# Out of scope today (deferred until xinu-raz `apps/abcl_xinu_cluster.c`
# lands, which requires the parallel kernel-evolution work to settle):
#
#   B1. Full QEMU 2-node integration: build xinu-raz twice with
#       -DNODE_ID=0 and =1, run the bridge between two -serial tcp:
#       sessions, grep digests 80001 / 90002 from UART0 logs.
#
# Exit codes:
#   0 — all host-side assertions PASS
#   1 — any host-side assertion failed
#   2 — toolchain missing (aipl2c could not be built)

set -u
cd "$(dirname "$0")/../../.."   # → abclcp-project root

PROJ=$(pwd)
SAMPLE=$PROJ/abclc/ClusterPingPongXinu.abcl
GEN_C=/tmp/cluster_pingpong.c
BRIDGE=$PROJ/aice-pi-evolution/experiments/2026-05-21_xinu_cluster/cluster_bridge.py
BRIDGE_TEST=$PROJ/aice-pi-evolution/experiments/2026-05-21_xinu_cluster/_test_bridge.py

pass=0; fail=0; total=0
ok()   { pass=$((pass + 1)); total=$((total + 1)); printf "  PASS  %s\n" "$1"; }
bad()  { fail=$((fail + 1)); total=$((total + 1)); printf "  FAIL  %s\n" "$1"; [ -n "${2-}" ] && printf "        %s\n" "$2"; }
sect() { printf "\n[%s] %s\n" "$1" "$2"; }

# ── prerequisites ───────────────────────────────────────────────
sect "prep" "build aipl2c"
if ! dune build src/aipl2c.exe 2>/tmp/n3_build.log; then
  echo "FAIL: dune build src/aipl2c.exe (see /tmp/n3_build.log)"
  exit 2
fi
[ -x ./_build/default/src/aipl2c.exe ] || { echo "FAIL: aipl2c.exe missing"; exit 2; }

# ── A1: typecheck ───────────────────────────────────────────────
sect "A1" "aipl2c --check on $SAMPLE"
if ./_build/default/src/aipl2c.exe "$SAMPLE" --check >/tmp/n3_check.log 2>&1; then
  if grep -q "type error" /tmp/n3_check.log; then
    bad "ClusterPingPongXinu.abcl typechecks" "type error in /tmp/n3_check.log"
  else
    ok "ClusterPingPongXinu.abcl typechecks"
  fi
else
  bad "ClusterPingPongXinu.abcl typechecks" "see /tmp/n3_check.log"
fi

# ── A2: Xinu C generation ───────────────────────────────────────
sect "A2" "aipl2c --xinu codegen"
rm -f "$GEN_C"
if ./_build/default/src/aipl2c.exe "$SAMPLE" -o "$GEN_C" --xinu --max-msgs 0 \
     >/tmp/n3_gen.log 2>&1 && [ -s "$GEN_C" ]; then
  ok "Xinu C produced ($(wc -l < "$GEN_C") lines)"
else
  bad "Xinu C produced" "see /tmp/n3_gen.log"
fi

# ── A2.1: extern emission for the new builtins ──────────────────
# (cluster_size is declared in the sample header but not yet invoked by
#  Phase A — xinu-raz cluster.c will still ship it for Phase B/C.)
for sym in cluster_send cluster_node_id; do
  if grep -q "\\b${sym}\\b" "$GEN_C" 2>/dev/null; then
    ok "$sym referenced in generated C"
  else
    bad "$sym referenced in generated C" "grep miss in $GEN_C"
  fi
done

# ── A3: host bridge routing test ────────────────────────────────
sect "A3" "cluster_bridge.py routing (no QEMU needed)"
if python3 "$BRIDGE_TEST" >/tmp/n3_bridge.log 2>&1; then
  if grep -q "pass=7/7" /tmp/n3_bridge.log; then
    ok "_test_bridge.py: 7/7 routing assertions"
  else
    bad "_test_bridge.py: 7/7 routing assertions" \
        "$(grep -E 'pass=|FAIL' /tmp/n3_bridge.log | tail -3)"
  fi
else
  bad "_test_bridge.py exits 0" "see /tmp/n3_bridge.log"
fi

# ── deferred B1 (full QEMU integration) ─────────────────────────
sect "B1" "full 2-node QEMU integration — DEFERRED"
echo "  SKIP  needs xinu-raz apps/abcl_xinu_cluster.c (planned after"
echo "        Xinu_KernelEvolution_Round1 ramps down — see README.md)"

# ── summary ─────────────────────────────────────────────────────
echo ""
echo "==== n3-cluster host-side smoke summary ===="
echo "  total=$total  pass=$pass  fail=$fail"
[ "$fail" -eq 0 ]
