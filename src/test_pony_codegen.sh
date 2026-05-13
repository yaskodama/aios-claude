#!/usr/bin/env bash
# Smoke test for the AIPL → Pony codegen.
#
# For each sample, runs:
#   1. abcl2c --pony <sample> → <name>.pony
#   2. ponyc on a tmp directory containing the .pony file (renamed main.pony)
#   3. executes the resulting binary
# Records PASS / FAIL per phase.  Some samples are expected to FAIL the
# compile phase because they use AIPL features Pony's strict actor model
# does not support (e.g. cross-actor globals referenced from init bodies,
# or sender-driven sends).
set -u
cd "$(dirname "$0")/.."

ABCL2C=./_build/default/src/abcl2c.exe
if [ ! -x "$ABCL2C" ]; then
  echo "[FATAL] $ABCL2C missing; run dune build"; exit 1
fi
if ! command -v ponyc >/dev/null 2>&1; then
  echo "[FATAL] ponyc missing; brew install ponyc"; exit 1
fi

TMPROOT=$(mktemp -d /tmp/aipl-pony-smoke.XXXXXX)
trap "rm -rf '$TMPROOT'" EXIT

# Samples expected to round-trip cleanly (no cross-actor globals
# in init, no `sender`-driven sends).
GOOD=(
  Hello.abcl
  counter.abcl
)

# Samples expected to fail (used as a negative check — sender / cross-ref).
# The codegen still emits Pony source but ponyc rejects it.
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
  if ! "$ABCL2C" "abclc/$f" -o "$dir/main.pony" --pony > /dev/null 2>&1; then
    fail=$((fail + 1)); printf '  FAIL  %s  (abcl2c)\n' "$f"; return
  fi
  if ! (cd "$dir" && ponyc --output . > ponyc.log 2>&1); then
    fail=$((fail + 1)); printf '  FAIL  %s  (ponyc)\n' "$f"
    tail -5 "$dir/ponyc.log" | sed 's/^/        /'
    return
  fi
  local bin
  bin=$(ls "$dir"/*-"$name" 2>/dev/null | head -1)
  [ -z "$bin" ] && bin=$(ls "$dir" | grep -v '\.' | head -1 | xargs -I{} echo "$dir/{}")
  if [ ! -x "$bin" ]; then
    fail=$((fail + 1)); printf '  FAIL  %s  (no binary)\n' "$f"; return
  fi
  local out
  out=$("$bin" 2>&1 | head -5)
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
  "$ABCL2C" "abclc/$f" -o "$dir/main.pony" --pony > /dev/null 2>&1
  # Expect ponyc to fail.
  if (cd "$dir" && ponyc --output . > ponyc.log 2>&1); then
    fail=$((fail + 1))
    printf '  UNEXPECTED PASS  %s  (was expected to fail)\n' "$f"
  else
    xfail=$((xfail + 1))
    printf '  XFAIL  %s  (expected — uses sender / cross-actor globals)\n' "$f"
  fi
}

echo "[Phase 1] expected-good samples"
for f in "${GOOD[@]}"; do check_good "$f"; done

echo "[Phase 2] expected-fail samples (negative check)"
for f in "${EXPECTED_FAIL[@]}"; do check_xfail "$f"; done

echo
echo "==== Pony codegen smoke summary ===="
echo "  total: $total  pass: $pass  xfail: $xfail  fail: $fail"
exit "$fail"
