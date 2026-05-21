#!/usr/bin/env bash
# run_diners_web.sh — 5-哲学者デモ + Web ダッシュボード起動.
#
# 1. abclc/DiningPhilosophersDistXinu.abcl を aipl2c → C → Xinu kernel build
# 2. QEMU を以下の構成で起動:
#      UART0 (console)  → TCP 127.0.0.1:5554 (server)
#      UART1 (AIPL RPC) → TCP 127.0.0.1:5555 (server)
# 3. host_diners_web.py を起動 (HTTP は 0.0.0.0:8080)
# 4. http://localhost:8080/ をブラウザで開く
#
# 終了: Ctrl-C で host_diners_web.py を止めると、trap で QEMU も kill.
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
XINU="${XINU_RAZ:-/Users/kodamay/projects/xinu-raz/xinu}"
COMPILER_ROOT="${COMPILER_ROOT:-/opt/homebrew/bin/arm-none-eabi-}"
SAMPLE="${SAMPLE:-abclc/DiningPhilosophersDistXinu.abcl}"

CONSOLE_PORT="${CONSOLE_PORT:-5554}"
RPC_PORT="${RPC_PORT:-5555}"
WEB_PORT="${WEB_PORT:-8080}"

cd "$REPO"

echo "--- [1/4] aipl2c build ---"
dune build src/aipl2c.exe

echo "--- [2/4] $SAMPLE → C (--xinu, AUTOSTART) ---"
./_build/default/src/aipl2c.exe "$SAMPLE" \
    -o /tmp/diners_web_xinu.c --xinu --max-msgs 0
cp /tmp/diners_web_xinu.c "$XINU/apps/abcl_program.c"

echo "--- [3/4] xinu kernel build ---"
( cd "$XINU/compile" &&
  make PLATFORM=arm-qemu COMPILER_ROOT="$COMPILER_ROOT" \
       >/tmp/xinu_diners_build.log 2>&1 )
echo "    xinu.elf $(stat -f%z "$XINU/compile/xinu.elf" 2>/dev/null || \
                       stat -c%s "$XINU/compile/xinu.elf") bytes"

echo "--- [4/4] launch QEMU (UART0→tcp:$CONSOLE_PORT, UART1→tcp:$RPC_PORT) ---"
qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
    -kernel "$XINU/compile/xinu.elf" \
    -display none -monitor none \
    -serial "tcp:127.0.0.1:${CONSOLE_PORT},server=on,wait=off" \
    -serial "tcp:127.0.0.1:${RPC_PORT},server=on,wait=off" \
    -no-reboot >/tmp/xinu_diners_qemu.log 2>&1 &
QEMU_PID=$!
trap 'echo "--- shutting down ---"; kill $QEMU_PID 2>/dev/null || true' EXIT INT TERM
echo "    qemu pid=$QEMU_PID"

# Give QEMU a moment to bind the TCP listening sockets.
sleep 1

echo "--- starting host_diners_web.py ---"
echo "    open: http://127.0.0.1:${WEB_PORT}/"
CONSOLE_HOST=127.0.0.1 CONSOLE_PORT="$CONSOLE_PORT" \
RPC_HOST=127.0.0.1     RPC_PORT="$RPC_PORT" \
WEB_HOST=127.0.0.1     WEB_PORT="$WEB_PORT" \
python3 -u "$HERE/host_diners_web.py"
