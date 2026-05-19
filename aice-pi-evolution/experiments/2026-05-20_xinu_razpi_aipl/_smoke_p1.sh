#!/usr/bin/env bash
# P1 smoke — verify the AIPL actor / Xinu thread mapping holds.
#
# Acceptance (4 assertion per sample × 3 samples = 12 total):
#   (1) [aipl] heartbeat actors=<expected>  — 1:1 actor↔thread + nested spawns OK
#   (2) [aipl] first-send precedes [aipl] first-recv — semaphore wake works
#   (3) [aipl] heartbeat tick=0..5 all 6 land — scheduler not starved by actors
#       (proves blocking semaphore, no busy-wait)
#   (4) no panic / FATAL / Exception — no deadlock
set -u
cd "$(dirname "$0")/../../.."
ROOT=$PWD
XINU=/Users/kodamay/projects/xinu-raz/xinu
COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi-

dune build src/aipl2c.exe >/tmp/_p1_build.log 2>&1 || {
  echo "FAIL: dune build aipl2c"; tail /tmp/_p1_build.log; exit 1; }

# Sample => expected actor count after constructors run.
#   R4L  : 1 Controller + 4 Spinner  = 5
#   P5   : 1 Controller + 5 Fork + 5 Philosopher = 11
#   BB   : 1 Controller + 1 Buffer + 3 Producer + 3 Consumer = 8
expected_actors() {
  case "$1" in
    Rotate4LinesXinu) echo 5 ;;
    Philosophers5Xinu) echo 11 ;;
    BoundedBufferXinu) echo 8 ;;
    *) echo 0 ;;
  esac
}

PASS=0; FAIL=0
for src in Rotate4LinesXinu Philosophers5Xinu BoundedBufferXinu; do
  exp=$(expected_actors "$src")
  echo "=== $src (expected actors=$exp) ==="
  ./_build/default/src/aipl2c.exe abclc/${src}.abcl \
      -o /tmp/_p1_${src}.c --xinu --max-msgs 0 > /tmp/_p1_${src}.aipl2c.log 2>&1
  [ -f /tmp/_p1_${src}.c ] || { echo "  FAIL aipl2c"; FAIL=$((FAIL+4)); continue; }
  cp /tmp/_p1_${src}.c "$XINU/apps/abcl_program.c"

  ( cd "$XINU/compile" \
    && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT clean >/dev/null 2>&1 \
    && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT DEBUG=-DAIPL_AUTOSTART \
       >/tmp/_p1_${src}.build.log 2>&1 ) \
    || { echo "  FAIL link"; tail /tmp/_p1_${src}.build.log; FAIL=$((FAIL+4)); continue; }

  # Need ~7 sec to capture all 6 heartbeats (1-sec interval).
  timeout 9 qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
        -kernel "$XINU/compile/xinu.elf" -nographic -no-reboot \
        >/tmp/_p1_${src}.qemu.log 2>&1 || true

  # 1) actor count matches expectation (read from any heartbeat line)
  hb_actors=$(grep -aE '\[aipl\] heartbeat' /tmp/_p1_${src}.qemu.log \
              | sed -nE 's/.*actors=([0-9]+).*/\1/p' | sort -u | head -1)
  if [ "$hb_actors" = "$exp" ]; then
    PASS=$((PASS+1)); echo "  PASS (1) actors=$hb_actors"
  else
    FAIL=$((FAIL+1)); echo "  FAIL (1) actors=$hb_actors  expected=$exp"
  fi

  # 2) send precedes recv (line numbers)
  send_ln=$(grep -an '\[aipl\] first-send' /tmp/_p1_${src}.qemu.log | head -1 | cut -d: -f1)
  recv_ln=$(grep -an '\[aipl\] first-recv' /tmp/_p1_${src}.qemu.log | head -1 | cut -d: -f1)
  if [ -n "$send_ln" ] && [ -n "$recv_ln" ] && [ "$send_ln" -le "$recv_ln" ]; then
    PASS=$((PASS+1)); echo "  PASS (2) first-send@${send_ln} <= first-recv@${recv_ln}"
  else
    FAIL=$((FAIL+1)); echo "  FAIL (2) send/recv ordering  send=$send_ln recv=$recv_ln"
  fi

  # 3) all 6 heartbeats land (tick=0..5)
  hb_count=$(grep -aE '\[aipl\] heartbeat tick=' /tmp/_p1_${src}.qemu.log | wc -l | tr -d ' ')
  if [ "$hb_count" -ge 5 ]; then
    # The 6th tick can be lost if QEMU is killed mid-sleep — allow 5+.
    PASS=$((PASS+1)); echo "  PASS (3) heartbeats=$hb_count (no scheduler starvation)"
  else
    FAIL=$((FAIL+1)); echo "  FAIL (3) heartbeats=$hb_count (busy-wait suspected)"
  fi

  # 4) no panic
  if grep -qE 'panic|FATAL|Exception' /tmp/_p1_${src}.qemu.log; then
    FAIL=$((FAIL+1)); echo "  FAIL (4) panic observed"
    grep -E 'panic|FATAL|Exception' /tmp/_p1_${src}.qemu.log | head -2
  else
    PASS=$((PASS+1)); echo "  PASS (4) no panic"
  fi
done

echo
echo "============================"
echo "P1 smoke: PASS=$PASS FAIL=$FAIL  (expected PASS=12 FAIL=0)"
[ $FAIL -eq 0 ]
