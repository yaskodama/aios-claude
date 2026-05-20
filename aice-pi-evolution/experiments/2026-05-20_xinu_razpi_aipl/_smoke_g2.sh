#!/usr/bin/env bash
# G2 smoke — bitmap font text rendering on PL110.
#
# Sample: abclc/TextDrawXinu.abcl
#   Painter draws 2 strings + 1 single char with 3 distinct colours,
#   then measures pixel width of the strings via fb_text_size.
#
# Acceptance (5 assertions):
#   (1) fb_text marker appears ≥ 2 times (two strings drawn)
#   (2) fb_char marker appears ≥ 1 time (with ch=0x58 for 'X')
#   (3) 24-bit colour round-trip in markers (red/green/white for the
#       three primitives respectively)
#   (4) fb_text_size returns chars * 16:
#       "AIPL on Xinu"  -> 12 chars -> 192
#       "G2 bitmap text"-> 14 chars -> 224
#   (5) no panic
set -u
cd "$(dirname "$0")/../../.."
ROOT=$PWD
XINU=/Users/kodamay/projects/xinu-raz/xinu
COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi-

dune build src/aipl2c.exe >/tmp/_g2_build.log 2>&1 || {
  echo "FAIL: dune build aipl2c"; tail /tmp/_g2_build.log; exit 1; }

src=TextDrawXinu
echo "=== $src ==="

./_build/default/src/aipl2c.exe abclc/${src}.abcl \
    -o /tmp/_g2_${src}.c --xinu --max-msgs 0 \
    > /tmp/_g2_${src}.aipl2c.log 2>&1
[ -f /tmp/_g2_${src}.c ] || {
  echo "  FAIL aipl2c"; cat /tmp/_g2_${src}.aipl2c.log; exit 1; }
cp /tmp/_g2_${src}.c "$XINU/apps/abcl_program.c"

( cd "$XINU/compile" \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT clean >/dev/null 2>&1 \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT DEBUG=-DAIPL_AUTOSTART \
     >/tmp/_g2_${src}.build.log 2>&1 ) \
  || { echo "  FAIL link"; tail /tmp/_g2_${src}.build.log; exit 1; }

timeout 5 qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
      -kernel "$XINU/compile/xinu.elf" -nographic -no-reboot \
      >/tmp/_g2_${src}.qemu.log 2>&1 || true

LOG=/tmp/_g2_${src}.qemu.log
PASS=0; FAIL=0

# (1) fb_text marker — both strings should produce one each.
echo "  -- assertion (1) fb_text marker --"
n_text=$(grep -ac '\[aipl\] fb_text ' "$LOG")
if [ "$n_text" -ge 2 ]; then
  PASS=$((PASS+1))
  echo "  PASS (1) fb_text=$n_text"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (1) fb_text=$n_text (need >= 2)"
  grep -a '\[aipl\] fb_text' "$LOG" | head -4
fi

# (2) fb_char marker with ch=0x58 ('X').
echo "  -- assertion (2) fb_char ASCII int path --"
n_char=$(grep -ac '\[aipl\] fb_char .*ch=0x58' "$LOG")
if [ "$n_char" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (2) fb_char ch=0x58 count=$n_char"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (2) fb_char ch=0x58 count=$n_char"
  grep -a '\[aipl\] fb_char' "$LOG" | head -4
fi

# (3) 24-bit colour round-trip.
echo "  -- assertion (3) 24-bit colour round-trip --"
red_ok=$(grep -ac 'fb_text .*color=0xff0000' "$LOG")
grn_ok=$(grep -ac 'fb_text .*color=0x00ff00' "$LOG")
wht_ok=$(grep -ac 'fb_char .*color=0xffffff' "$LOG")
if [ "$red_ok" -ge 1 ] && [ "$grn_ok" -ge 1 ] && [ "$wht_ok" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (3) red=$red_ok green=$grn_ok white=$wht_ok"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (3) red=$red_ok green=$grn_ok white=$wht_ok"
  grep -aE '\[aipl\] fb_(text|char) ' "$LOG" | head -6
fi

# (4) fb_text_size returns chars * 16.  AIPL print() goes to serial
# as "<value>\r\n".  Look for the two expected widths.
echo "  -- assertion (4) fb_text_size width --"
w1=$(grep -ac '^192$\|^192\r$' "$LOG")
w2=$(grep -ac '^224$\|^224\r$' "$LOG")
if [ "$w1" -ge 1 ] && [ "$w2" -ge 1 ]; then
  PASS=$((PASS+1))
  echo "  PASS (4) width1=192 (12*16) and width2=224 (14*16) printed"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (4) w1(192)=$w1 w2(224)=$w2"
  grep -aE '^[0-9]+$' "$LOG" | head -6
fi

# (5) No panic.
echo "  -- assertion (5) no panic --"
if grep -qE 'panic|FATAL|Exception' "$LOG"; then
  FAIL=$((FAIL+1)); echo "  FAIL (5) panic observed"
  grep -E 'panic|FATAL|Exception' "$LOG" | head -2
else
  PASS=$((PASS+1)); echo "  PASS (5) no panic"
fi

echo
echo "============================"
echo "G2 smoke: PASS=$PASS FAIL=$FAIL  (expected PASS=5 FAIL=0)"
[ $FAIL -eq 0 ]
