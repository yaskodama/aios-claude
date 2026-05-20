#!/usr/bin/env bash
# host_rpc_demo.sh — H4 reference client (bash + nc).
#
# Talks to the Xinu RPC dispatcher exposed on TCP 127.0.0.1:5555
# (= QEMU -serial tcp: mapped to PL011 UART1).
#
# Usage:
#   1. Boot QEMU with the RemoteRpcDemoXinu program + UART1 socket:
#        cd $XINU/compile
#        make PLATFORM=arm-qemu COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi- \
#             DEBUG=-DAIPL_AUTOSTART
#        qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
#            -kernel xinu.elf -nographic \
#            -serial mon:stdio \
#            -serial tcp:127.0.0.1:5555,server=on,wait=off
#   2. In another terminal: ./host_rpc_demo.sh
#
# Each command is sent on its own line.  The reply line(s) are echoed
# back to stdout so a smoke can grep them.
set -u
HOST=${RPC_HOST:-127.0.0.1}
PORT=${RPC_PORT:-5555}

# Build the command stream once so nc sees a contiguous byte stream
# regardless of how fast the shell dispatches lines.
SCRIPT="$(cat <<'EOF'
PING
SEND 0 bump
SEND 0 bump
SEND 0 dump
SEND 1 set_who 42
SEND 1 hello
QUERY 0 0
QUERY 1 0
LIST
EOF
)"

echo "--- sending ---"
echo "$SCRIPT"
echo "--- replies  ---"

# nc -w 2 = 2-sec idle timeout on the read side; long enough for the
# kernel to print the OK/ERR reply, short enough that the script exits
# promptly once the conversation is done.
echo "$SCRIPT" | nc -w 2 "$HOST" "$PORT"
