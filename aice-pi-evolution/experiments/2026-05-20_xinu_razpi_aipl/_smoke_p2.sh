#!/usr/bin/env bash
# P2 smoke — verify AIPL priority(high|normal|low) maps to Xinu prio.
#
# Sample: abclc/Priority3Xinu.abcl
#   - HiWorker priority(high)   -> prio 30
#   - MdWorker (default normal) -> prio 20
#   - LoWorker priority(low)    -> prio 10
#   - Controller (default)      -> prio 20, sends 10 ticks to each
#
# Acceptance (3 assertions per spec, +1 regression):
#   (1) getprio() agrees with AIPL setting for all 3 workers
#       — line "[aipl] prio class=… want=W got=G" must have W==G
#       — and the constants must be (30, 20, 10) for (Hi, Md, Lo)
#   (2) Hi actor preempts Lo
#       — last [aipl] HIGH-tick line number < first [aipl] LOW-tick
#         (because Lo can't start while Hi+Controller are ready)
#   (3) no starvation — Lo eventually drains all 10 of its messages
#       — count of "[aipl] LOW-tick" >= 10
#   (4) no panic / FATAL / Exception
set -u
cd "$(dirname "$0")/../../.."
ROOT=$PWD
XINU=/Users/kodamay/projects/xinu-raz/xinu
COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi-

dune build src/aipl2c.exe >/tmp/_p2_build.log 2>&1 || {
  echo "FAIL: dune build aipl2c"; tail /tmp/_p2_build.log; exit 1; }

src=Priority3Xinu
echo "=== $src ==="
./_build/default/src/aipl2c.exe abclc/${src}.abcl \
    -o /tmp/_p2_${src}.c --xinu --max-msgs 0 \
    > /tmp/_p2_${src}.aipl2c.log 2>&1
[ -f /tmp/_p2_${src}.c ] || {
  echo "  FAIL aipl2c"; cat /tmp/_p2_${src}.aipl2c.log; exit 1; }
cp /tmp/_p2_${src}.c "$XINU/apps/abcl_program.c"

( cd "$XINU/compile" \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT clean >/dev/null 2>&1 \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT DEBUG=-DAIPL_AUTOSTART \
     >/tmp/_p2_${src}.build.log 2>&1 ) \
  || { echo "  FAIL link"; tail /tmp/_p2_${src}.build.log; exit 1; }

# 6 sec should be plenty for 95 dispatches.
timeout 6 qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
      -kernel "$XINU/compile/xinu.elf" -nographic -no-reboot \
      >/tmp/_p2_${src}.qemu.log 2>&1 || true

LOG=/tmp/_p2_${src}.qemu.log
PASS=0; FAIL=0

# (1) getprio agreement — extract want/got pairs and check matches.
echo "  -- assertion (1) prio assignment --"
mismatch=$(grep -aE '\[aipl\] prio class=' "$LOG" \
           | sed -nE 's/.*want=([0-9]+) got=([0-9]+).*/\1 \2/p' \
           | awk '$1 != $2 {print}')
need_hi=$(grep -aE '\[aipl\] prio class=HiWorker .*want=30 got=30' "$LOG" | wc -l | tr -d ' ')
need_md=$(grep -aE '\[aipl\] prio class=MdWorker .*want=20 got=20' "$LOG" | wc -l | tr -d ' ')
need_lo=$(grep -aE '\[aipl\] prio class=LoWorker .*want=10 got=10' "$LOG" | wc -l | tr -d ' ')
if [ -z "$mismatch" ] && [ "$need_hi" -ge 1 ] && [ "$need_md" -ge 1 ] && [ "$need_lo" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (1) Hi=30 Md=20 Lo=10 — getprio matches in all 3"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (1) hi=$need_hi md=$need_md lo=$need_lo  mismatches:"
  echo "$mismatch" | head -5
  grep -aE '\[aipl\] prio class=' "$LOG" | head -10
fi

# (2) Preemption: last HIGH line < first LOW line.
echo "  -- assertion (2) preemption --"
last_hi=$(grep -an '\[aipl\] HIGH-tick' "$LOG" | tail -1 | cut -d: -f1)
first_lo=$(grep -an '\[aipl\] LOW-tick'  "$LOG" | head -1 | cut -d: -f1)
if [ -n "$last_hi" ] && [ -n "$first_lo" ] && [ "$last_hi" -lt "$first_lo" ]; then
  PASS=$((PASS+1))
  echo "  PASS (2) last-HIGH@${last_hi} < first-LOW@${first_lo}"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (2) last-HIGH=$last_hi first-LOW=$first_lo"
fi

# (3) No starvation: LoWorker drains all 30 of its messages.
echo "  -- assertion (3) no starvation --"
n_hi=$(grep -ac '\[aipl\] HIGH-tick' "$LOG")
n_md=$(grep -ac '\[aipl\] MID-tick'  "$LOG")
n_lo=$(grep -ac '\[aipl\] LOW-tick'  "$LOG")
if [ "$n_hi" -ge 10 ] && [ "$n_md" -ge 10 ] && [ "$n_lo" -ge 10 ]; then
  PASS=$((PASS+1))
  echo "  PASS (3) Hi=$n_hi Md=$n_md Lo=$n_lo — all >= 10"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (3) Hi=$n_hi Md=$n_md Lo=$n_lo — expected each >= 10"
fi

# (4) No panic.
echo "  -- assertion (4) no panic --"
if grep -qE 'panic|FATAL|Exception' "$LOG"; then
  FAIL=$((FAIL+1)); echo "  FAIL (4) panic observed"
  grep -E 'panic|FATAL|Exception' "$LOG" | head -2
else
  PASS=$((PASS+1)); echo "  PASS (4) no panic"
fi

echo
echo "============================"
echo "P2 smoke: PASS=$PASS FAIL=$FAIL  (expected PASS=4 FAIL=0)"
[ $FAIL -eq 0 ]
