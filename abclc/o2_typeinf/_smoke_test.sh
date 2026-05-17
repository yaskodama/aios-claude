#!/usr/bin/env bash
# Smoke-test all .abcl samples under abclc/o2_typeinf/.
#
# Phase O-2.* type-inference samples are organised one feature-group
# per subdir (ce_where, ce_int_refine, ce_real_refine, ce_record,
# ce_cross_class).  Each sample is validated via `repl_thread.exe
# --check` which runs the nominal type-check + HM inference + (if
# AIPL_REFINE_CHECK=1) Z3 refinement discharge.
#
# Exit non-zero if any sample fails.

set -u

cd "$(dirname "$0")"
REPL=../../_build/default/src/repl_thread.exe

if [ ! -x "$REPL" ]; then
  echo "[build] dune build"
  (cd ../.. && dune build) || { echo "[FATAL] dune build failed"; exit 1; }
fi

pass=0; fail=0; total=0
declare -a FAILS

for f in */sample*.abcl; do
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
