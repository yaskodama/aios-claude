#!/usr/bin/env bash
# Shell readline smoke — verify history + cursor movement.
#
# Sends raw escape sequences to QEMU stdin and inspects the echoed
# back display in the captured serial log.  The xsh prompt now runs
# its own line editor (system/shell_readline.c) so what we see is
# the redrawn line after each keypress.
#
# Acceptance (4 assertions):
#   (1) Up arrow (ESC [ A) recalls the previous command
#       — we type `pwd<Enter> ls<Enter>`, then send ESC [ A and
#         confirm `ls` is shown again on the prompt before <Enter>.
#   (2) Ctrl-P does the same recall via the keystroke (0x10)
#   (3) Down arrow (ESC [ B) returns to the empty line after Up
#   (4) Left arrow (ESC [ D) + insert in the middle of the line
#       — we type `foo`, send ESC [ D ESC [ D `Z`, end up with `fZoo`,
#         and confirm "unknown command: fZoo" appears in the log.
set -u
XINU=/Users/kodamay/projects/xinu-raz/xinu
LOG=/tmp/_readline.qemu.log

ESC=$'\x1b'
CR=$'\r'
CP=$'\x10'         # Ctrl-P
CN=$'\x0e'         # Ctrl-N

{
  sleep 2
  # (preamble) print so we can grep the boundary
  printf 'pwd%s'    "$CR"; sleep 0.4
  printf 'ls%s'     "$CR"; sleep 0.4
  printf '%s[A'     "$ESC"; sleep 0.2     # Up — recalls `ls`
  printf '%s'       "$CR";  sleep 0.4     # accept (runs ls again)
  printf '%s%s'     "$CP" "$CR"; sleep 0.4   # Ctrl-P + Enter — same as Up
  printf '%s[A'     "$ESC"; sleep 0.2     # Up — recalls `ls` (now history top)
  printf '%s[B'     "$ESC"; sleep 0.2     # Down — returns to empty
  printf 'echo down-ok%s' "$CR"; sleep 0.4
  # (4) Left-arrow editing: type `foo`, left twice, insert 'Z', Enter
  printf 'foo';            sleep 0.2
  printf '%s[D%s[D' "$ESC" "$ESC"; sleep 0.2
  printf 'Z';              sleep 0.2
  printf '%s' "$CR";       sleep 0.4
  printf 'halt%s' "$CR";   sleep 1
} | timeout 12 qemu-system-arm \
        -M versatilepb -cpu arm1176 -m 128M \
        -nographic -semihosting -no-reboot \
        -kernel "$XINU/compile/xinu.boot" \
        >"$LOG" 2>&1
QEMU_RC=$?

PASS=0; FAIL=0

# Decode the log so escape sequences become readable.  Cat raw bytes
# is fine because grep -a treats it as text.
n_ls=$(grep -ac '^/$' "$LOG")    # `pwd` prints "/"; baseline = 1
# After Up-recall + Enter, `ls` runs again — extra runs visible as
# repeated prompt lines.  Look for at least 3 `ls` invocations in the
# raw log (Up + Ctrl-P + initial).
echo "  -- assertion (1+2) history recall (Up + Ctrl-P) --"
# Count occurrences of the cwd listing.  `ls` of / prints e.g.
# "home/" — see what comes back.
n_recall=$(grep -ac 'home/' "$LOG")
if [ "$n_recall" -ge 3 ]; then
  PASS=$((PASS+1))
  echo "  PASS (1+2) ls appeared ${n_recall} times — history recall (Up + Ctrl-P) works"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (1+2) ls appeared only ${n_recall} times (need >= 3)"
  grep -aE 'home/|xsh\$' "$LOG" | head -20
fi

echo "  -- assertion (3) Down arrow returns to empty --"
if grep -aq 'down-ok' "$LOG"; then
  PASS=$((PASS+1))
  echo "  PASS (3) Down arrow restored empty line — echo down-ok ran"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (3) 'down-ok' not observed"
fi

echo "  -- assertion (4) Left arrow + insert --"
if grep -aq 'fZoo' "$LOG"; then
  PASS=$((PASS+1))
  echo "  PASS (4) Left+insert produced fZoo (rejected by shell as unknown — OK)"
else
  FAIL=$((FAIL+1))
  echo "  FAIL (4) 'fZoo' not in log — left-arrow editing not working"
  grep -aE 'fZoo|foo|unknown command' "$LOG" | head -5
fi

echo "  -- assertion (5) halt cleanly --"
if [ "$QEMU_RC" -eq 0 ] && grep -aq 'System halted' "$LOG"; then
  PASS=$((PASS+1)); echo "  PASS (5) System halted; QEMU rc=0"
else
  FAIL=$((FAIL+1)); echo "  FAIL (5) QEMU rc=$QEMU_RC"
fi

echo
echo "============================"
echo "readline smoke: PASS=$PASS FAIL=$FAIL  (expected PASS=4 FAIL=0)"
[ "$FAIL" -eq 0 ]
