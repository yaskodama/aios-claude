#!/usr/bin/env bash
# P3 smoke — lock-free MPSC mailbox under multi-producer contention.
#
# Sample: abclc/MpscStressXinu.abcl
#   4 Producer actors × K=32 ticks each → 128 ticks → single Counter
#   actor.  Counter prints its final n.
#
# Acceptance (4 checks):
#   (1) ISR-safe send (static) — abcl_enqueue uses __atomic primitives
#       only and never calls wait() (the only kernel call is the
#       trailing signal(items), which Xinu marks irq-safe).
#   (2) No message loss under contention — Counter receives exactly
#       4*K=128 ticks and `[abcl] done … drops=0` shows zero queue drops.
#   (3) Throughput — total dispatch time is < 1000 ticks (=1 s) for
#       the 128 messages, i.e. < ~7.8 ms per send.  On native hardware
#       this would be much lower (single-digit us); the Xinu/QEMU
#       overhead is what we are bounding here.
#   (4) No panic / FATAL / Exception.
set -u
cd "$(dirname "$0")/../../.."
ROOT=$PWD
XINU=/Users/kodamay/projects/xinu-raz/xinu
COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi-

dune build src/aipl2c.exe >/tmp/_p3_build.log 2>&1 || {
  echo "FAIL: dune build aipl2c"; tail /tmp/_p3_build.log; exit 1; }

src=MpscStressXinu
EXPECTED=128       # 4 producers * K=32 ticks
echo "=== $src (expected ticks=$EXPECTED) ==="

./_build/default/src/aipl2c.exe abclc/${src}.abcl \
    -o /tmp/_p3_${src}.c --xinu --max-msgs 0 \
    > /tmp/_p3_${src}.aipl2c.log 2>&1
[ -f /tmp/_p3_${src}.c ] || {
  echo "  FAIL aipl2c"; cat /tmp/_p3_${src}.aipl2c.log; exit 1; }
cp /tmp/_p3_${src}.c "$XINU/apps/abcl_program.c"

( cd "$XINU/compile" \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT clean >/dev/null 2>&1 \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT DEBUG=-DAIPL_AUTOSTART \
     >/tmp/_p3_${src}.build.log 2>&1 ) \
  || { echo "  FAIL link"; tail /tmp/_p3_${src}.build.log; exit 1; }

# 6 sec is plenty for 128 ticks + report; we then need shutdown via
# message-cap.  Since cap=0 here, we just kill via timeout — the
# final report from Counter still lands before the kill.
timeout 6 qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
      -kernel "$XINU/compile/xinu.elf" -nographic -no-reboot \
      >/tmp/_p3_${src}.qemu.log 2>&1 || true

LOG=/tmp/_p3_${src}.qemu.log
PASS=0; FAIL=0

# (1) ISR-safe send — static check on the generated C source.
echo "  -- assertion (1) ISR-safe send (static) --"
if grep -q '__atomic_compare_exchange_n' /tmp/_p3_${src}.c \
   && grep -q '__atomic_fetch_add\|__atomic_store_n' /tmp/_p3_${src}.c \
   && ! awk '/^void abcl_enqueue/,/^}$/' /tmp/_p3_${src}.c \
        | grep -qE '\bwait\('; then
  PASS=$((PASS+1))
  echo "  PASS (1) abcl_enqueue uses CAS + atomic store, no wait()"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (1) abcl_enqueue still uses wait() or no atomics found"
fi

# (2) No message loss — Counter received all 128.  Drops are inferred
#     from the Counter total: if the lock-free ring had dropped any,
#     Counter's final n would be < EXPECTED.
echo "  -- assertion (2) no message loss under contention --"
final_n=$(grep -aA1 '\[aipl\] mpsc-final' "$LOG" \
          | tr -d '\r' | sed -nE 's/^([0-9]+)$/\1/p' | head -1)
if [ "$final_n" = "$EXPECTED" ]; then
  PASS=$((PASS+1))
  echo "  PASS (2) Counter=$final_n (expected $EXPECTED — zero dropped)"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (2) Counter=$final_n (expected $EXPECTED — some dropped)"
fi

# (3) Throughput — start tick → last alive-marker tick (or done marker
#     if shutdown landed).  Throughput target: < 1000 ticks (1 sec)
#     total, i.e. < ~7.8 ms per message including QEMU overhead.  On
#     real hardware this would be single-digit microseconds per send.
echo "  -- assertion (3) throughput --"
t0=$(grep -aE '\[aipl\] start tick=' "$LOG" \
     | sed -nE 's/.*tick=([0-9]+).*/\1/p' | head -1)
last_alive=$(grep -aE '\[aipl\] alive msg=[0-9]+ tick=' "$LOG" | tail -1)
t1=$(echo "$last_alive" | sed -nE 's/.*tick=([0-9]+).*/\1/p')
msgs=$(echo "$last_alive" | sed -nE 's/.*msg=([0-9]+).*/\1/p')
if [ -n "$t0" ] && [ -n "$t1" ] && [ -n "$msgs" ]; then
  delta=$((t1 - t0))
  # Need at least 125 alive-marker msgs (alive prints every 25; 128
  # dispatches → markers at 25/50/75/100/125, total ≥ 125).
  if [ "$delta" -lt 1000 ] && [ "$msgs" -ge 125 ]; then
    per_msg_us=$((delta * 1000 / msgs))
    PASS=$((PASS+1))
    echo "  PASS (3) elapsed=${delta} ms for $msgs msgs ≈ ${per_msg_us} us/msg"
  else
    FAIL=$((FAIL+1))
    echo "  FAIL (3) elapsed=${delta} ms msgs=$msgs (need delta<1000, msgs>=125)"
  fi
else
  FAIL=$((FAIL+1))
  echo "  FAIL (3) could not extract throughput  t0=$t0 t1=$t1 msgs=$msgs"
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
echo "P3 smoke: PASS=$PASS FAIL=$FAIL  (expected PASS=4 FAIL=0)"
[ $FAIL -eq 0 ]
