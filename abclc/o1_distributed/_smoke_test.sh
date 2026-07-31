#!/usr/bin/env bash
# Smoke-test all .aipl samples under abclc/o1_distributed/.
#
# Phase O-1.* AIPL v2 Distributed samples are organised one
# feature-group per subdir.  Each sample exercises a runtime feature
# that is only OBSERVABLE when the appropriate AIPL_DIST_* env vars
# are set (see the header comment in each sample).  At plain `--check`
# time we verify parse + type-check.  Side-effect verification is a
# manual / CI-script-level concern, documented per-sample.
#
# Exit non-zero if any sample fails to parse / type-check.

set -u

cd "$(dirname "$0")"
REPL=../../_build/default/src/repl_thread.exe

if [ ! -x "$REPL" ]; then
  echo "[build] dune build"
  (cd ../.. && dune build) || { echo "[FATAL] dune build failed"; exit 1; }
fi

pass=0; fail=0; total=0
declare -a FAILS

for f in */sample*.aipl; do
  [ -e "$f" ] || continue
  total=$((total+1))
  if "$REPL" --check "$f" >/dev/null 2>&1; then
    pass=$((pass+1))
    printf '  OK    %s\n' "$f"
  else
    fail=$((fail+1))
    FAILS+=("$f")
    printf '  FAIL  %s\n' "$f"
    "$REPL" --check "$f" 2>&1 | tail -5 | sed 's/^/        /'
  fi
done

echo
echo "==== summary ===="
echo "total: $total  pass: $pass  fail: $fail"
if [ "$fail" -gt 0 ]; then
  echo "---- failed samples ----"
  for f in "${FAILS[@]}"; do echo "  $f"; done
  exit 1
fi
