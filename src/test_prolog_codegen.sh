#!/usr/bin/env bash
# Smoke test for the AIPL → Prolog (SWI) codegen.
# Each sample: aipl2c --prolog -> swipl -g main -t halt
set -u
cd "$(dirname "$0")/.."

ABCL2C=./_build/default/src/aipl2c.exe
if [ ! -x "$ABCL2C" ]; then
  echo "[FATAL] $ABCL2C missing; run dune build"; exit 1
fi
if ! command -v swipl >/dev/null 2>&1; then
  echo "[FATAL] swipl missing; brew install swi-prolog"; exit 1
fi

TMPROOT=$(mktemp -d /tmp/aipl-pl-smoke.XXXXXX)
trap "rm -rf '$TMPROOT'" EXIT

GOOD=(Hello.abcl counter.abcl)
EXPECTED_FAIL=(PingPong.abcl)

pass=0; fail=0; total=0; xfail=0

check_good() {
  local f="$1"
  total=$((total + 1))
  local name="${f%.abcl}"
  local pl="$TMPROOT/$name.pl"
  if ! "$ABCL2C" "abclc/$f" -o "$pl" --prolog > /dev/null 2>&1; then
    fail=$((fail + 1)); printf '  FAIL  %s  (aipl2c)\n' "$f"; return
  fi
  # swipl prints warnings to stderr; we capture stdout for the actual output
  local out
  out=$(swipl -q -g main -t halt "$pl" 2>/dev/null | head -5)
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
  local pl="$TMPROOT/$name.pl"
  "$ABCL2C" "abclc/$f" -o "$pl" --prolog > /dev/null 2>&1
  local out
  out=$(swipl -q -g main -t halt "$pl" 2>&1 | head -10)
  if echo "$out" | grep -qiE "error|exception|undefined|warning.*main"; then
    # Either crash or noise from sender/cross-actor unsupported
    if [ -n "$out" ] && ! echo "$out" | grep -qE "got pong|got ping"; then
      xfail=$((xfail + 1))
      printf '  XFAIL  %s  (error / no proper output as expected)\n' "$f"
    else
      fail=$((fail + 1))
      printf '  UNEXPECTED PASS  %s\n' "$f"
    fi
  else
    fail=$((fail + 1))
    printf '  UNEXPECTED PASS  %s\n' "$f"
  fi
}

echo "[Phase 1] expected-good samples"
for f in "${GOOD[@]}"; do check_good "$f"; done

echo "[Phase 2] expected-fail samples (negative check)"
for f in "${EXPECTED_FAIL[@]}"; do check_xfail "$f"; done

echo
echo "==== Prolog codegen smoke summary ===="
echo "  total: $total  pass: $pass  xfail: $xfail  fail: $fail"
exit "$fail"
