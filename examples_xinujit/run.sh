#!/bin/sh
# AIPL -> C (--xinu-jit) -> POST to a running xinu-rpi5 Pi 4 /compile endpoint.
# Usage: ./run.sh File.abcl [host]   (host default 192.168.3.100)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJ="$(cd "$HERE/.." && pwd)"
SRC="$1"; H="${2:-192.168.3.100}"
OUT="/tmp/$(basename "${SRC%.abcl}").c"
( cd "$PROJ" && dune exec src/aipl2c.exe -- "$SRC" --xinu-jit --no-typecheck -o "$OUT" )
echo "--- generated: $OUT ---"
echo "--- POST $H/compile ---"
curl -s --max-time 15 --data-binary @"$OUT" "http://$H/compile"
