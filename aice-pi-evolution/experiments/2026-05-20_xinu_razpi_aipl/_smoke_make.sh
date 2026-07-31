#!/usr/bin/env bash
# make smoke — verify the existing `make` command builds executables
# from both C (.c) and ABCL/AIPL (.aipl) sources, auto-generating a
# Makefile on first use.
#
# Demo dirs seeded by xfsBootstrap (system/main.c):
#   /home                        hello.c, sum.c
#   /home/abclcp/abclc           PingPong.aipl, RotLines.aipl
#
# Acceptance (6 assertions):
#   (1) C demo: `make` in /home auto-generates a Makefile listing
#       both hello and sum as targets
#   (2) The C binaries are produced and runnable (`run hello`
#       prints "hello..."; `run sum` prints "sum 1..10 = 55")
#   (3) ABCL demo: `make` in /home/abclcp/abclc auto-generates a
#       Makefile that lists PingPong and RotLines
#   (4) The ABCL binaries are produced (visible in `ls` and `run`able)
#   (5) Running `run PingPong` shows the actor execution trace
#   (6) halt cleanly exits QEMU (rc=0, Cocoa window closes)
set -u
XINU=/Users/kodamay/projects/xinu-raz/xinu
COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi-
LOG=/tmp/_make.qemu.log

( cd "$XINU/compile" \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT clean >/dev/null 2>&1 \
  && make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT \
     >/tmp/_make.build.log 2>&1 ) \
  || { echo "FAIL build"; tail -30 /tmp/_make.build.log; exit 1; }

{
  sleep 2
  printf '\n'
  # ============================================================
  # C demo: /home has hello.c + sum.c
  # ============================================================
  printf 'cd /home\n';            sleep 0.4
  printf 'ls\n';                  sleep 0.4
  printf 'make\n';                sleep 2.5
  printf 'ls\n';                  sleep 0.5
  printf '%s\n' '--- C-MAKEFILE-BEGIN ---'; sleep 0.3
  printf 'cat Makefile\n';        sleep 0.6
  printf '%s\n' '--- C-MAKEFILE-END ---';   sleep 0.3
  printf 'run hello\n';           sleep 0.6
  printf 'run sum\n';             sleep 0.6
  # ============================================================
  # ABCL demo: /home/abclcp/abclc has PingPong.aipl + RotLines.aipl
  # ============================================================
  printf 'cd /home/abclcp/abclc\n'; sleep 0.4
  printf 'ls\n';                    sleep 0.4
  printf 'make\n';                  sleep 4.0
  printf 'ls\n';                    sleep 0.5
  printf '%s\n' '--- ABCL-MAKEFILE-BEGIN ---'; sleep 0.3
  printf 'cat Makefile\n';          sleep 0.6
  printf '%s\n' '--- ABCL-MAKEFILE-END ---';   sleep 0.3
  printf 'run PingPong\n';          sleep 1.2
  printf 'halt\n';                  sleep 1
} | timeout 30 qemu-system-arm \
        -M versatilepb -cpu arm1176 -m 128M \
        -nographic -semihosting -no-reboot \
        -kernel "$XINU/compile/xinu.boot" \
        >"$LOG" 2>&1
QEMU_RC=$?

PASS=0; FAIL=0

echo "  -- assertion (1) C Makefile auto-gen --"
c_mk=$(awk '/--- C-MAKEFILE-BEGIN ---/,/--- C-MAKEFILE-END ---/' "$LOG")
if echo "$c_mk" | grep -qE 'TARGETS\s*=.*hello.*sum|hello:\s*hello\.c|sum:\s*sum\.c'; then
  PASS=$((PASS+1))
  echo "  PASS (1) Makefile generated in /home with hello + sum targets"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (1) C Makefile missing or malformed:"
  echo "$c_mk" | head -15
fi

echo "  -- assertion (2) C binaries run --"
if grep -aE '^hello\.\.\.|^hello' "$LOG" >/dev/null \
   && grep -aE 'sum 1\.\.10 = 55|sum.*= 55' "$LOG" >/dev/null; then
  PASS=$((PASS+1))
  echo "  PASS (2) hello + sum binaries executed correctly"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (2) one or both C binaries failed:"
  grep -aE 'hello|sum 1' "$LOG" | head -5
fi

echo "  -- assertion (3) ABCL Makefile auto-gen --"
abcl_mk=$(awk '/--- ABCL-MAKEFILE-BEGIN ---/,/--- ABCL-MAKEFILE-END ---/' "$LOG")
if echo "$abcl_mk" | grep -qE 'TARGETS\s*=.*PingPong.*RotLines|PingPong:\s*PingPong\.aipl|RotLines:\s*RotLines\.aipl'; then
  PASS=$((PASS+1))
  echo "  PASS (3) Makefile generated in /home/abclcp/abclc with PingPong + RotLines targets"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (3) ABCL Makefile missing or malformed:"
  echo "$abcl_mk" | head -15
fi

echo "  -- assertion (4) ABCL targets built --"
# After make, both binaries should appear without .aipl/.c suffix.
abcl_ls=$(awk '/cd \/home\/abclcp\/abclc/{p=1}/cd \/home\/abclcp\/abclc/,/run PingPong/' "$LOG")
if echo "$abcl_ls" | grep -qE '^PingPong\s*$' && echo "$abcl_ls" | grep -qE '^RotLines\s*$'; then
  PASS=$((PASS+1))
  echo "  PASS (4) PingPong + RotLines a.out binaries present after make"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (4) ABCL binaries missing — ls tail:"
  echo "$abcl_ls" | grep -aE 'PingPong|RotLines' | head -10
fi

echo "  -- assertion (5) ABCL run trace --"
if grep -aE 'Player [0-9]+:|tick \(n=|\[abcl\] done|hits=' "$LOG" >/dev/null; then
  PASS=$((PASS+1))
  echo "  PASS (5) PingPong actor trace observed"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (5) no actor trace"
fi

echo "  -- assertion (6) halt cleanly exits --"
if [ "$QEMU_RC" -eq 0 ] && grep -aq 'System halted' "$LOG"; then
  PASS=$((PASS+1))
  echo "  PASS (6) System halted printed; QEMU rc=0"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (6) QEMU rc=$QEMU_RC"
fi

echo
echo "============================"
echo "make smoke: PASS=$PASS FAIL=$FAIL  (expected PASS=6 FAIL=0)"
[ "$FAIL" -eq 0 ]
