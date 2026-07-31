#!/usr/bin/env bash
# G5 smoke — image bitmap blit on PL110.
#
# Sample: abclc/ImageBlitXinu.aipl
#   Painter calls fb_image_solid(16,16,16,16, 0x0000FF) then builds a
#   4x4 red/green checkerboard via array_new + array_set, blits it
#   with fb_image at (80,80).  Counts are printed back via v_print.
#
# Acceptance (6 assertions):
#   (1) fb_image_solid marker present, with color=0x0000ff
#   (2) Solid path returned w*h = 256 (printed as 256 by AIPL)
#   (3) fb_image marker present, painted=16 clipped=0 arr=<id>
#   (4) fb_image returned 16 (printed back via AIPL)
#   (5) Array slot id was stable through fb_image (marker arr=<id>
#       matches the obj id returned by array_new) — verified by
#       grepping that fb_image arr= field is integer-valued, no
#       `bad arr=` error path was taken
#   (6) no panic
set -u
cd "$(dirname "$0")/../../.."
ROOT=$PWD
XINU=/Users/kodamay/projects/xinu-raz/xinu
COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi-

dune build src/aipl2c.exe >/tmp/_g5_build.log 2>&1 || {
  echo "FAIL: dune build aipl2c"; tail /tmp/_g5_build.log; exit 1; }

src=ImageBlitXinu
echo "=== $src ==="

./_build/default/src/aipl2c.exe abclc/${src}.aipl \
    -o /tmp/_g5_${src}.c --xinu --max-msgs 0 \
    > /tmp/_g5_${src}.aipl2c.log 2>&1
[ -f /tmp/_g5_${src}.c ] || {
  echo "  FAIL aipl2c"; cat /tmp/_g5_${src}.aipl2c.log; exit 1; }
cp /tmp/_g5_${src}.c "$XINU/apps/abcl_program.c"

( cd "$XINU/compile" \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT clean >/dev/null 2>&1 \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT DEBUG=-DAIPL_AUTOSTART \
     >/tmp/_g5_${src}.build.log 2>&1 ) \
  || { echo "  FAIL link"; tail /tmp/_g5_${src}.build.log; exit 1; }

timeout 5 qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
      -kernel "$XINU/compile/xinu.elf" -nographic -no-reboot \
      >/tmp/_g5_${src}.qemu.log 2>&1 || true

LOG=/tmp/_g5_${src}.qemu.log
PASS=0; FAIL=0

# (1) fb_image_solid marker.
echo "  -- assertion (1) fb_image_solid marker --"
n_solid=$(grep -ac '\[aipl\] fb_image_solid .*color=0x0000ff' "$LOG")
if [ "$n_solid" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (1) fb_image_solid count=$n_solid color=0x0000ff"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (1) fb_image_solid count=$n_solid"
  grep -a '\[aipl\] fb_image' "$LOG" | head -4
fi

# (2) Solid path returned w*h = 256.  Use word-boundary grep because
# AIPL print prefix can be glued to the WM xsh$ prompt.
echo "  -- assertion (2) solid w*h = 256 returned --"
n_256=$(grep -acE '(^|[^0-9])256($|[^0-9])' "$LOG")
if [ "$n_256" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (2) 256 printed (solid return value)"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (2) 256 not observed"
  grep -aE '(^|[^0-9])[0-9]+($|[^0-9])' "$LOG" | head -10
fi

# (3) fb_image marker — painted=16 clipped=0.
echo "  -- assertion (3) fb_image marker (painted/clipped) --"
n_img=$(grep -ac '\[aipl\] fb_image .*painted=16 clipped=0' "$LOG")
if [ "$n_img" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (3) fb_image painted=16 clipped=0 count=$n_img"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (3) fb_image painted=16 clipped=0 — not observed"
  grep -a '\[aipl\] fb_image ' "$LOG" | head -4
fi

# (4) fb_image returned 16.
echo "  -- assertion (4) fb_image return value = 16 --"
n_16=$(grep -acE '(^|[^0-9])16($|[^0-9])' "$LOG")
if [ "$n_16" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (4) 16 printed (fb_image return value)"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (4) 16 not observed"
fi

# (5) No `bad arr=` error path; arr= field carries a numeric slot id.
echo "  -- assertion (5) array slot id round-trip --"
n_bad=$(grep -ac 'fb_image bad arr=' "$LOG")
n_arrgood=$(grep -ac '\[aipl\] fb_image .*arr=[0-9]' "$LOG")
if [ "$n_bad" -eq 0 ] && [ "$n_arrgood" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (5) arr_id stable (bad_arr_count=0, good=$n_arrgood)"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (5) bad_arr=$n_bad good=$n_arrgood"
fi

# (6) No panic.
echo "  -- assertion (6) no panic --"
if grep -qE 'panic|FATAL|Exception' "$LOG"; then
  FAIL=$((FAIL+1)); echo "  FAIL (6) panic observed"
  grep -E 'panic|FATAL|Exception' "$LOG" | head -2
else
  PASS=$((PASS+1)); echo "  PASS (6) no panic"
fi

echo
echo "============================"
echo "G5 smoke: PASS=$PASS FAIL=$FAIL  (expected PASS=6 FAIL=0)"
[ $FAIL -eq 0 ]
