#!/usr/bin/env bash
# S3_DeadlineHints smoke — kernel evolution Round 1.
#
# Boots Xinu with abclc/DeadlineDemoXinu.abcl baked in.  The sample
# launches a priority-high "Hoarder" that wants to spin 30 times in
# a row, plus a priority-low "Urgent" actor that prints `90042`.
# Before sending either, AIPL calls `set_deadline(u, 50)` so Urgent
# is queued with a 50ms deadline.
#
# Without S3, Hoarder (prio 30) would block Urgent (prio 10) for
# the whole 30-step run and `90042` would land AFTER `81030`.
# With S3 the resched EDF pick promotes Urgent to the front of
# the queue — `90042` lands EARLY (before all 30 Hoarder steps
# finish).
#
# Acceptance (5 assertions):
#   (1) [aipl] set_deadline marker with rc=1 observed
#   (2) Urgent digest 90042 observed
#   (3) Strictly FEWER than 30 Hoarder steps (81001..81030) appear
#       BEFORE the first 90042 line — proves Urgent jumped queue
#   (4) Hoarder did finish (82000 marker present, all 30 steps printed)
#   (5) no panic / no stack canary trip
set -u
cd "$(dirname "$0")/../../.."
ROOT=$PWD
XINU=/Users/kodamay/projects/xinu-raz/xinu
COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi-

dune build src/aipl2c.exe >/tmp/_s3_build.log 2>&1 || {
  echo "FAIL: dune build aipl2c"; tail /tmp/_s3_build.log; exit 1; }

src=DeadlineDemoXinu
echo "=== $src ==="

./_build/default/src/aipl2c.exe abclc/${src}.abcl \
    -o /tmp/_s3_${src}.c --xinu --max-msgs 0 \
    > /tmp/_s3_${src}.aipl2c.log 2>&1
[ -f /tmp/_s3_${src}.c ] || {
  echo "  FAIL aipl2c"; cat /tmp/_s3_${src}.aipl2c.log; exit 1; }
cp /tmp/_s3_${src}.c "$XINU/apps/abcl_program.c"

( cd "$XINU/compile" \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT clean >/dev/null 2>&1 \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT DEBUG=-DAIPL_AUTOSTART \
     >/tmp/_s3_${src}.build.log 2>&1 ) \
  || { echo "  FAIL link"; tail /tmp/_s3_${src}.build.log; exit 1; }

pkill -f qemu-system-arm 2>/dev/null
sleep 1
timeout 10 qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
      -kernel "$XINU/compile/xinu.elf" -nographic -no-reboot \
      -serial mon:stdio \
      >/tmp/_s3_${src}.qemu.log 2>&1 || true

LOG=/tmp/_s3_${src}.qemu.log
PASS=0; FAIL=0

# (1) set_deadline marker.
echo "  -- assertion (1) set_deadline marker --"
n_sd=$(grep -ac '\[aipl\] set_deadline .*rc=1' "$LOG")
if [ "$n_sd" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (1) set_deadline rc=1 count=$n_sd"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (1) set_deadline rc=1 not observed"
  grep -a '\[aipl\] set_deadline' "$LOG" | head -3
fi

# (2) Urgent digest present.
echo "  -- assertion (2) Urgent 90042 --"
n_urg=$(grep -acE '(^|[^0-9])90042($|[^0-9])' "$LOG")
if [ "$n_urg" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (2) 90042 count=$n_urg"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (2) 90042 not observed"
fi

# (3) Urgent jumped queue — fewer than 30 Hoarder steps before it.
echo "  -- assertion (3) Urgent jumped queue --"
n_before=$(python3 - "$LOG" << 'PY'
import sys
lines = open(sys.argv[1]).read().splitlines()
saw_urgent = False
count = 0
for ln in lines:
    for tok in ln.split():
        if tok == '90042':
            saw_urgent = True
            break
        if tok.isdigit():
            n = int(tok)
            if 81001 <= n <= 81030 and not saw_urgent:
                count += 1
    if saw_urgent:
        break
print(count if saw_urgent else 999)
PY
)
if [ "$n_before" -lt 30 ]; then
  PASS=$((PASS+1))
  echo "  PASS (3) only $n_before Hoarder steps before first Urgent (< 30)"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (3) $n_before Hoarder steps before Urgent (need < 30)"
fi

# (4) Hoarder did finish — all 30 steps and the 82000 done marker.
echo "  -- assertion (4) Hoarder finished --"
n_h=$(grep -caE '(^|[^0-9])81(00[1-9]|0[1-2][0-9]|030)($|[^0-9])' "$LOG")
n_h_done=$(grep -caE '(^|[^0-9])82000($|[^0-9])' "$LOG")
if [ "$n_h" -ge 30 ] && [ "$n_h_done" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (4) Hoarder 30/30 + done marker"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (4) Hoarder steps=$n_h done=$n_h_done"
fi

# (5) No panic / canary trip.
echo "  -- assertion (5) no panic --"
if grep -qE 'panic|FATAL|Exception|STACK CANARY' "$LOG"; then
  FAIL=$((FAIL+1)); echo "  FAIL (5) panic / canary observed"
  grep -E 'panic|FATAL|Exception|STACK CANARY' "$LOG" | head -2
else
  PASS=$((PASS+1)); echo "  PASS (5) clean"
fi

echo
echo "============================"
echo "S3 smoke: PASS=$PASS FAIL=$FAIL  (expected PASS=5 FAIL=0)"
[ $FAIL -eq 0 ]
