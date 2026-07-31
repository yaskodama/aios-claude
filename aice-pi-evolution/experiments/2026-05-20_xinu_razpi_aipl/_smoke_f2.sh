#!/usr/bin/env bash
# F2 smoke — Last-Writer-Wins cell semantics.
#
# Sample: abclc/LwwCellsXinu.aipl
#   Sheet exercises every LWW invariant — newer-wins, older-rejected,
#   strict-greater (ties rejected), multi-key isolation, monotonic
#   tick, clear.
#
# Acceptance (8 assertions):
#   (1) Two accepted writes for key=1 (ts=10, ts=20)
#   (2) One reject for ts=5 (older), one reject for ts=20 (tie)
#   (3) Read of key=1 ends at 200 (the last accepted value)
#   (4) Read of key=2 returns 42 (different key isolated)
#   (5) size == 2 between writes, == 0 after clear
#   (6) lww_tick monotonic: 5021 then 5022 (Lamport advanced past
#       the highest observed ts=20)
#   (7) Tag-mismatch digests: r1=1001 r2=1001 r3=1000 r4=1000 r5=1001
#   (8) no panic
set -u
cd "$(dirname "$0")/../../.."
ROOT=$PWD
XINU=/Users/kodamay/projects/xinu-raz/xinu
COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi-

dune build src/aipl2c.exe >/tmp/_f2_build.log 2>&1 || {
  echo "FAIL: dune build aipl2c"; tail /tmp/_f2_build.log; exit 1; }

src=LwwCellsXinu
echo "=== $src ==="

./_build/default/src/aipl2c.exe abclc/${src}.aipl \
    -o /tmp/_f2_${src}.c --xinu --max-msgs 0 \
    > /tmp/_f2_${src}.aipl2c.log 2>&1
[ -f /tmp/_f2_${src}.c ] || {
  echo "  FAIL aipl2c"; cat /tmp/_f2_${src}.aipl2c.log; exit 1; }
cp /tmp/_f2_${src}.c "$XINU/apps/abcl_program.c"

( cd "$XINU/compile" \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT clean >/dev/null 2>&1 \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT DEBUG=-DAIPL_AUTOSTART \
     >/tmp/_f2_${src}.build.log 2>&1 ) \
  || { echo "  FAIL link"; tail /tmp/_f2_${src}.build.log; exit 1; }

timeout 5 qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
      -kernel "$XINU/compile/xinu.elf" -nographic -no-reboot \
      >/tmp/_f2_${src}.qemu.log 2>&1 || true

LOG=/tmp/_f2_${src}.qemu.log
PASS=0; FAIL=0

# (1) Accepted writes — key=1 ts=10, key=1 ts=20, key=2 ts=15 — 3 total
echo "  -- assertion (1) 3 accepted writes --"
n_acc=$(grep -ac '\[aipl\] lww op=write ' "$LOG")
if [ "$n_acc" -eq 3 ]; then
  PASS=$((PASS+1))
  echo "  PASS (1) accepted writes count=$n_acc"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (1) accepted writes count=$n_acc (need exactly 3)"
  grep -a '\[aipl\] lww op=' "$LOG" | head -10
fi

# (2) Rejects: older + tie.
echo "  -- assertion (2) 2 rejects (older + tie) --"
n_rej=$(grep -ac '\[aipl\] lww op=reject ' "$LOG")
n_rej_old=$(grep -ac 'lww op=reject key=1 value=50 ts=5 stored_ts=20' "$LOG")
n_rej_tie=$(grep -ac 'lww op=reject key=1 value=999 ts=20 stored_ts=20' "$LOG")
if [ "$n_rej" -eq 2 ] && [ "$n_rej_old" -ge 1 ] && [ "$n_rej_tie" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (2) reject count=$n_rej (older=$n_rej_old tie=$n_rej_tie)"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (2) reject=$n_rej older=$n_rej_old tie=$n_rej_tie"
fi

# (3) read(key=1) ends at 200 → digest 2200 appears 3+ times
# (after 1st write 2100, after 2nd write 2200, after rejected
# writes 2200 still).
echo "  -- assertion (3) read(key=1) ends at 200 --"
d_2200=$(grep -acE '(^|[^0-9])2200($|[^0-9])' "$LOG")
d_2100=$(grep -acE '(^|[^0-9])2100($|[^0-9])' "$LOG")
if [ "$d_2200" -ge 3 ] && [ "$d_2100" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (3) read traces: 2100=$d_2100 2200=$d_2200"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (3) 2100=$d_2100 2200=$d_2200 (need 2100≥1 2200≥3)"
fi

# (4) read(key=2) returns 42 → digest 3042.
echo "  -- assertion (4) read(key=2) returns 42 --"
d_3042=$(grep -acE '(^|[^0-9])3042($|[^0-9])' "$LOG")
if [ "$d_3042" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (4) key=2 value=42 observed"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (4) 3042=$d_3042"
fi

# (5) size 2 then 0 after clear → 4002 then 4000.
echo "  -- assertion (5) size 2 → 0 around clear --"
d_4002=$(grep -acE '(^|[^0-9])4002($|[^0-9])' "$LOG")
d_4000=$(grep -acE '(^|[^0-9])4000($|[^0-9])' "$LOG")
d_6002=$(grep -acE '(^|[^0-9])6002($|[^0-9])' "$LOG")
n_clr=$(grep -ac '\[aipl\] lww op=clear count=2' "$LOG")
if [ "$d_4002" -ge 1 ] && [ "$d_4000" -ge 1 ] && \
   [ "$d_6002" -ge 1 ] && [ "$n_clr" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (5) size 2 → cleared 2 → size 0"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (5) 4002=$d_4002 6002=$d_6002 4000=$d_4000 clear-marker=$n_clr"
fi

# (6) Lamport monotonic: 5021 then 5022.
echo "  -- assertion (6) Lamport monotonic 5021 then 5022 --"
d_5021=$(grep -acE '(^|[^0-9])5021($|[^0-9])' "$LOG")
d_5022=$(grep -acE '(^|[^0-9])5022($|[^0-9])' "$LOG")
if [ "$d_5021" -ge 1 ] && [ "$d_5022" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (6) lww_tick = 21 then 22 (past highest observed ts=20)"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (6) 5021=$d_5021 5022=$d_5022"
fi

# (7) Per-write digest pattern: 1001 ≥3, 1000 ≥2.
echo "  -- assertion (7) write digests --"
d_1001=$(grep -acE '(^|[^0-9])1001($|[^0-9])' "$LOG")
d_1000=$(grep -acE '(^|[^0-9])1000($|[^0-9])' "$LOG")
if [ "$d_1001" -ge 3 ] && [ "$d_1000" -ge 2 ]; then
  PASS=$((PASS+1))
  echo "  PASS (7) accept digests=1001×$d_1001 reject=1000×$d_1000"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (7) 1001=$d_1001 1000=$d_1000"
fi

# (8) No panic.
echo "  -- assertion (8) no panic --"
if grep -qE 'panic|FATAL|Exception' "$LOG"; then
  FAIL=$((FAIL+1)); echo "  FAIL (8) panic observed"
  grep -E 'panic|FATAL|Exception' "$LOG" | head -2
else
  PASS=$((PASS+1)); echo "  PASS (8) no panic"
fi

echo
echo "============================"
echo "F2 smoke: PASS=$PASS FAIL=$FAIL  (expected PASS=8 FAIL=0)"
[ $FAIL -eq 0 ]
