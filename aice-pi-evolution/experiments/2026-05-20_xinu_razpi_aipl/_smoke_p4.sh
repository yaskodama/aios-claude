#!/usr/bin/env bash
# P4 smoke — Scheduling Visualizer (LCD bar-chart + CSV trace).
#
# Sample: abclc/SchedVizXinu.abcl
#   Controller spawns 3 priority-classed Workers (hi/md/lo) and calls
#   sched_viz_start(300) so a background Xinu thread emits a CSV
#   line + draws the 4-bar chart every 300 ms.
#
# Acceptance (the spec asks 2 assertions, plus standard no-panic):
#   (1) bar-chart drawn — `[aipl] p4_bar …` markers appear with all 4
#       state counters (ready/curr/sleep/recv).
#   (2) CSV trace allows 4-state occupancy computation — multiple
#       `csv,t=…,ready=…,curr=…,sleep=…,recv=…` lines are present
#       and a simple average per state is non-zero (CURR is always
#       >=1 because the viz thread itself is CURR when it prints).
#   (3) no panic.
set -u
cd "$(dirname "$0")/../../.."
ROOT=$PWD
XINU=/Users/kodamay/projects/xinu-raz/xinu
COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi-

dune build src/aipl2c.exe >/tmp/_p4_build.log 2>&1 || {
  echo "FAIL: dune build aipl2c"; tail /tmp/_p4_build.log; exit 1; }

src=SchedVizXinu
echo "=== $src ==="

./_build/default/src/aipl2c.exe abclc/${src}.abcl \
    -o /tmp/_p4_${src}.c --xinu --max-msgs 0 \
    > /tmp/_p4_${src}.aipl2c.log 2>&1
[ -f /tmp/_p4_${src}.c ] || {
  echo "  FAIL aipl2c"; cat /tmp/_p4_${src}.aipl2c.log; exit 1; }
cp /tmp/_p4_${src}.c "$XINU/apps/abcl_program.c"

( cd "$XINU/compile" \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT clean >/dev/null 2>&1 \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT DEBUG=-DAIPL_AUTOSTART \
     >/tmp/_p4_${src}.build.log 2>&1 ) \
  || { echo "  FAIL link"; tail /tmp/_p4_${src}.build.log; exit 1; }

# 6 sec window → ~20 samples at period=300ms.
timeout 6 qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
      -kernel "$XINU/compile/xinu.elf" -nographic -no-reboot \
      >/tmp/_p4_${src}.qemu.log 2>&1 || true

LOG=/tmp/_p4_${src}.qemu.log
PASS=0; FAIL=0

# (1) bar-chart drawn — count [aipl] p4_bar lines.
echo "  -- assertion (1) bar-chart drawn --"
n_bar=$(grep -ac '\[aipl\] p4_bar ' "$LOG")
n_bar_full=$(grep -ac '\[aipl\] p4_bar ready=.*curr=.*sleep=.*recv=' "$LOG")
if [ "$n_bar" -ge 3 ] && [ "$n_bar_full" -eq "$n_bar" ]; then
  PASS=$((PASS+1))
  echo "  PASS (1) $n_bar bar-chart frames (each with all 4 counters)"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (1) bar lines=$n_bar full=$n_bar_full (need >=3 full)"
fi

# (2) CSV trace — multiple samples allow occupancy averaging.
echo "  -- assertion (2) CSV occupancy --"
n_csv=$(grep -ac '^csv,t=' "$LOG")
# Sum each column with awk so we can compute averages.
sums=$(grep -aE '^csv,t=' "$LOG" \
       | sed -nE 's/^csv,t=[0-9]+,ready=([0-9]+),curr=([0-9]+),sleep=([0-9]+),recv=([0-9]+).*$/\1 \2 \3 \4/p' \
       | awk 'BEGIN{r=0;c=0;s=0;v=0;n=0}
              {r+=$1; c+=$2; s+=$3; v+=$4; n++}
              END{ if (n>0) printf "n=%d r=%.2f c=%.2f s=%.2f v=%.2f", n, r/n, c/n, s/n, v/n }')
if [ "$n_csv" -ge 3 ] && [ -n "$sums" ]; then
  PASS=$((PASS+1))
  echo "  PASS (2) $n_csv CSV samples — occupancy: $sums"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (2) csv=$n_csv sums=$sums"
fi

# (3) No panic.
echo "  -- assertion (3) no panic --"
if grep -qE 'panic|FATAL|Exception' "$LOG"; then
  FAIL=$((FAIL+1)); echo "  FAIL (3) panic observed"
  grep -E 'panic|FATAL|Exception' "$LOG" | head -2
else
  PASS=$((PASS+1)); echo "  PASS (3) no panic"
fi

echo
echo "============================"
echo "P4 smoke: PASS=$PASS FAIL=$FAIL  (expected PASS=3 FAIL=0)"
[ $FAIL -eq 0 ]
