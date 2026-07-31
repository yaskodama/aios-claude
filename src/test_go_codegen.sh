#!/usr/bin/env bash
# Smoke test for the AIPL → Go codegen.
#
# For each sample: aipl2c --go -> go run -> capture output.
set -u
cd "$(dirname "$0")/.."

ABCL2C=./_build/default/src/aipl2c.exe
if [ ! -x "$ABCL2C" ]; then
  echo "[FATAL] $ABCL2C missing; run dune build"; exit 1
fi
if ! command -v go >/dev/null 2>&1; then
  echo "[FATAL] go missing; brew install go"; exit 1
fi

TMPROOT=$(mktemp -d /tmp/aipl-go-smoke.XXXXXX)
trap "rm -rf '$TMPROOT'" EXIT

GOOD=(
  Hello.aipl
  counter.aipl
)
EXPECTED_FAIL=(
  PingPong.aipl
)

pass=0; fail=0; total=0; xfail=0

check_good() {
  local f="$1"
  total=$((total + 1))
  local name="${f%.aipl}"
  local dir="$TMPROOT/$name"
  mkdir -p "$dir"
  if ! "$ABCL2C" "abclc/$f" -o "$dir/main.go" --go > /dev/null 2>&1; then
    fail=$((fail + 1)); printf '  FAIL  %s  (aipl2c)\n' "$f"; return
  fi
  local out
  out=$(cd "$dir" && go run main.go 2>&1 | head -5)
  local rc=$?
  if [ -n "$out" ] && [ $rc -eq 0 ]; then
    pass=$((pass + 1)); printf '  PASS  %s  (output: %s)\n' "$f" "$(echo "$out" | head -1)"
  else
    fail=$((fail + 1)); printf '  FAIL  %s  (rc=%d)\n' "$f" "$rc"
    echo "$out" | head -3 | sed 's/^/        /'
  fi
}

check_xfail() {
  local f="$1"
  total=$((total + 1))
  local name="${f%.aipl}"
  local dir="$TMPROOT/$name"
  mkdir -p "$dir"
  "$ABCL2C" "abclc/$f" -o "$dir/main.go" --go > /dev/null 2>&1
  local out
  out=$(cd "$dir" && go run main.go 2>&1)
  local rc=$?
  if [ $rc -ne 0 ] || echo "$out" | grep -q "panic\|undefined"; then
    xfail=$((xfail + 1))
    printf '  XFAIL  %s  (compile/runtime error as expected)\n' "$f"
  else
    fail=$((fail + 1))
    printf '  UNEXPECTED PASS  %s  (was expected to fail)\n' "$f"
  fi
}

echo "[Phase 1] expected-good samples"
for f in "${GOOD[@]}"; do check_good "$f"; done

echo "[Phase 2] expected-fail samples (negative check)"
for f in "${EXPECTED_FAIL[@]}"; do check_xfail "$f"; done

echo
echo "==== Go codegen smoke summary ===="
echo "  total: $total  pass: $pass  xfail: $xfail  fail: $fail"
exit "$fail"
