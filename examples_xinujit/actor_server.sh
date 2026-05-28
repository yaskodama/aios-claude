#!/bin/sh
# Load an AIPL program as RESIDENT actors on a running xinu-rpi5, then
# exchange messages with them over HTTP.
# Usage: ./actor_server.sh File.abcl [host]   (host default 192.168.3.100)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJ="$(cd "$HERE/.." && pwd)"
SRC="$1"; H="${2:-192.168.3.100}"
OUT="/tmp/$(basename "${SRC%.abcl}").c"
( cd "$PROJ" && dune exec src/aipl2c.exe -- "$SRC" --xinu-jit --no-typecheck -o "$OUT" )
echo "== POST /actor/load =="
curl -s --data-binary @"$OUT" "http://$H/actor/load"; echo
echo "== GET /actor/send (state persists across calls) =="
curl -s "http://$H/actor/send?to=0&m=bump&arg=10"; echo
curl -s "http://$H/actor/send?to=0&m=get";          echo
curl -s "http://$H/actor/send?to=0&m=bump&arg=100"; echo
curl -s "http://$H/actor/send?to=0&m=get";          echo
