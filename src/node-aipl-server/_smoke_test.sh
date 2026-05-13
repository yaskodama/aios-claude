#!/usr/bin/env bash
# Smoke test for node-aipl-server.
#
# Starts server.mjs on a free port, hits /api/typecheck against the
# browser-abcl samples, and checks for ok:true|false matches.
set -u
cd "$(dirname "$0")"

PORT=8091
LOG=/tmp/node_aipl_smoke.log
PIDFILE=/tmp/node_aipl_smoke.pid

# Stop anything already on this port.
lsof -ti tcp:$PORT 2>/dev/null | xargs -r kill 2>/dev/null || true
sleep 0.3

PORT=$PORT node ./server.mjs > "$LOG" 2>&1 &
SPID=$!
echo $SPID > "$PIDFILE"

# Wait until the listener is up.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  curl -s -o /dev/null -w '' http://localhost:$PORT/ 2>/dev/null && break
  sleep 0.3
done

pass=0; fail=0; total=0

# Synthetic API tests
api_case() {
  local label="$1" body="$2" want_ok="$3"
  total=$((total + 1))
  local resp
  resp=$(curl -s -X POST -H 'Content-Type: application/json' \
    -d "$body" http://localhost:$PORT/api/typecheck)
  local got=""
  case "$resp" in
    '{"ok":true'*)  got=true ;;
    '{"ok":false'*) got=false ;;
  esac
  if [ "$got" = "$want_ok" ]; then
    pass=$((pass + 1)); printf '  PASS  %s\n' "$label"
  else
    fail=$((fail + 1))
    printf '  FAIL  %s\n        expected ok=%s, got %s\n' "$label" "$want_ok" "$got"
    printf '        response: %s\n' "$resp"
  fi
}

echo "[Phase 1] /api/typecheck JSON cases"
api_case "valid: empty class"         '{"source":"class C { var x = 0; method tick() { x = x + 1; } }"}'  "true"
api_case "valid: constructor"         '{"source":"class H { var n = 0; method init(x) { n = x; } } var h = new H(5);"}' "true"
api_case "error: parse failure"       '{"source":"not valid abcl"}'                                       "false"
api_case "error: missing source"      '{"source":""}'                                                     "false"

# Sample-file tests — reuse browser-abcl's known-good samples
SAMPLES=(bounded_buffer.abcl philosophers.abcl rotate4lines.abcl drone_simulator.abcl)
echo "[Phase 2] /api/typecheck on browser-abcl samples"
for s in "${SAMPLES[@]}"; do
  total=$((total + 1))
  body_file=$(mktemp /tmp/aipl_smoke_body.XXXXXX)
  # Build JSON body via Node so we don't fight bash escaping
  node -e '
    const fs = require("node:fs");
    const src = fs.readFileSync(process.argv[1], "utf8");
    process.stdout.write(JSON.stringify({source:src}));
  ' "../browser-abcl/$s" > "$body_file"
  resp=$(curl -s -X POST -H 'Content-Type: application/json' \
    --data-binary @"$body_file" \
    http://localhost:$PORT/api/typecheck)
  rm -f "$body_file"
  case "$resp" in
    '{"ok":true'*)
      pass=$((pass + 1)); printf '  PASS  %s\n' "$s" ;;
    *)
      fail=$((fail + 1))
      printf '  FAIL  %s\n        %s\n' "$s" "${resp:0:200}" ;;
  esac
done

# Shut down server
kill "$SPID" 2>/dev/null
sleep 0.2
lsof -ti tcp:$PORT 2>/dev/null | xargs -r kill -9 2>/dev/null || true
rm -f "$PIDFILE"

echo
echo "==== node-aipl-server smoke summary ===="
echo "  total: $total  pass: $pass  fail: $fail"
exit "$fail"
