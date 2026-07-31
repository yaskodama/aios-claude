#!/usr/bin/env bash
# run_diners_all_aipl.sh — 5-philosopher dining demo where BOTH sides
# are written in AIPL.
#
# Xinu side : abclc/DiningPhilosophersDistXinu.aipl  (Fork×5 + P4/P5)
# PC   side : aice-pi-evolution/.../host_diners.aipl (Coordinator + P1/P2/P3)
#
# Pipeline:
#   1. aipl2c the Xinu sample → C → arm-qemu kernel
#   2. launch QEMU with UART1 RPC on TCP 5555 + smc91c111 SLIRP
#      (hostfwd: 127.0.0.1:8181 → 10.0.2.15:80 for the Xinu HTTP
#      dashboard so the same browser endpoint works as before)
#   3. python3 -u aipl_main.py host_diners.aipl  ←  PC side is AIPL,
#      not Python — the Python here is just the interpreter
#
# Ctrl-C cleans up QEMU + PC AIPL via trap.

set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
XINU="${XINU_RAZ:-/Users/kodamay/projects/xinu-raz/xinu}"
COMPILER_ROOT="${COMPILER_ROOT:-/opt/homebrew/bin/arm-none-eabi-}"
SAMPLE="${SAMPLE:-abclc/DiningPhilosophersDistXinu.aipl}"
HOST_AIPL="${HOST_AIPL:-$HERE/../2026-05-20_xinu_remote_rpc/host_diners.aipl}"

CONSOLE_PORT="${CONSOLE_PORT:-5554}"
RPC_PORT="${RPC_PORT:-5555}"
HOST_HTTP_PORT="${HOST_HTTP_PORT:-8181}"
GUEST_HTTP_PORT="${GUEST_HTTP_PORT:-80}"

cd "$REPO"

echo "--- [1/4] $SAMPLE → Xinu kernel ---"
dune build src/aipl2c.exe
./_build/default/src/aipl2c.exe "$SAMPLE" \
    -o /tmp/diners_all_aipl.c --xinu --max-msgs 0
cp /tmp/diners_all_aipl.c "$XINU/apps/abcl_program.c"
( cd "$XINU/compile" && \
  make PLATFORM=arm-qemu COMPILER_ROOT="$COMPILER_ROOT" \
       DEBUG=-DAIPL_AUTOSTART \
       >/tmp/xinu_all_aipl_build.log 2>&1 )
echo "    xinu.elf $(stat -f%z "$XINU/compile/xinu.elf" 2>/dev/null) bytes"

echo "--- [2/4] launch QEMU ---"
qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
    -kernel "$XINU/compile/xinu.elf" \
    -display none -monitor none -no-reboot \
    -chardev "socket,id=ser0,host=127.0.0.1,port=${CONSOLE_PORT},server=on,wait=off,logfile=/tmp/xinu_all_aipl.uart0.log" \
    -serial "chardev:ser0" \
    -serial "tcp:127.0.0.1:${RPC_PORT},server=on,wait=off" \
    -netdev "user,id=net0,net=10.0.2.0/24,host=10.0.2.2,hostfwd=tcp:127.0.0.1:${HOST_HTTP_PORT}-10.0.2.15:${GUEST_HTTP_PORT}" \
    -nic none \
    -net nic,model=smc91c111,macaddr=52:54:00:12:34:56,netdev=net0 \
    >/tmp/xinu_all_aipl_qemu.log 2>&1 &
QEMU_PID=$!
trap 'echo "--- shutting down ---"; kill $QEMU_PID 2>/dev/null || true' EXIT INT TERM
echo "    qemu pid=$QEMU_PID"

echo "--- [3/4] wait for Xinu RPC dispatcher ---"
RPC_OK=0
for i in $(seq 1 40); do
    # The UART1 socket is in server mode; "ready" once we can connect.
    if (echo > /dev/null < /dev/tcp/127.0.0.1/$RPC_PORT) 2>/dev/null; then
        echo "    RPC up after ${i}s"
        RPC_OK=1
        break
    fi
    sleep 0.5
done
if [ "$RPC_OK" != "1" ]; then
    echo "    FAIL: RPC port $RPC_PORT never opened"
    tail -10 /tmp/xinu_all_aipl_qemu.log
    exit 1
fi

echo "============================================================"
echo "  Xinu side : AIPL  ($SAMPLE)"
echo "  PC   side : AIPL  ($(basename "$HOST_AIPL"))"
echo "  Xinu HTTP : http://127.0.0.1:${HOST_HTTP_PORT}/"
echo "============================================================"

echo "--- [4/4] run PC-side AIPL host_diners.aipl ---"
# `--idle-ms` is set short so the Python AIPL runtime exits once all
# three Philosopher actors are idle (= all done eating).  With
# 20 meals × 3 PC philos the worst case is ~15 min in the AIPL
# message dispatcher (P3 may starve briefly on F1); we cap at
# 1800 sec (30 min) so the launcher doesn't hang indefinitely on
# a deadlock.
RPC_HOST=127.0.0.1 RPC_PORT="$RPC_PORT" \
python3 -u "$REPO/src/python-aipl/aipl_main.py" "$HOST_AIPL" \
    --timeout 1800 --idle-ms 5000 || true

echo ""
echo "--- done ---"
echo "Browse  : http://127.0.0.1:${HOST_HTTP_PORT}/"
echo "UART0 log: /tmp/xinu_all_aipl.uart0.log"
echo "(QEMU still running — Ctrl-C to exit)"
while true; do sleep 1; done
