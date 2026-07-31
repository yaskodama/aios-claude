#!/usr/bin/env bash
# F4 smoke — strings + int arrays in the Xinu AIPL runtime.
#
# Sample: abclc/StringArrayXinu.aipl runs a Probe actor that exercises
#         str_concat, array bounds checks, and a 200-cycle alloc/free
#         loop.  All three assertions read out of the serial log.
#
# Acceptance (4 assertions):
#   (1) String concat round-trips
#         "hello" + " " + "world" → "hello world"; str_eq returns 1
#   (2) Array OOB is detected
#         array_get(a, 99) prints `[aipl] array OOB ...` and returns 0
#   (3) 200-cycle alloc/free leaks zero slots
#         heap_stats reports alloc≥200 and in_use=0
#   (4) No panic / FATAL
set -u
ROOT=$PWD
XINU=/Users/kodamay/projects/xinu-raz/xinu
COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi-
LOG=/tmp/_f4.qemu.log

dune build src/aipl2c.exe >/tmp/_f4_build.log 2>&1 || {
  echo "FAIL: dune build"; tail /tmp/_f4_build.log; exit 1; }

./_build/default/src/aipl2c.exe abclc/StringArrayXinu.aipl \
    -o /tmp/_f4_StringArrayXinu.c --xinu --max-msgs 0 \
    > /tmp/_f4_aipl2c.log 2>&1
[ -f /tmp/_f4_StringArrayXinu.c ] || {
  echo "FAIL aipl2c"; cat /tmp/_f4_aipl2c.log; exit 1; }
cp /tmp/_f4_StringArrayXinu.c "$XINU/apps/abcl_program.c"

( cd "$XINU/compile" \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT clean >/dev/null 2>&1 \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT DEBUG=-DAIPL_AUTOSTART \
     >/tmp/_f4_xinu_build.log 2>&1 ) \
  || { echo "FAIL xinu build"; tail -20 /tmp/_f4_xinu_build.log; exit 1; }

timeout 8 qemu-system-arm \
      -M versatilepb -cpu arm1176 -m 128M \
      -nographic -semihosting -no-reboot \
      -kernel "$XINU/compile/xinu.boot" \
      >"$LOG" 2>&1 || true

PASS=0; FAIL=0

echo "  -- assertion (1) str_concat round-trip --"
# The AIPL program prints (a) "hello world", (b) 1 (str_eq result)
if grep -aE '^hello world\s*$' "$LOG" >/dev/null \
   && grep -aE '^1\s*$' "$LOG" >/dev/null; then
  PASS=$((PASS+1))
  echo "  PASS (1) hello world + str_eq=1 observed"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (1) concat output missing"
  grep -aE 'hello|str_|world' "$LOG" | head -5
fi

echo "  -- assertion (2) array OOB --"
if grep -aE '\[aipl\] array OOB get .*i=99' "$LOG" >/dev/null; then
  PASS=$((PASS+1))
  echo "  PASS (2) OOB marker present"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (2) OOB marker missing"
  grep -aE 'OOB|array_get' "$LOG" | head -5
fi

echo "  -- assertion (3) 200-cycle alloc/free, no leak --"
# heap_stats prints alloc=<n> free=<n> in_use=0  when balanced.
hline=$(grep -aE '\[aipl\] heap stats alloc=[0-9]+ free=[0-9]+ in_use=[0-9]+' "$LOG" | tail -1)
in_use=$(echo "$hline" | sed -nE 's/.*in_use=([0-9]+).*/\1/p')
allocs=$(echo "$hline" | sed -nE 's/.*alloc=([0-9]+).*/\1/p')
if [ -n "$in_use" ] && [ "$in_use" -eq 0 ] && [ "$allocs" -ge 200 ]; then
  PASS=$((PASS+1))
  echo "  PASS (3) alloc=$allocs free=$(echo "$hline"|sed -nE 's/.*free=([0-9]+).*/\1/p') in_use=$in_use"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (3) heap_stats: $hline"
fi

echo "  -- assertion (4) no panic --"
if grep -qE 'panic|FATAL|Exception' "$LOG"; then
  FAIL=$((FAIL+1)); echo "  FAIL (4) panic"
  grep -E 'panic|FATAL|Exception' "$LOG" | head -2
else
  PASS=$((PASS+1)); echo "  PASS (4) no panic"
fi

echo
echo "============================"
echo "F4 smoke: PASS=$PASS FAIL=$FAIL  (expected PASS=4 FAIL=0)"
[ "$FAIL" -eq 0 ]
