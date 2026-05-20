#!/usr/bin/env bash
# memfs smoke — verify the existing Xinu RAM-backed hierarchical file
# system + shell commands (ls / pwd / cd / mkdir / cat / halt) work.
#
# Boots Xinu in console mode (no -DAIPL_AUTOSTART so xsh launches),
# streams shell commands into the UART, captures the serial log, and
# asserts:
#   (1) pwd shows /
#   (2) mkdir /demo + cd /demo + pwd shows /demo
#   (3) ls / lists demo/ as a directory
#   (4) halt cleanly exits QEMU (semihosting SYS_EXIT) — script
#       returns without -timeout having to kill the process
set -u
XINU=/Users/kodamay/projects/xinu-raz/xinu
COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi-
LOG=/tmp/_memfs.qemu.log

# Build WITHOUT AIPL_AUTOSTART so the interactive xsh launches.
( cd "$XINU/compile" \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT clean >/dev/null 2>&1 \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT \
     >/tmp/_memfs.build.log 2>&1 ) \
  || { echo "FAIL build"; tail -30 /tmp/_memfs.build.log; exit 1; }

# Feed shell commands into QEMU's stdin.  Pauses give the shell time
# to print the prompt before the next command lands.  Final `halt`
# triggers semihosting SYS_EXIT so QEMU returns 0 on its own.
{
  sleep 2
  printf '\n'
  printf 'pwd\n';                sleep 0.4
  printf 'ls /\n';               sleep 0.4
  printf 'mkdir /demo\n';        sleep 0.4
  printf 'mkdir /demo/nested\n'; sleep 0.4
  printf 'ls /\n';               sleep 0.4
  printf 'cd /demo\n';           sleep 0.4
  printf 'pwd\n';                sleep 0.4
  printf 'ls\n';                 sleep 0.4
  printf 'cd ..\n';              sleep 0.4
  printf 'pwd\n';                sleep 0.4
  printf 'halt\n';               sleep 1
} | timeout 12 qemu-system-arm \
        -M versatilepb -cpu arm1176 -m 128M \
        -nographic -semihosting -no-reboot \
        -kernel "$XINU/compile/xinu.boot" \
        >"$LOG" 2>&1
QEMU_RC=$?

PASS=0; FAIL=0

echo "  -- assertion (1) pwd / works --"
# After the first `pwd` the line `/` should appear.
if grep -aE '^/\s*$|^/[[:space:]]*$' "$LOG" >/dev/null; then
  PASS=$((PASS+1))
  echo "  PASS (1) pwd printed / at startup"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (1) pwd did not print /"
fi

echo "  -- assertion (2) mkdir + cd + pwd --"
# After cd /demo, pwd should output /demo.
if grep -aE '^/demo\s*$' "$LOG" >/dev/null; then
  PASS=$((PASS+1))
  echo "  PASS (2) pwd printed /demo after cd"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (2) /demo not observed in pwd output"
fi

echo "  -- assertion (3) ls shows demo/ --"
if grep -aE '^demo/' "$LOG" >/dev/null; then
  PASS=$((PASS+1))
  echo "  PASS (3) ls / lists demo/"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (3) demo/ not in ls output"
fi

echo "  -- assertion (4) halt cleanly exits QEMU --"
# semihosting SYS_EXIT makes QEMU return 0.  timeout would have made
# it return 124.  We also want to see "System halted." in the log.
if [ "$QEMU_RC" -eq 0 ] && grep -aq 'System halted' "$LOG"; then
  PASS=$((PASS+1))
  echo "  PASS (4) System halted printed; QEMU exited rc=0 (window closed)"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (4) QEMU rc=$QEMU_RC, expected 0 (halt did not exit cleanly)"
fi

echo
echo "============================"
echo "memfs smoke: PASS=$PASS FAIL=$FAIL  (expected PASS=4 FAIL=0)"
[ "$FAIL" -eq 0 ]
