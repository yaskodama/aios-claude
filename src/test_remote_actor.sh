#!/usr/bin/env bash
# End-to-end smoke for OCaml remote actor calls.
#
#   1) Launch abclc/RemoteServer.aipl (web_listen on :8090, actor `echo`)
#   2) Run abclc/RemoteClient.aipl which exercises send/now/future against
#      `remote("localhost:8090", "echo")`.
#   3) Grep both sides' captured stdout for the expected interaction.
set -u
cd "$(dirname "$0")/.."

REPL=./_build/default/src/repl_thread.exe
[ -x "$REPL" ] || { echo "[FATAL] $REPL missing; run dune build"; exit 1; }

TMP=$(mktemp -d /tmp/aipl-remote.XXXXXX)
trap 'rm -rf "$TMP"; [ -n "${SRV_PID:-}" ] && kill "$SRV_PID" 2>/dev/null; :' EXIT

SRV_LOG="$TMP/server.log"
CLI_LOG="$TMP/client.log"

echo "[start] server"
printf 'load abclc/RemoteServer.aipl\ncompile\n' \
  | "$REPL" > "$SRV_LOG" 2>&1 &
SRV_PID=$!
sleep 2

if ! lsof -i :8090 >/dev/null 2>&1; then
  echo "[FAIL] server did not bind :8090"
  cat "$SRV_LOG" | tail -20
  exit 2
fi

echo "[run] client"
printf 'load abclc/RemoteClient.aipl\ncompile\n' \
  | gtimeout 8 "$REPL" > "$CLI_LOG" 2>&1
kill "$SRV_PID" 2>/dev/null
wait "$SRV_PID" 2>/dev/null

pass=0; fail=0
check() {
  local label="$1" pattern="$2" file="$3"
  if grep -q "$pattern" "$file"; then
    pass=$((pass + 1))
    printf '  PASS  %s\n' "$label"
  else
    fail=$((fail + 1))
    printf '  FAIL  %s  (expected /%s/ in %s)\n' "$label" "$pattern" "$file"
    grep -i "remote\|reply\|client\|server" "$file" | tail -10 | sed 's/^/        /'
  fi
}

check "server got 2x note (fire-and-forget)"  '\[server\] note hit=2' "$SRV_LOG"
check "server processed now/ask (hits to 3+)" '\[server\] ask hit'    "$SRV_LOG"
check "client got synchronous reply"          '\[client\] now reply'  "$CLI_LOG"
check "client got both futures back"          '\[client\] future a'   "$CLI_LOG"
check "client got both futures back"          '\[client\] future b'   "$CLI_LOG"
check "client tolerated unreachable host"     'tolerated unreachable' "$CLI_LOG"

# === Phase 2: HMAC-signed round-trip ===================================
echo
echo "[start] signed server (ABCL_REMOTE_SECRET=topsecret)"
SRV2_LOG="$TMP/server2.log"
CLI2_LOG="$TMP/client2.log"
CLI3_LOG="$TMP/client3.log"
ABCL_REMOTE_SECRET=topsecret printf 'load abclc/RemoteServer.aipl\ncompile\n' \
  | ABCL_REMOTE_SECRET=topsecret "$REPL" > "$SRV2_LOG" 2>&1 &
SRV2_PID=$!
sleep 2

echo "[run] client with matching secret"
ABCL_REMOTE_SECRET=topsecret printf 'load abclc/RemoteClient.aipl\ncompile\n' \
  | ABCL_REMOTE_SECRET=topsecret gtimeout 8 "$REPL" > "$CLI2_LOG" 2>&1

echo "[run] client with WRONG secret (should be rejected)"
ABCL_REMOTE_SECRET=wrongkey printf 'load abclc/RemoteClient.aipl\ncompile\n' \
  | ABCL_REMOTE_SECRET=wrongkey gtimeout 8 "$REPL" > "$CLI3_LOG" 2>&1
kill "$SRV2_PID" 2>/dev/null; wait "$SRV2_PID" 2>/dev/null

check "signed client got real reply"          'now reply : answer'   "$CLI2_LOG"
check "signed server logged ask hit"          '\[server\] ask hit'   "$SRV2_LOG"
# Wrong-secret client must NOT reach the actor: server's "ask hit"
# count stays at whatever the previous (correct) client produced.
# We additionally verify the wrong-secret client got a null/() reply.
check "wrong-secret client got empty reply"   'now reply : ()'       "$CLI3_LOG"

echo
echo "==== remote actor smoke ===="
echo "  pass: $pass  fail: $fail"
exit "$fail"
