#!/usr/bin/env bash
# G1 smoke — framebuffer drawing primitives on PL110.
#
# Sample: abclc/FbPrimitivesXinu.abcl
#   Painter draws circle + triangle + rounded-rect twice — once with
#   AA off, once with AA on — using 24-bit colours (red/green/blue).
#
# Acceptance (3 assertions from the spec):
#   (1) 3 primitive markers appear on serial
#       (fb_circle, fb_triangle, fb_rrect each ≥ 2 times: crisp + AA)
#   (2) 24-bit colour is round-tripped — markers carry the full
#       0xRRGGBB value the AIPL side passed in
#   (3) AA toggle observable — fb_aa=0 appears before fb_aa=1, and
#       the aa= field on primitives reflects the current flag
#   (4) no panic
set -u
cd "$(dirname "$0")/../../.."
ROOT=$PWD
XINU=/Users/kodamay/projects/xinu-raz/xinu
COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi-

dune build src/aipl2c.exe >/tmp/_g1_build.log 2>&1 || {
  echo "FAIL: dune build aipl2c"; tail /tmp/_g1_build.log; exit 1; }

src=FbPrimitivesXinu
echo "=== $src ==="

./_build/default/src/aipl2c.exe abclc/${src}.abcl \
    -o /tmp/_g1_${src}.c --xinu --max-msgs 0 \
    > /tmp/_g1_${src}.aipl2c.log 2>&1
[ -f /tmp/_g1_${src}.c ] || {
  echo "  FAIL aipl2c"; cat /tmp/_g1_${src}.aipl2c.log; exit 1; }
cp /tmp/_g1_${src}.c "$XINU/apps/abcl_program.c"

( cd "$XINU/compile" \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT clean >/dev/null 2>&1 \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT DEBUG=-DAIPL_AUTOSTART \
     >/tmp/_g1_${src}.build.log 2>&1 ) \
  || { echo "  FAIL link"; tail /tmp/_g1_${src}.build.log; exit 1; }

timeout 5 qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
      -kernel "$XINU/compile/xinu.elf" -nographic -no-reboot \
      >/tmp/_g1_${src}.qemu.log 2>&1 || true

LOG=/tmp/_g1_${src}.qemu.log
PASS=0; FAIL=0

# (1) Each of the 3 required primitives appears at least twice (one
# crisp pass + one AA pass).
echo "  -- assertion (1) 3 primitive markers --"
n_circle=$(grep -ac '\[aipl\] fb_circle ' "$LOG")
n_tri=$(grep -ac '\[aipl\] fb_triangle ' "$LOG")
n_rr=$(grep -ac '\[aipl\] fb_rrect ' "$LOG")
if [ "$n_circle" -ge 2 ] && [ "$n_tri" -ge 2 ] && [ "$n_rr" -ge 2 ]; then
  PASS=$((PASS+1))
  echo "  PASS (1) circle=$n_circle triangle=$n_tri rrect=$n_rr"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (1) circle=$n_circle triangle=$n_tri rrect=$n_rr (need each >= 2)"
fi

# (2) Colour 24-bit — the markers should carry the actual values
# we passed in (red=0xff0000, green=0x00ff00, blue=0x0000ff).
echo "  -- assertion (2) 24-bit colour round-trip --"
red_ok=$(grep -ac 'fb_circle .*color=0xff0000'  "$LOG")
grn_ok=$(grep -ac 'fb_triangle .*color=0x00ff00' "$LOG")
blu_ok=$(grep -ac 'fb_rrect .*color=0x0000ff'    "$LOG")
if [ "$red_ok" -ge 2 ] && [ "$grn_ok" -ge 2 ] && [ "$blu_ok" -ge 2 ]; then
  PASS=$((PASS+1))
  echo "  PASS (2) red=$red_ok green=$grn_ok blue=$blu_ok 24-bit ok"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (2) red=$red_ok green=$grn_ok blue=$blu_ok"
  grep -aE '\[aipl\] fb_(circle|triangle|rrect) ' "$LOG" | head -6
fi

# (3) AA toggle — fb_aa=0 must appear before fb_aa=1, and the
# AA-on primitives must carry aa=1 while crisp primitives carry aa=0.
echo "  -- assertion (3) AA toggle observable --"
ln_aa0=$(grep -an '\[aipl\] fb_aa=0' "$LOG" | head -1 | cut -d: -f1)
ln_aa1=$(grep -an '\[aipl\] fb_aa=1' "$LOG" | head -1 | cut -d: -f1)
n_aa0_prim=$(grep -ac '\[aipl\] fb_\(circle\|triangle\|rrect\) .*aa=0' "$LOG")
n_aa1_prim=$(grep -ac '\[aipl\] fb_\(circle\|triangle\|rrect\) .*aa=1' "$LOG")
if [ -n "$ln_aa0" ] && [ -n "$ln_aa1" ] && [ "$ln_aa0" -lt "$ln_aa1" ] \
   && [ "$n_aa0_prim" -ge 3 ] && [ "$n_aa1_prim" -ge 3 ]; then
  PASS=$((PASS+1))
  echo "  PASS (3) fb_aa=0@${ln_aa0} < fb_aa=1@${ln_aa1}; crisp=$n_aa0_prim aa=$n_aa1_prim primitives"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (3) aa0@$ln_aa0 aa1@$ln_aa1 crisp=$n_aa0_prim aa=$n_aa1_prim"
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
echo "G1 smoke: PASS=$PASS FAIL=$FAIL  (expected PASS=4 FAIL=0)"
[ $FAIL -eq 0 ]
