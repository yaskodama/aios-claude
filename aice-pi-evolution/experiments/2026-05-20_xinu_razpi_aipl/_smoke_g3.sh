#!/usr/bin/env bash
# G3 smoke — PL050 mouse → AIPL actor message dispatch.
#
# Sample: abclc/MouseDemoXinu.abcl
#   MouseLogger subscribes to click / move / release, then synthesises
#   1 click + 2 moves + 1 release via mouse_inject().  Callbacks print
#   tagged digests (1xxx click / 2xxx move / 3xxx release) so the smoke
#   can confirm the AIPL thread actually consumed the messages.
#
# Acceptance (6 assertions):
#   (1) All three subscribe markers observed (mouse_on_{click,move,release})
#   (2) mouse_event kind=click appears ≥ 1 with x=100 y=200 btn=1
#   (3) mouse_event kind=move  appears ≥ 2
#   (4) mouse_event kind=release appears ≥ 1 with btn=0
#   (5) Actor callbacks reached AIPL thread — digests 1100, 2105, 2110,
#       3110 all printed
#   (6) mouse_state() returns 115399680 = (110<<20)|(220<<8)|0
set -u
cd "$(dirname "$0")/../../.."
ROOT=$PWD
XINU=/Users/kodamay/projects/xinu-raz/xinu
COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi-

dune build src/aipl2c.exe >/tmp/_g3_build.log 2>&1 || {
  echo "FAIL: dune build aipl2c"; tail /tmp/_g3_build.log; exit 1; }

src=MouseDemoXinu
echo "=== $src ==="

./_build/default/src/aipl2c.exe abclc/${src}.abcl \
    -o /tmp/_g3_${src}.c --xinu --max-msgs 0 \
    > /tmp/_g3_${src}.aipl2c.log 2>&1
[ -f /tmp/_g3_${src}.c ] || {
  echo "  FAIL aipl2c"; cat /tmp/_g3_${src}.aipl2c.log; exit 1; }
cp /tmp/_g3_${src}.c "$XINU/apps/abcl_program.c"

( cd "$XINU/compile" \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT clean >/dev/null 2>&1 \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT DEBUG=-DAIPL_AUTOSTART \
     >/tmp/_g3_${src}.build.log 2>&1 ) \
  || { echo "  FAIL link"; tail /tmp/_g3_${src}.build.log; exit 1; }

timeout 5 qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
      -kernel "$XINU/compile/xinu.elf" -nographic -no-reboot \
      >/tmp/_g3_${src}.qemu.log 2>&1 || true

LOG=/tmp/_g3_${src}.qemu.log
PASS=0; FAIL=0

# (1) Subscribe markers.
echo "  -- assertion (1) subscribe markers --"
n_sub_c=$(grep -ac '\[aipl\] mouse_on_click '   "$LOG")
n_sub_m=$(grep -ac '\[aipl\] mouse_on_move '    "$LOG")
n_sub_r=$(grep -ac '\[aipl\] mouse_on_release ' "$LOG")
if [ "$n_sub_c" -ge 1 ] && [ "$n_sub_m" -ge 1 ] && [ "$n_sub_r" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (1) on_click=$n_sub_c on_move=$n_sub_m on_release=$n_sub_r"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (1) on_click=$n_sub_c on_move=$n_sub_m on_release=$n_sub_r"
  grep -a '\[aipl\] mouse_on_' "$LOG" | head -6
fi

# (2) Click dispatch.
echo "  -- assertion (2) click dispatch --"
n_clk=$(grep -ac '\[aipl\] mouse_event kind=click .*x=100 y=200 btn=1' "$LOG")
if [ "$n_clk" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (2) click x=100 y=200 btn=1 count=$n_clk"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (2) expected click (100,200,btn=1) — got $n_clk"
  grep -a '\[aipl\] mouse_event' "$LOG" | head -6
fi

# (3) Move dispatch (>= 2).
echo "  -- assertion (3) move dispatch --"
n_mv=$(grep -ac '\[aipl\] mouse_event kind=move ' "$LOG")
if [ "$n_mv" -ge 2 ]; then
  PASS=$((PASS+1))
  echo "  PASS (3) move count=$n_mv"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (3) move count=$n_mv (need >= 2)"
fi

# (4) Release dispatch.
echo "  -- assertion (4) release dispatch --"
n_rel=$(grep -ac '\[aipl\] mouse_event kind=release .*btn=0' "$LOG")
if [ "$n_rel" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (4) release btn=0 count=$n_rel"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (4) release btn=0 count=$n_rel"
fi

# (5) Actor callbacks reached the AIPL thread.  Digests are unique
# per callback so we can grep them — but the WM xsh prompt may glue
# itself to the first print (xsh$ 1100), so use word-boundary search
# rather than anchored start-of-line.
echo "  -- assertion (5) actor digests --"
d_1100=$(grep -acE '(^|[^0-9])1100($|[^0-9])' "$LOG")
d_2105=$(grep -acE '(^|[^0-9])2105($|[^0-9])' "$LOG")
d_2110=$(grep -acE '(^|[^0-9])2110($|[^0-9])' "$LOG")
d_3110=$(grep -acE '(^|[^0-9])3110($|[^0-9])' "$LOG")
if [ "$d_1100" -ge 1 ] && [ "$d_2105" -ge 1 ] && \
   [ "$d_2110" -ge 1 ] && [ "$d_3110" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (5) digests 1100/2105/2110/3110 all present"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (5) 1100=$d_1100 2105=$d_2105 2110=$d_2110 3110=$d_3110"
  grep -aE '^[0-9]+(\r)?$' "$LOG" | head -10
fi

# (6) mouse_state packed int.  (110<<20)|(220<<8)|0 = 115399680.
echo "  -- assertion (6) mouse_state packed --"
expect_state=$(printf '%d' $(( (110 << 20) | (220 << 8) | 0 )))
n_state=$(grep -acE "(^|[^0-9])${expect_state}($|[^0-9])" "$LOG")
if [ "$n_state" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (6) mouse_state=$expect_state observed"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (6) expected mouse_state=$expect_state"
  grep -aE '^[0-9]+(\r)?$' "$LOG" | tail -8
fi

echo
echo "============================"
echo "G3 smoke: PASS=$PASS FAIL=$FAIL  (expected PASS=6 FAIL=0)"
[ $FAIL -eq 0 ]
