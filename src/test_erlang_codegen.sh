#!/usr/bin/env bash
# Smoke test for the AIPL → Erlang codegen.
#
# For each sample: aipl2c --erlang -> erlc -> erl -s aipl_out main.
# Captures the output and PASSes if non-empty.
set -u
cd "$(dirname "$0")/.."

ABCL2C=./_build/default/src/aipl2c.exe
if [ ! -x "$ABCL2C" ]; then
  echo "[FATAL] $ABCL2C missing; run dune build"; exit 1
fi
if ! command -v erlc >/dev/null 2>&1; then
  echo "[FATAL] erlc missing; brew install erlang"; exit 1
fi

TMPROOT=$(mktemp -d /tmp/aipl-erl-smoke.XXXXXX)
trap "rm -rf '$TMPROOT'" EXIT

# Samples expected to round-trip
GOOD=(
  Hello.abcl
  counter.abcl
)

# Samples expected to fail (sender / cross-actor globals from init bodies)
EXPECTED_FAIL=(
  PingPong.abcl
)

pass=0; fail=0; total=0; xfail=0

check_good() {
  local f="$1"
  total=$((total + 1))
  local name="${f%.abcl}"
  local dir="$TMPROOT/$name"
  mkdir -p "$dir"
  if ! "$ABCL2C" "abclc/$f" -o "$dir/aipl_out.erl" --erlang > /dev/null 2>&1; then
    fail=$((fail + 1)); printf '  FAIL  %s  (aipl2c)\n' "$f"; return
  fi
  if ! (cd "$dir" && erlc aipl_out.erl > erlc.log 2>&1); then
    fail=$((fail + 1)); printf '  FAIL  %s  (erlc)\n' "$f"
    head -5 "$dir/erlc.log" | sed 's/^/        /'
    return
  fi
  local out
  out=$(erl -noshell -pa "$dir" -s aipl_out main -s init stop 2>&1 | head -5)
  if [ -n "$out" ]; then
    pass=$((pass + 1)); printf '  PASS  %s  (output: %s)\n' "$f" "$(echo "$out" | head -1)"
  else
    fail=$((fail + 1)); printf '  FAIL  %s  (empty output)\n' "$f"
  fi
}

check_xfail() {
  local f="$1"
  total=$((total + 1))
  local name="${f%.abcl}"
  local dir="$TMPROOT/$name"
  mkdir -p "$dir"
  "$ABCL2C" "abclc/$f" -o "$dir/aipl_out.erl" --erlang > /dev/null 2>&1
  if (cd "$dir" && erlc aipl_out.erl > erlc.log 2>&1); then
    # Even if it compiles, runtime may fail due to send-to-atom etc.
    local out
    out=$(erl -noshell -pa "$dir" -s aipl_out main -s init stop 2>&1)
    if echo "$out" | grep -q "error\|crash\|badarg\|undefined"; then
      xfail=$((xfail + 1))
      printf '  XFAIL  %s  (runtime error as expected)\n' "$f"
    else
      fail=$((fail + 1))
      printf '  UNEXPECTED PASS  %s  (was expected to fail)\n' "$f"
    fi
  else
    xfail=$((xfail + 1))
    printf '  XFAIL  %s  (erlc rejected as expected)\n' "$f"
  fi
}

echo "[Phase 1] expected-good samples"
for f in "${GOOD[@]}"; do check_good "$f"; done

echo "[Phase 2] expected-fail samples (negative check)"
for f in "${EXPECTED_FAIL[@]}"; do check_xfail "$f"; done

echo
echo "==== Erlang codegen smoke summary ===="
echo "  total: $total  pass: $pass  xfail: $xfail  fail: $fail"
exit "$fail"
