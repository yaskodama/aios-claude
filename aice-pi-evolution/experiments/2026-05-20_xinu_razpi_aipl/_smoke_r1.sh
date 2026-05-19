#!/usr/bin/env bash
# R1 smoke — verify each Xinu sample boots, prints [aipl] start, runs at
# least one send + recv, and never hits panic / FATAL / Exception in the
# serial log.
#
# Acceptance (3 assertion per sample × 3 samples = 9 total):
#   (1) [aipl] start  marker emitted
#   (2) [aipl] first-send + [aipl] first-recv  markers emitted
#   (3) no panic / FATAL / Exception
set -u
cd "$(dirname "$0")/../../.."
ROOT=$PWD
XINU=/Users/kodamay/projects/xinu-raz/xinu
COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi-

# Sanity: aipl2c builds.
dune build src/aipl2c.exe >/tmp/_r1_build.log 2>&1 || {
  echo "FAIL: dune build aipl2c"; tail /tmp/_r1_build.log; exit 1; }

PASS=0; FAIL=0
for src in Rotate4LinesXinu Philosophers5Xinu BoundedBufferXinu; do
  echo "=== $src ==="
  ./_build/default/src/aipl2c.exe abclc/${src}.abcl \
      -o /tmp/_r1_${src}.c --xinu --max-msgs 0 \
      > /tmp/_r1_${src}.aipl2c.log 2>&1
  if [ ! -f /tmp/_r1_${src}.c ]; then
    echo "  FAIL aipl2c"; tail /tmp/_r1_${src}.aipl2c.log; FAIL=$((FAIL+3)); continue
  fi
  cp /tmp/_r1_${src}.c "$XINU/apps/abcl_program.c"

  # Force a clean rebuild so the new abcl_program.c is picked up.
  ( cd "$XINU/compile" \
    && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT clean >/dev/null 2>&1 \
    && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT DEBUG=-DAIPL_AUTOSTART \
       >/tmp/_r1_${src}.build.log 2>&1 ) \
    || { echo "  FAIL link"; tail /tmp/_r1_${src}.build.log; FAIL=$((FAIL+3)); continue; }

  timeout 12 qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
        -kernel "$XINU/compile/xinu.elf" -nographic -no-reboot \
        >/tmp/_r1_${src}.qemu.log 2>&1 || true

  # 1) start marker
  if grep -q '\[aipl\] start' /tmp/_r1_${src}.qemu.log; then
    PASS=$((PASS+1)); echo "  PASS (1) [aipl] start"
  else FAIL=$((FAIL+1)); echo "  FAIL (1) no [aipl] start"; fi

  # 2) send + recv markers — at least one of each
  if grep -q '\[aipl\] first-send'  /tmp/_r1_${src}.qemu.log \
     && grep -q '\[aipl\] first-recv' /tmp/_r1_${src}.qemu.log; then
    PASS=$((PASS+1)); echo "  PASS (2) first-send + first-recv"
  else FAIL=$((FAIL+1)); echo "  FAIL (2) missing send/recv markers"; fi

  # 3) no panic
  if grep -qE 'panic|FATAL|Exception' /tmp/_r1_${src}.qemu.log; then
    FAIL=$((FAIL+1)); echo "  FAIL (3) panic/FATAL/Exception observed"
    grep -E 'panic|FATAL|Exception' /tmp/_r1_${src}.qemu.log | head -3
  else PASS=$((PASS+1)); echo "  PASS (3) no panic"; fi
done

echo
echo "============================"
echo "R1 smoke: PASS=$PASS FAIL=$FAIL  (expected PASS=9 FAIL=0)"
[ $FAIL -eq 0 ]
