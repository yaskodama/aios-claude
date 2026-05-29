#!/bin/sh
# run_browser_rpi4.sh — distributed dining philosophers (3 Mac + 2 Xinu),
# Mac side ALL in AIPL, run from the browser dashboard.
#
# Prep: translate the Pi philosophers' AIPL -> C (the Mac AIPL ships this to
# the Pi /actor/load over xinujit:// on Start, where the cc JIT compiles it).
# Then launch the Py-I dashboard.  Open the printed URL and click Start.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJ="$(cd "$HERE/../../.." && pwd)"
PORT="${1:-8899}"
cd "$PROJ"
echo "[prep] translating xinu_phil.abcl -> /tmp/xinu_phil.c (for Pi JIT) ..."
dune exec src/aipl2c.exe -- "$HERE/xinu_phil.abcl" --xinu-jit --no-typecheck -o /tmp/xinu_phil.c
echo "[run ] dashboard on http://127.0.0.1:$PORT/actors  (Pi must be at 192.168.3.100)"
exec python3 src/python-aipl/aipl_main.py --dashboard "$PORT" "$HERE/mac_diners_rpi4.abcl"
