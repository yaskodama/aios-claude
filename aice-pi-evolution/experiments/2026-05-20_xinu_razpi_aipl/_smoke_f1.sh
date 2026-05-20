#!/usr/bin/env bash
# F1 smoke — local-node distributed-checkpoint phase 1.
#
# Sample: abclc/DistCheckpointXinu.abcl
#   Bank saves "v1" snapshot, mutates balance/score/owner, restores
#   "v1", then misses a tag and clears.  Tagged digests verify each
#   step.
#
# Acceptance (7 assertions):
#   (1) chkpt op=save marker observed with slot=N fields=3+
#   (2) chkpt op=load marker observed with slot=N fields=3+
#   (3) Balance digest sequence 1100 → 1999 → 1100 (round-trip)
#   (4) Score restored to 50 (digest 5050)
#   (5) Tag miss: checkpoint_load("no-such-tag") returns 0 → 7000
#   (6) checkpoint_list returns 1 after save, 0 after clear (3001+3000)
#   (7) no panic
set -u
cd "$(dirname "$0")/../../.."
ROOT=$PWD
XINU=/Users/kodamay/projects/xinu-raz/xinu
COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi-

dune build src/aipl2c.exe >/tmp/_f1_build.log 2>&1 || {
  echo "FAIL: dune build aipl2c"; tail /tmp/_f1_build.log; exit 1; }

src=DistCheckpointXinu
echo "=== $src ==="

./_build/default/src/aipl2c.exe abclc/${src}.abcl \
    -o /tmp/_f1_${src}.c --xinu --max-msgs 0 \
    > /tmp/_f1_${src}.aipl2c.log 2>&1
[ -f /tmp/_f1_${src}.c ] || {
  echo "  FAIL aipl2c"; cat /tmp/_f1_${src}.aipl2c.log; exit 1; }
cp /tmp/_f1_${src}.c "$XINU/apps/abcl_program.c"

( cd "$XINU/compile" \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT clean >/dev/null 2>&1 \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT DEBUG=-DAIPL_AUTOSTART \
     >/tmp/_f1_${src}.build.log 2>&1 ) \
  || { echo "  FAIL link"; tail /tmp/_f1_${src}.build.log; exit 1; }

timeout 5 qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
      -kernel "$XINU/compile/xinu.elf" -nographic -no-reboot \
      >/tmp/_f1_${src}.qemu.log 2>&1 || true

LOG=/tmp/_f1_${src}.qemu.log
PASS=0; FAIL=0

# (1) Save marker — fields >= 3 (Bank has 5 declared, but the runtime
# zero-inits all MAX_FIELDS so all 16 are copied; accept >= 3).
echo "  -- assertion (1) chkpt save marker --"
n_save=$(grep -aE '\[aipl\] chkpt op=save .*slot=[0-9]+ class=[0-9]+ fields=([3-9]|1[0-9])' "$LOG" | wc -l)
if [ "$n_save" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (1) save count=$n_save"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (1) save count=$n_save"
  grep -a '\[aipl\] chkpt' "$LOG" | head -5
fi

# (2) Load marker.
echo "  -- assertion (2) chkpt load marker --"
n_load=$(grep -aE '\[aipl\] chkpt op=load .*slot=[0-9]+ fields=([3-9]|1[0-9])' "$LOG" | wc -l)
if [ "$n_load" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (2) load count=$n_load"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (2) load count=$n_load"
fi

# (3) Balance round-trip — digest 1100 appears twice (before save +
# after load), 1999 once between them.
echo "  -- assertion (3) balance round-trip 100 → 999 → 100 --"
d_1100=$(grep -acE '(^|[^0-9])1100($|[^0-9])' "$LOG")
d_1999=$(grep -acE '(^|[^0-9])1999($|[^0-9])' "$LOG")
if [ "$d_1100" -ge 2 ] && [ "$d_1999" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (3) 1100 count=$d_1100 (>=2)  1999 count=$d_1999"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (3) 1100=$d_1100 1999=$d_1999"
fi

# (4) Score restored — digest 5050.
echo "  -- assertion (4) score restored to 50 --"
d_5050=$(grep -acE '(^|[^0-9])5050($|[^0-9])' "$LOG")
d_6042=$(grep -acE '(^|[^0-9])6042($|[^0-9])' "$LOG")
if [ "$d_5050" -ge 1 ] && [ "$d_6042" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (4) score=5050 owner=6042 both restored"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (4) 5050=$d_5050 6042=$d_6042"
fi

# (5) Tag miss returns 0 → digest 7000.
echo "  -- assertion (5) tag miss returns 0 --"
d_7000=$(grep -acE '(^|[^0-9])7000($|[^0-9])' "$LOG")
n_miss=$(grep -ac 'chkpt op=load .*status=not-found' "$LOG")
if [ "$d_7000" -ge 1 ] && [ "$n_miss" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (5) miss returned 0 (7000) and not-found marker present"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (5) 7000=$d_7000 not-found=$n_miss"
fi

# (6) list returned 1 then 0 (3001 before clear, 3000 after).
echo "  -- assertion (6) list 1 → clear → 0 --"
d_3001=$(grep -acE '(^|[^0-9])3001($|[^0-9])' "$LOG")
d_3000=$(grep -acE '(^|[^0-9])3000($|[^0-9])' "$LOG")
d_8001=$(grep -acE '(^|[^0-9])8001($|[^0-9])' "$LOG")
if [ "$d_3001" -ge 1 ] && [ "$d_3000" -ge 1 ] && [ "$d_8001" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (6) list 3001 → cleared 8001 → list 3000"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (6) 3001=$d_3001 8001=$d_8001 3000=$d_3000"
fi

# (7) No panic.
echo "  -- assertion (7) no panic --"
if grep -qE 'panic|FATAL|Exception' "$LOG"; then
  FAIL=$((FAIL+1)); echo "  FAIL (7) panic observed"
  grep -E 'panic|FATAL|Exception' "$LOG" | head -2
else
  PASS=$((PASS+1)); echo "  PASS (7) no panic"
fi

echo
echo "============================"
echo "F1 smoke: PASS=$PASS FAIL=$FAIL  (expected PASS=7 FAIL=0)"
[ $FAIL -eq 0 ]
