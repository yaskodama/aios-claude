#!/usr/bin/env bash
# run_diners_bootstrap.sh — pure-AIPL diners with runtime SPAWN.
#
# Xinu side : abclc/DiningPhilosophersDistXinu_NoMain.abcl
#             Fork + Philosopher classes linked, but NO instances at
#             boot (actor table starts empty).
#
# PC   side : aice-pi-evolution/experiments/2026-05-20_xinu_remote_rpc/
#             host_diners_bootstrap.abcl
#             LOADs the source, then SPAWNs 5 Forks + 2 Xinu philos
#             over UART1 RPC, then kicks them with SEND try_eat, then
#             runs the usual 3 PC philosophers.
#
# Demonstrates the "compile-and-spawn at runtime from the host" path:
# the Xinu image carries only the class CODE; the actor INSTANCES
# come into existence only after PC drives the SPAWN sequence.

set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
XINU="${XINU_RAZ:-/Users/kodamay/projects/xinu-raz/xinu}"
COMPILER_ROOT="${COMPILER_ROOT:-/opt/homebrew/bin/arm-none-eabi-}"
SAMPLE="${SAMPLE:-abclc/DiningPhilosophersDistXinu_NoMain.abcl}"
HOST_AIPL="${HOST_AIPL:-$HERE/../2026-05-20_xinu_remote_rpc/host_diners_bootstrap.abcl}"

CONSOLE_PORT="${CONSOLE_PORT:-5554}"
RPC_PORT="${RPC_PORT:-5555}"
HOST_HTTP_PORT="${HOST_HTTP_PORT:-8181}"
GUEST_HTTP_PORT="${GUEST_HTTP_PORT:-80}"

cd "$REPO"

echo "--- [1/4] $SAMPLE → Xinu kernel ---"
dune build src/aipl2c.exe
./_build/default/src/aipl2c.exe "$SAMPLE" \
    -o /tmp/diners_bootstrap.c --xinu --max-msgs 0
cp /tmp/diners_bootstrap.c "$XINU/apps/abcl_program.c"
( cd "$XINU/compile" && \
  make PLATFORM=arm-qemu COMPILER_ROOT="$COMPILER_ROOT" \
       DEBUG=-DAIPL_AUTOSTART \
       >/tmp/xinu_bootstrap_build.log 2>&1 )
echo "    xinu.elf $(stat -f%z "$XINU/compile/xinu.elf" 2>/dev/null) bytes"

echo "--- [2/4] launch QEMU ---"
qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
    -kernel "$XINU/compile/xinu.elf" \
    -display none -monitor none -no-reboot \
    -chardev "socket,id=ser0,host=127.0.0.1,port=${CONSOLE_PORT},server=on,wait=off,logfile=/tmp/xinu_bootstrap.uart0.log" \
    -serial "chardev:ser0" \
    -serial "tcp:127.0.0.1:${RPC_PORT},server=on,wait=off" \
    -netdev "user,id=net0,net=10.0.2.0/24,host=10.0.2.2,hostfwd=tcp:127.0.0.1:${HOST_HTTP_PORT}-10.0.2.15:${GUEST_HTTP_PORT}" \
    -nic none \
    -net nic,model=smc91c111,macaddr=52:54:00:12:34:56,netdev=net0 \
    >/tmp/xinu_bootstrap_qemu.log 2>&1 &
QEMU_PID=$!
trap 'echo "--- shutting down ---"; kill $QEMU_PID 2>/dev/null || true' EXIT INT TERM
echo "    qemu pid=$QEMU_PID"

echo "--- [3/4] wait for Xinu RPC dispatcher ---"
RPC_OK=0
for i in $(seq 1 40); do
    if (echo > /dev/null < /dev/tcp/127.0.0.1/$RPC_PORT) 2>/dev/null; then
        echo "    RPC up after ${i}s"
        RPC_OK=1
        break
    fi
    sleep 0.5
done
[ "$RPC_OK" = "1" ] || { echo "FAIL RPC port never opened"; exit 1; }

echo "============================================================"
echo "  Xinu side : empty actor table (only classes linked)"
echo "  PC   side : $(basename "$HOST_AIPL")"
echo "  Xinu HTTP : http://127.0.0.1:${HOST_HTTP_PORT}/"
echo "============================================================"

echo "--- [4/4] run PC bootstrap host ---"
RPC_HOST=127.0.0.1 RPC_PORT="$RPC_PORT" \
python3 -u "$REPO/src/python-aipl/aipl_main.py" "$HOST_AIPL" \
    --timeout 1800 --idle-ms 5000 || true

echo ""
echo "--- done ---"
echo "Browse  : http://127.0.0.1:${HOST_HTTP_PORT}/"
echo "(QEMU still running — Ctrl-C to exit)"
while true; do sleep 1; done
