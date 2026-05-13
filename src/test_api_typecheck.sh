#!/usr/bin/env bash
# Smoke test for the JS-server-version /api/typecheck endpoint.
#
# Starts repl_thread.exe with the web gateway listening on :8080,
# runs three test cases against /api/typecheck, then shuts down.
#
# Each case is a (description, source, expected ok=true|false) tuple.
# A case PASSes if (a) the response is JSON and (b) "ok" matches.

set -u
cd "$(dirname "$0")/.."

REPL=./_build/default/src/repl_thread.exe
PORT=8080
BOOT=src/ide_boot.bat
LOG=/tmp/typecheck_smoke.log

if [ ! -x "$REPL" ]; then
  echo "[FATAL] $REPL missing; run dune build"; exit 1
fi

# Stop any previous server and start fresh.
pkill -f repl_thread.exe >/dev/null 2>&1 || true
sleep 0.5
"$REPL" -f "$BOOT" >"$LOG" 2>&1 &
SERVER_PID=$!

# Wait until the gateway is listening.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  curl -s -o /dev/null -w '' http://localhost:$PORT/ 2>/dev/null && break
  sleep 0.3
done

pass=0; fail=0; total=0

check_case() {
  local label="$1" body="$2" want_ok="$3"
  total=$((total + 1))
  local resp
  resp=$(curl -s -X POST -H 'Content-Type: application/json' \
    -d "$body" http://localhost:$PORT/api/typecheck)
  # extract "ok":true|false (response always starts with {"ok":...})
  local got_ok=""
  case "$resp" in
    '{"ok":true'*)  got_ok=true ;;
    '{"ok":false'*) got_ok=false ;;
  esac
  if [ "$got_ok" = "$want_ok" ]; then
    pass=$((pass+1)); printf '  PASS  %s\n' "$label"
  else
    fail=$((fail+1))
    printf '  FAIL  %s\n        expected ok=%s, got %s\n' "$label" "$want_ok" "$got_ok"
    printf '        response: %s\n' "$resp"
  fi
}

check_case "valid: empty class"          '{"source":"class C { float x = 0.; method tick() { x = x + 1.; } }"}' "true"
check_case "valid: with constructor"     '{"source":"class H { float count = 0.; method init(n) { count = n; } } var h = new H(5);"}' "true"
check_case "error: parse failure"        '{"source":"not valid abcl"}'                                        "false"
check_case "error: missing method"       '{"source":"class A { float x = 0.; } var a = new A(); send a.nope(1);"}' "false"
check_case "error: missing source"       '{"source":""}'                                                      "false"

# Shut down.
kill "$SERVER_PID" 2>/dev/null
sleep 0.3
pkill -9 -f repl_thread.exe >/dev/null 2>&1 || true

echo
echo "==== /api/typecheck smoke summary ===="
echo "  total: $total  pass: $pass  fail: $fail"
exit "$fail"
