#!/usr/bin/env bash
# Combined smoke for:
#   - halt refactor (system_halt() now shared by xsh_halt + WM)
#   - Xinu-side AIPL->C compiler (xsh_abclc + system/abclc.c + cc + a.out)
#
# Boots xinu.boot in console mode (no AIPL_AUTOSTART), feeds shell
# commands via UART, captures the serial log.
#
# Acceptance (5 assertions):
#   (1) xsh halt still works after the refactor (semihosting SYS_EXIT)
#   (2) abclc accepts a seed .abcl and writes the corresponding .c
#   (3) cc compiles that .c into a.out (runs ccCompile chain)
#   (4) running the a.out produces output
#   (5) System halted line + QEMU rc=0
set -u
XINU=/Users/kodamay/projects/xinu-raz/xinu
COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi-
LOG=/tmp/_halt_abclc.qemu.log

( cd "$XINU/compile" \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT clean >/dev/null 2>&1 \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT \
     >/tmp/_halt_abclc.build.log 2>&1 ) \
  || { echo "FAIL build"; tail -30 /tmp/_halt_abclc.build.log; exit 1; }

{
  sleep 2
  printf '\n'
  printf 'ls /home/abclcp/abclc\n';                              sleep 0.5
  printf 'abclc /home/abclcp/abclc/PingPong.abcl\n';             sleep 2.0
  printf 'ls /home/abclcp/abclc\n';                              sleep 0.5
  # `abclc` chains through to cc internally — check the a.out exists.
  printf 'ls\n';                                                 sleep 0.4
  printf 'run /home/abclcp/abclc/PingPong\n';                    sleep 1.0
  printf 'halt\n';                                               sleep 1
} | timeout 18 qemu-system-arm \
        -M versatilepb -cpu arm1176 -m 128M \
        -nographic -semihosting -no-reboot \
        -kernel "$XINU/compile/xinu.boot" \
        >"$LOG" 2>&1
QEMU_RC=$?

PASS=0; FAIL=0

echo "  -- assertion (1) System halted printed --"
if grep -aq 'System halted' "$LOG"; then
  PASS=$((PASS+1)); echo "  PASS (1) halt still works (system_halt refactor OK)"
else
  FAIL=$((FAIL+1)); echo "  FAIL (1) 'System halted' not in log"
fi

echo "  -- assertion (2) abclc produced .c output --"
# After running `abclc PingPong.abcl`, the directory listing should
# show PingPong.c.  The abclc command itself also prints a status.
if grep -aE 'PingPong\.c|wrote.*\.c|abclc:.*ok' "$LOG" >/dev/null; then
  PASS=$((PASS+1)); echo "  PASS (2) abclc wrote .c"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (2) abclc did not write .c — tail of log:"
  grep -aE 'abclc|PingPong' "$LOG" | head -10
fi

echo "  -- assertion (3) cc produced a.out --"
# The 2nd ls in /home/abclcp/abclc should list PingPong (the binary)
# next to PingPong.abcl + PingPong.c.
if grep -aE '^PingPong[[:space:]]*$|PingPong$' "$LOG" >/dev/null; then
  PASS=$((PASS+1)); echo "  PASS (3) PingPong a.out present in listing"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (3) PingPong a.out missing — relevant ls output:"
  grep -aE 'PingPong' "$LOG" | head -10
fi

echo "  -- assertion (4) run a.out produced output --"
# PingPong actor program: any line from the actual execution is
# enough — e.g. `Player … tick`, `[abcl] done`, `hits=`.
if grep -aE 'Player [0-9]+:|tick \(n=|\[abcl\] done|hits=' "$LOG" >/dev/null; then
  PASS=$((PASS+1))
  echo "  PASS (4) PingPong actor program ran end-to-end"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (4) no output from run — recent log tail:"
  tail -20 "$LOG"
fi

echo "  -- assertion (5) QEMU exited cleanly --"
if [ "$QEMU_RC" -eq 0 ]; then
  PASS=$((PASS+1)); echo "  PASS (5) QEMU rc=0 (Cocoa window closes too)"
else
  FAIL=$((FAIL+1)); echo "  FAIL (5) QEMU rc=$QEMU_RC (expected 0)"
fi

echo
echo "============================"
echo "halt+abclc smoke: PASS=$PASS FAIL=$FAIL  (expected PASS=5 FAIL=0)"
[ "$FAIL" -eq 0 ]
