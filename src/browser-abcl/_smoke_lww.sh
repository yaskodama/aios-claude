#!/usr/bin/env bash
# C4 LWW smoke — starts node-aipl-server and runs _smoke_lww.mjs.
# The smoke imports `ws`, so we drop it inside src/node-aipl-server
# (which has ws installed) and rewrite the lww.js import to absolute.
set -u
cd "$(dirname "$0")"
HERE="$(pwd)"
SERVER_DIR="$(cd ../node-aipl-server && pwd)"

PORT=8092
LOG=/tmp/c4_lww_smoke.log

lsof -ti tcp:$PORT 2>/dev/null | xargs -r kill 2>/dev/null || true
sleep 0.2

PORT=$PORT node "$SERVER_DIR/server.mjs" > "$LOG" 2>&1 &
SPID=$!

for _ in 1 2 3 4 5 6 7 8 9 10; do
  curl -s -o /dev/null -w '' http://localhost:$PORT/ 2>/dev/null && break
  sleep 0.2
done

TMP_SMOKE="$SERVER_DIR/_smoke_lww_tmp.mjs"
sed "s|from \"./src/lww.js\"|from \"file://${HERE}/src/lww.js\"|" \
  _smoke_lww.mjs > "$TMP_SMOKE"

PORT=$PORT node "$TMP_SMOKE"
rc=$?
rm -f "$TMP_SMOKE"

kill "$SPID" 2>/dev/null
sleep 0.2
lsof -ti tcp:$PORT 2>/dev/null | xargs -r kill -9 2>/dev/null || true
exit "$rc"
