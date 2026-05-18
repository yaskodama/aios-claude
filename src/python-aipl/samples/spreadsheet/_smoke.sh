#!/usr/bin/env bash
# WebSpreadsheet round 3 smoke runner.
#
# Currently exercises:
#   - HelloSheet.abcl  : 3x3 sheet with AST-formula eval (no parser yet)
#
# Each subsequent commit in the round-3 implementation phase adds
# one more sample (formula parser, cell actors, persistence, …).
#
# usage:
#   bash src/python-aipl/samples/spreadsheet/_smoke.sh

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PYAIPL="$(cd "$HERE/../.." && pwd)"          # src/python-aipl
LOGDIR="$HERE/_logs"
rm -rf "$LOGDIR" && mkdir -p "$LOGDIR"

cd "$PYAIPL"
export AIPL_AI_PROVIDER="${AIPL_AI_PROVIDER:-mock}"
export AIPL_DIST_ENABLE="${AIPL_DIST_ENABLE:-1}"

pass=0; fail=0

check_contains() {
  local name="$1" log="$2" expect="$3"
  if grep -qF -- "$expect" "$log"; then
    pass=$((pass+1)); printf '  PASS  %-16s | %s\n' "$name" "$expect"
  else
    fail=$((fail+1)); printf '  FAIL  %-16s | expected %q not found\n' "$name" "$expect"
    sed -n '1,5p' "$log" | sed 's/^/        /'
  fi
}

# ── Phase 0: HelloSheet ──────────────────────────────────────
echo "[Phase 0] HelloSheet (AST-formula eval)"
HELLO_LOG="$LOGDIR/HelloSheet.log"
timeout 20 python3 aipl_main.py samples/spreadsheet/HelloSheet.abcl > "$HELLO_LOG" 2>&1

check_contains "HelloSheet"  "$HELLO_LOG" "A1 = 10"
check_contains "HelloSheet"  "$HELLO_LOG" "C1 = 30"        # A1 + B1
check_contains "HelloSheet"  "$HELLO_LOG" "C2 = 1200"      # A2 * B2
check_contains "HelloSheet"  "$HELLO_LOG" "A3 = 20"        # A1 * 2
check_contains "HelloSheet"  "$HELLO_LOG" "C3 = 1330"      # SUM(...)

# ── Phase 1: StringFormulaSheet (PA4 parser) ─────────────────
echo
echo "[Phase 1] StringFormulaSheet (lex + parse + eval)"
SFS_LOG="$LOGDIR/StringFormulaSheet.log"
timeout 20 python3 aipl_main.py samples/spreadsheet/StringFormulaSheet.abcl > "$SFS_LOG" 2>&1

check_contains "StringFormula" "$SFS_LOG" "A1 = 10"
check_contains "StringFormula" "$SFS_LOG" "C1 = 30"        # parsed "A1+B1"
check_contains "StringFormula" "$SFS_LOG" "C2 = 1200"      # parsed "A2*B2"
check_contains "StringFormula" "$SFS_LOG" "C3 = 1330"      # parsed "SUM(...)"

# ── Phase 2: ActorSheet (CA4 + FE4) ──────────────────────────
echo
echo "[Phase 2] ActorSheet (cell actors + actor eval)"
AS_LOG="$LOGDIR/ActorSheet.log"
timeout 25 python3 aipl_main.py samples/spreadsheet/ActorSheet.abcl > "$AS_LOG" 2>&1

check_contains "ActorSheet"    "$AS_LOG" "A1 = 10"
check_contains "ActorSheet"    "$AS_LOG" "C1 = 30"          # cell-to-cell now
check_contains "ActorSheet"    "$AS_LOG" "C2 = 1200"
check_contains "ActorSheet"    "$AS_LOG" "C3 = 1330"
check_contains "ActorSheet"    "$AS_LOG" "=== done ==="

echo
echo "==== WebSpreadsheet smoke summary ===="
echo "  pass=$pass  fail=$fail  (logs: $LOGDIR/)"
[ "$fail" -eq 0 ]
