#!/usr/bin/env bash
# run_diners_xinu_http.sh — 5-哲学者デモ + Xinu 直接 HTTP.
#
# 旧 run_diners_web.sh では PC 側 (host_diners_web.py) が HTTP も提供
# していたが、Round 2 Step C で Xinu の TCP/IP+HTTP 直接化が出来たので
# ここでは PC 側は 3 哲学者の orchestration (UART1 RPC) のみ.
# ブラウザは Xinu 直接の `http://127.0.0.1:8181/` を見る.
#
# 物理経路:
#       QEMU (Xinu)
#         ├ UART0  →  tcp:5554 (console、optional)
#         ├ UART1  →  tcp:5555 (PC philosophers RPC)
#         └ smc91c111 → SLIRP → hostfwd 127.0.0.1:8181 → 10.0.2.15:80
#                                                  (Xinu HTTP server)
#       host_diners.py                  Browser
#         └ TCP 5555  → P1/P2/P3        └ http://127.0.0.1:8181/
#
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
XINU="${XINU_RAZ:-/Users/kodamay/projects/xinu-raz/xinu}"
COMPILER_ROOT="${COMPILER_ROOT:-/opt/homebrew/bin/arm-none-eabi-}"
SAMPLE="${SAMPLE:-abclc/DiningPhilosophersDistXinu.aipl}"

CONSOLE_PORT="${CONSOLE_PORT:-5554}"
RPC_PORT="${RPC_PORT:-5555}"
HOST_HTTP_PORT="${HOST_HTTP_PORT:-8181}"
GUEST_HTTP_PORT="${GUEST_HTTP_PORT:-80}"
PCAP="${PCAP:-/tmp/diners_xinu_http.pcap}"

cd "$REPO"

echo "--- [1/5] aipl2c build ---"
dune build src/aipl2c.exe

echo "--- [2/5] $SAMPLE → C (--xinu, AUTOSTART) ---"
./_build/default/src/aipl2c.exe "$SAMPLE" \
    -o /tmp/diners_xinu_http.c --xinu --max-msgs 0
cp /tmp/diners_xinu_http.c "$XINU/apps/abcl_program.c"

echo "--- [3/5] xinu kernel build ---"
( cd "$XINU/compile" &&
  make PLATFORM=arm-qemu COMPILER_ROOT="$COMPILER_ROOT" \
       DEBUG=-DAIPL_AUTOSTART \
       >/tmp/xinu_diners_http_build.log 2>&1 )
echo "    xinu.elf $(stat -f%z "$XINU/compile/xinu.elf" 2>/dev/null || \
                       stat -c%s "$XINU/compile/xinu.elf") bytes"

echo "--- [4/5] launch QEMU ---"
echo "        UART0 → tcp:$CONSOLE_PORT"
echo "        UART1 → tcp:$RPC_PORT (PC philosophers RPC)"
echo "        SLIRP → hostfwd 127.0.0.1:$HOST_HTTP_PORT -> 10.0.2.15:$GUEST_HTTP_PORT"
rm -f "$PCAP"
qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
    -kernel "$XINU/compile/xinu.elf" \
    -display none -monitor none -no-reboot \
    -chardev "socket,id=ser0,host=127.0.0.1,port=${CONSOLE_PORT},server=on,wait=off,logfile=/tmp/xinu_uart0.log" \
    -serial "chardev:ser0" \
    -serial "tcp:127.0.0.1:${RPC_PORT},server=on,wait=off" \
    -netdev "user,id=net0,net=10.0.2.0/24,host=10.0.2.2,hostfwd=tcp:127.0.0.1:${HOST_HTTP_PORT}-10.0.2.15:${GUEST_HTTP_PORT}" \
    -nic none \
    -net nic,model=smc91c111,macaddr=52:54:00:12:34:56,netdev=net0 \
    -object "filter-dump,id=f0,netdev=net0,file=$PCAP" \
    >/tmp/xinu_diners_http_qemu.log 2>&1 &
QEMU_PID=$!
trap 'echo "--- shutting down ---"; kill $QEMU_PID 2>/dev/null || true' EXIT INT TERM
echo "    qemu pid=$QEMU_PID"

# Wait for HTTP server to actually respond.  UART0 console is routed
# to TCP:$CONSOLE_PORT (not QEMU stdout), so we probe the HTTP endpoint
# directly instead of grepping a log file.
echo "--- [5/5] wait for Xinu HTTP server (curl /api/uptime) ---"
HTTP_OK=0
for i in $(seq 1 40); do
    if curl -s -m 1 -o /dev/null -w "%{http_code}" \
         "http://127.0.0.1:${HOST_HTTP_PORT}/api/uptime" 2>/dev/null \
         | grep -q "^200$"; then
        echo "    Xinu HTTP responding after ${i}s"
        HTTP_OK=1
        break
    fi
    sleep 1
done
if [ "$HTTP_OK" != "1" ]; then
    echo "    FAIL: Xinu HTTP never responded on port $HOST_HTTP_PORT"
    exit 1
fi

echo ""
echo "============================================================"
echo "  ✅ ready"
echo "       Browser:    http://127.0.0.1:${HOST_HTTP_PORT}/"
echo "       UART0 log:  /tmp/xinu_diners_http_qemu.log"
echo "       PC philos:  python3 ../2026-05-20_xinu_remote_rpc/host_diners.py"
echo "                   (= 3 PC philosophers over UART1:${RPC_PORT})"
echo "  Ctrl-C で QEMU 含めクリーン終了."
echo "============================================================"

# Run PC philosophers (3 threads) — orchestration only.  Xinu HTTP
# is independent and keeps serving after the diners finish.
RPC_HOST=127.0.0.1 RPC_PORT="$RPC_PORT" MEALS="${MEALS:-5}" \
    python3 -u "$HERE/../2026-05-20_xinu_remote_rpc/host_diners.py" || true

echo ""
echo "(diners finished; Xinu HTTP still up — browse / poll then Ctrl-C)"
# Stay alive so user can keep browsing.
while true; do
    sleep 1
done
