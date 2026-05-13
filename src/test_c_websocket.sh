#!/usr/bin/env bash
# Smoke test for the C codegen + abcl_ws_runtime.c (libwebsockets).
#
# Generates a small AIPL program that calls ws_listen / ws_send /
# ws_close, links it against abcl_ws_runtime.c and libwebsockets,
# and verifies the binary runs to completion.
set -u
cd "$(dirname "$0")/.."

ABCL2C=./_build/default/src/aipl2c.exe
WS_RT=./src/abcl_ws_runtime.c

if [ ! -x "$ABCL2C" ]; then echo "[FATAL] $ABCL2C missing; dune build"; exit 1; fi
if ! command -v pkg-config >/dev/null 2>&1 && [ ! -d /opt/homebrew/opt/libwebsockets ]; then
  echo "[FATAL] libwebsockets not found"; exit 1
fi

LWS_INC=$(brew --prefix libwebsockets 2>/dev/null)/include
LWS_LIB=$(brew --prefix libwebsockets 2>/dev/null)/lib
OS_INC=$(brew --prefix openssl@3 2>/dev/null)/include

TMPROOT=$(mktemp -d /tmp/aipl-cws.XXXXXX)
trap "rm -rf '$TMPROOT'" EXIT

pass=0; fail=0; total=0

# Case 1: build a program that uses all three ws_ builtins
total=$((total + 1))
cat > "$TMPROOT/ws_smoke.abcl" <<EOF
class Hub {
  method run() {
    var p = ws_listen(9099);
    print("hub up on port " + p);
    var n = ws_send("room", "hello-from-c");
    print("delivered to " + n);
    ws_close(9099);
    print("closed");
  }
}
var h = new Hub();
send h.run();
EOF

if ! "$ABCL2C" "$TMPROOT/ws_smoke.abcl" -o "$TMPROOT/ws_smoke.c" --max-msgs 4 > /dev/null 2>&1; then
  fail=$((fail + 1)); printf '  FAIL  aipl2c\n'
else
  if cc -O2 -Wall -pthread \
        -I"$LWS_INC" -I"$OS_INC" \
        "$TMPROOT/ws_smoke.c" "$WS_RT" \
        -L"$LWS_LIB" -lwebsockets \
        -o "$TMPROOT/ws_smoke" -lm > "$TMPROOT/cc.log" 2>&1; then
    out=$("$TMPROOT/ws_smoke" 2>&1)
    if echo "$out" | grep -q "hub up on port 9099" && \
       echo "$out" | grep -q "delivered to 0" && \
       echo "$out" | grep -q "closed"; then
      pass=$((pass + 1)); printf '  PASS  ws_listen + ws_send + ws_close\n'
    else
      fail=$((fail + 1)); printf '  FAIL  output mismatch:\n'
      echo "$out" | head -5 | sed 's/^/        /'
    fi
  else
    fail=$((fail + 1)); printf '  FAIL  link\n'
    tail -3 "$TMPROOT/cc.log" | sed 's/^/        /'
  fi
fi

echo
echo "==== C-codegen WebSocket smoke summary ===="
echo "  total: $total  pass: $pass  fail: $fail"
exit "$fail"
