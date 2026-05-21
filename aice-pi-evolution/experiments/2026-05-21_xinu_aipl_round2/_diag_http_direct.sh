#!/usr/bin/env bash
# _diag_http_direct.sh — Xinu に直接 HTTP リクエスト (host bridge なし).
#
# 1. NetInitOnlyXinu (AIPL は net_init を呼ぶだけ) を Xinu kernel に焼く
# 2. QEMU を SLIRP + hostfwd 127.0.0.1:8181 -> 10.0.2.15:80 で起動
# 3. Xinu の HTTP server (apps/abcl_xinu_http.c) が auto-start で立ち上がるのを待つ
# 4. 127.0.0.1:8181 に curl で / と /api/actors を叩く
# 5. 期待: Xinu 直接生成 HTML が返ってくる
set -u
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
XINU="${XINU_RAZ:-/Users/kodamay/projects/xinu-raz/xinu}"
COMPILER_ROOT="${COMPILER_ROOT:-/opt/homebrew/bin/arm-none-eabi-}"
UART0_LOG=/tmp/n1_http.uart0.log
PCAP=/tmp/n1_http.pcap

echo "======================================================================"
echo "  Xinu Direct HTTP diagnostic"
echo "======================================================================"
cd "$ROOT"

echo "--- [1] AIPL NetInitOnly → C → xinu.elf ---"
dune build src/aipl2c.exe >/tmp/n1_http_build.log 2>&1 || { echo FAIL aipl2c; exit 1; }
./_build/default/src/aipl2c.exe abclc/NetInitOnlyXinu.abcl \
    -o /tmp/n1_http.c --xinu --max-msgs 0 >/tmp/n1_http_a2c.log 2>&1
cp /tmp/n1_http.c "$XINU/apps/abcl_program.c"
( cd "$XINU/compile" \
  && make PLATFORM=arm-qemu COMPILER_ROOT="$COMPILER_ROOT" clean >/dev/null 2>&1 \
  && make PLATFORM=arm-qemu COMPILER_ROOT="$COMPILER_ROOT" DEBUG=-DAIPL_AUTOSTART \
     >/tmp/n1_http_xinu.log 2>&1 ) \
  || { echo "FAIL: xinu build"; tail -30 /tmp/n1_http_xinu.log; exit 1; }
echo "    xinu.boot $(stat -f%z "$XINU/compile/xinu.boot" 2>/dev/null) bytes"

echo "--- [2] launch QEMU with hostfwd 127.0.0.1:8181 -> 10.0.2.15:80 ---"
rm -f "$PCAP" "$UART0_LOG"
qemu-system-arm \
    -M versatilepb -cpu arm1176 -m 128M \
    -nographic -no-reboot \
    -kernel "$XINU/compile/xinu.boot" \
    -netdev user,id=net0,net=10.0.2.0/24,host=10.0.2.2,hostfwd=tcp:127.0.0.1:8181-10.0.2.15:80 \
    -nic none \
    -net nic,model=smc91c111,macaddr=52:54:00:12:34:56,netdev=net0 \
    -object filter-dump,id=f0,netdev=net0,file="$PCAP" \
    >"$UART0_LOG" 2>&1 &
QEMU=$!
trap 'kill $QEMU 2>/dev/null || true' EXIT INT TERM
echo "    qemu pid=$QEMU"

# Wait for the Xinu HTTP server to respond.  The kernel-side trace
# was removed during cleanup, so we probe the endpoint directly.
echo "--- [3] wait for Xinu HTTP server (curl /api/uptime) ---"
HTTP_OK=0
for i in $(seq 1 30); do
    if curl -s -m 1 -o /dev/null -w "%{http_code}" \
         "http://127.0.0.1:8181/api/uptime" 2>/dev/null \
         | grep -q "^200$"; then
        echo "    HTTP responding after ${i}s"
        HTTP_OK=1
        break
    fi
    sleep 1
done
if [ "$HTTP_OK" != "1" ]; then
    echo "    FAIL: HTTP server never responded"
    tail -20 "$UART0_LOG"
    exit 1
fi

echo "--- [4] curl Xinu directly via hostfwd ---"
echo "    GET / ↴"
curl -s -m 5 -o /tmp/n1_http_root.html -w "    status=%{http_code} bytes=%{size_download} time=%{time_total}\n" \
    http://127.0.0.1:8181/ || echo "    curl / failed"
echo "    response head ↴"
head -3 /tmp/n1_http_root.html 2>/dev/null | sed 's/^/      /'

echo "    GET /api/actors ↴"
curl -s -m 5 -o /tmp/n1_http_actors.txt -w "    status=%{http_code} bytes=%{size_download} time=%{time_total}\n" \
    http://127.0.0.1:8181/api/actors || echo "    curl /api/actors failed"
echo "    response ↴"
cat /tmp/n1_http_actors.txt 2>/dev/null | sed 's/^/      /'

echo "    GET /api/uptime ↴"
curl -s -m 5 http://127.0.0.1:8181/api/uptime | sed 's/^/      /' || echo "    failed"

echo "--- [5] UART0 [http] markers ---"
grep -aE "\[http\]" "$UART0_LOG" | head -20 | sed 's/^/    /'

echo "======================================================================"
echo "  diagnostic complete"
echo "======================================================================"
