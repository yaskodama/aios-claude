#!/usr/bin/env bash
# Smoke test for python-aipl-inferred — the HM-inferred sibling of python-aipl.
#
# Runs each sample under `../python-aipl/samples/` through aipl_main.py
# with the HM type-checker active (default).  PASS means the program
# parsed, type-checked, and executed without uncaught exceptions.
#
# Usage:
#   bash src/python-aipl-inferred/_smoke_test.sh
#   PYTHON=/opt/homebrew/bin/python3.13 bash ...
#
set -u
cd "$(dirname "$0")"

PY=${PYTHON:-/usr/bin/python3}
SAMPLES_DIR=../python-aipl/samples

# A representative subset of samples — exercises all language features.
samples=(
  Hello.abcl
  Counter.abcl
  PingPong.abcl
  Tuples.abcl
  Records.abcl
  Arrays.abcl
  MultiDimArrays.abcl
  Functions.abcl
  Effects.abcl
  Channels.abcl
  Linear.abcl
  Owned.abcl
  Transient.abcl
  Dynamic.abcl
  MethodPatch.abcl
  Signatures.abcl
  Phase17_StructuredConc.abcl
  NowFuture.abcl
  Philosophers.abcl
  BoundedBuffer.abcl
)

pass=0; fail=0; total=0
FAILS=()

for s in "${samples[@]}"; do
  total=$((total + 1))
  if [ ! -f "$SAMPLES_DIR/$s" ]; then
    fail=$((fail + 1)); FAILS+=("$s (missing)")
    printf '  FAIL  %s  (missing)\n' "$s"
    continue
  fi
  out=$($PY aipl_main.py "$SAMPLES_DIR/$s" --timeout 1.5 2>&1)
  rc=$?
  if [ "$rc" = "0" ]; then
    pass=$((pass + 1)); printf '  PASS  %s\n' "$s"
  else
    fail=$((fail + 1)); FAILS+=("$s")
    printf '  FAIL  %s  (rc=%d)\n' "$s" "$rc"
    echo "$out" | head -2 | sed 's/^/        /'
  fi
done

echo
echo "==== python-aipl-inferred smoke summary ===="
echo "  total: $total  pass: $pass  fail: $fail"
exit "$fail"
