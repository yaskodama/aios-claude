#!/usr/bin/env bash
# _diag_n1_arp.sh — Step A: N1 ARP/TCP 診断 + Xinu HTTP component link 確認.
#
# 1. AIPL TcpEchoClientXinu を arm-qemu 用に build
# 2. QEMU を pcap dump 付きで起動 (-net dump,file=/tmp/n1_diag.pcap)
# 3. wire 上のパケットを tcpdump で要約、ARP/TCP 進行を見る
# 4. arm-qemu APPCOMPS に http を追加して build が通るか試す
set -u
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
XINU="${XINU_RAZ:-/Users/kodamay/projects/xinu-raz/xinu}"
COMPILER_ROOT="${COMPILER_ROOT:-/opt/homebrew/bin/arm-none-eabi-}"

UART0_LOG=/tmp/n1_diag.uart0.log
PCAP=/tmp/n1_diag.pcap
ECHO_PORT=49199

echo "======================================================================"
echo "  Step A : N1 ARP/TCP diagnostic + HTTP component link check"
echo "======================================================================"

cd "$ROOT"

# ─── (1) AIPL N1 sample build ─────────────────────────────────
echo "--- [1] AIPL TcpEchoClientXinu → C → Xinu kernel ---"
dune build src/aipl2c.exe >/tmp/n1_diag_build.log 2>&1 || {
  echo "FAIL: dune build"; tail /tmp/n1_diag_build.log; exit 1; }

./_build/default/src/aipl2c.exe abclc/TcpEchoClientXinu.abcl \
    -o /tmp/n1_diag.c --xinu --max-msgs 0 >/tmp/n1_diag_a2c.log 2>&1 || {
  echo "FAIL: aipl2c"; cat /tmp/n1_diag_a2c.log; exit 1; }
cp /tmp/n1_diag.c "$XINU/apps/abcl_program.c"

( cd "$XINU/compile" \
  && make PLATFORM=arm-qemu COMPILER_ROOT="$COMPILER_ROOT" clean >/dev/null 2>&1 \
  && make PLATFORM=arm-qemu COMPILER_ROOT="$COMPILER_ROOT" DEBUG=-DAIPL_AUTOSTART \
     >/tmp/n1_diag_xinu.log 2>&1 ) || {
  echo "FAIL: xinu build (without http)"; tail -30 /tmp/n1_diag_xinu.log; exit 1; }
echo "    xinu.elf $(stat -f%z "$XINU/compile/xinu.elf" 2>/dev/null) bytes"

# ─── (2) host echo server ──────────────────────────────────────
echo "--- [2] host TCP echo on 0.0.0.0:$ECHO_PORT ---"
PYECHO=/tmp/n1_diag_echo.py
cat > "$PYECHO" <<'PY'
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('0.0.0.0', int(sys.argv[1])))
s.listen(1); s.settimeout(20)
print(f"echo: listening", flush=True)
try:
    c, addr = s.accept(); print(f"echo: conn from {addr}", flush=True)
    c.settimeout(5); data = c.recv(1024)
    print(f"echo: recv {len(data)} bytes: {data!r}", flush=True)
    c.sendall(b"ECHO:" + data); c.close()
    print("echo: replied + closed", flush=True)
except Exception as e: print(f"echo: ex: {e}", flush=True)
finally: s.close()
PY
rm -f /tmp/n1_diag_echo.log
python3 "$PYECHO" "$ECHO_PORT" >/tmp/n1_diag_echo.log 2>&1 &
ECHO_PID=$!
sleep 0.5

# ─── (3) QEMU with pcap dump ───────────────────────────────────
echo "--- [3] qemu-system-arm with -net dump,file=$PCAP ---"
rm -f "$PCAP" "$UART0_LOG"
timeout 25 qemu-system-arm \
    -M versatilepb -cpu arm1176 -m 128M \
    -nographic -no-reboot \
    -kernel "$XINU/compile/xinu.boot" \
    -netdev user,id=net0,net=10.0.2.0/24,host=10.0.2.2,hostfwd=tcp:127.0.0.1:8181-10.0.2.15:80 \
    -nic none \
    -net nic,model=smc91c111,macaddr=52:54:00:12:34:56,netdev=net0 \
    -object filter-dump,id=f0,netdev=net0,file="$PCAP" \
    >"$UART0_LOG" 2>&1 || true

kill "$ECHO_PID" 2>/dev/null || true
wait "$ECHO_PID" 2>/dev/null || true

# ─── (4) UART0 から AIPL 出力を抽出 ─────────────────────────────
echo "--- [4] UART0 AIPL markers ---"
grep -aE '\[aipl\] net_(init|connect|send|recv|close)' "$UART0_LOG" \
  | head -10 | sed 's/^/    /'

# ─── (5) pcap 解析 ────────────────────────────────────────────
echo "--- [5] pcap analysis (/usr/sbin/tcpdump -r $PCAP) ---"
if [ ! -s "$PCAP" ]; then
    echo "    NO PCAP (QEMU did not emit any frames)"
else
    sz=$(stat -f%z "$PCAP" 2>/dev/null)
    echo "    pcap size: $sz bytes"
    # macOS tcpdump
    tcpdump -nn -r "$PCAP" 2>/dev/null \
      | awk 'NR<=40' | sed 's/^/    /'
    echo "    ─── packet type tally ────"
    tcpdump -nn -r "$PCAP" 2>/dev/null \
      | awk '/ARP, Request/  {arp_req++}
             /ARP, Reply/    {arp_rep++}
             /Flags \[S\]/   {syn++}
             /Flags \[S\.\]/ {synack++}
             /Flags \[\./    {acks++}
             /ICMP/          {icmp++}
             END {
               printf("    ARP Request : %d\n", arp_req)
               printf("    ARP Reply   : %d\n", arp_rep)
               printf("    TCP SYN     : %d\n", syn)
               printf("    TCP SYN+ACK : %d\n", synack)
               printf("    TCP ACK/data: %d\n", acks)
               printf("    ICMP        : %d\n", icmp)
             }'
fi

# ─── (6) HTTP component を APPCOMPS に追加して link が通るか ───
echo "--- [6] add 'http' to arm-qemu APPCOMPS + rebuild ---"
PV="$XINU/compile/platforms/arm-qemu/platformVars"
if grep -qE '^APPCOMPS.*[[:space:]]http([[:space:]]|$)' "$PV"; then
    echo "    already includes http"
else
    cp "$PV" /tmp/n1_diag_platformVars.bak
    python3 - <<PY
path = r"""$PV"""
with open(path) as f: lines = f.readlines()
out = []
for L in lines:
    if L.startswith("APPCOMPS"):
        L = L.rstrip("\n").rstrip() + " http\n"
    out.append(L)
open(path,'w').writelines(out)
PY
    echo "    edited APPCOMPS to include 'http'"
    grep '^APPCOMPS' "$PV" | sed 's/^/      /'
fi

( cd "$XINU/compile" \
  && make PLATFORM=arm-qemu COMPILER_ROOT="$COMPILER_ROOT" clean >/dev/null 2>&1 \
  && make PLATFORM=arm-qemu COMPILER_ROOT="$COMPILER_ROOT" DEBUG=-DAIPL_AUTOSTART \
     >/tmp/n1_diag_xinu_with_http.log 2>&1 )
RC=$?
if [ $RC -eq 0 ]; then
    sz=$(stat -f%z "$XINU/compile/xinu.elf" 2>/dev/null)
    echo "    OK   xinu.elf with http = $sz bytes"
else
    echo "    FAIL build with http (rc=$RC)"
    grep -aE 'error:|undefined reference|cannot find' /tmp/n1_diag_xinu_with_http.log \
      | head -20 | sed 's/^/      /'
    # restore platformVars so subsequent runs still work
    if [ -f /tmp/n1_diag_platformVars.bak ]; then
        cp /tmp/n1_diag_platformVars.bak "$PV"
        echo "    reverted platformVars"
    fi
fi

echo "======================================================================"
echo "  Step A complete — see $PCAP and $UART0_LOG"
echo "======================================================================"
