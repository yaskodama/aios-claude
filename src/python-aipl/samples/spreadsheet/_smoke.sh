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

# ── Phase 3: PersistedSheet (P3 DistCheckpoint) ──────────────
echo
echo "[Phase 3] PersistedSheet (save / load round-trip)"
PS_LOG="$LOGDIR/PersistedSheet.log"
timeout 25 python3 aipl_main.py samples/spreadsheet/PersistedSheet.abcl > "$PS_LOG" 2>&1

check_contains "PersistedSheet" "$PS_LOG" "=== original ==="
check_contains "PersistedSheet" "$PS_LOG" "[save] /tmp/_persisted_sheet.txt"
check_contains "PersistedSheet" "$PS_LOG" "=== reloaded ==="
check_contains "PersistedSheet" "$PS_LOG" "[load] /tmp/_persisted_sheet.txt"
# Same computed values appear twice (original + reloaded) — verify both runs
orig_count=$(grep -c "C3 = 1330" "$PS_LOG")
if [ "$orig_count" -eq 2 ]; then
  pass=$((pass+1)); printf '  PASS  %-16s | round-trip C3 = 1330 (orig+reload)\n' "PersistedSheet"
else
  fail=$((fail+1)); printf '  FAIL  %-16s | expected 2 occurrences of C3=1330, got %d\n' "PersistedSheet" "$orig_count"
fi

# ── Phase 5.0: GSheetsCore12 (F2 Core12 functions) ───────────
echo
echo "[Phase 5.0] GSheetsCore12 (SUM/AVG/MIN/MAX/COUNT/IF/POWER/MOD/...)"
GS_LOG="$LOGDIR/GSheetsCore12.log"
timeout 25 python3 aipl_main.py samples/spreadsheet/GSheetsCore12.abcl > "$GS_LOG" 2>&1

check_contains "GSheetsCore12" "$GS_LOG" "B1 = 150"      # SUM(A1..A5)
check_contains "GSheetsCore12" "$GS_LOG" "B2 = 30"       # AVG(A1..A5)
check_contains "GSheetsCore12" "$GS_LOG" "B3 = 10"       # MIN
check_contains "GSheetsCore12" "$GS_LOG" "B4 = 50"       # MAX
check_contains "GSheetsCore12" "$GS_LOG" "B5 = 5"        # COUNT (non-zero)
check_contains "GSheetsCore12" "$GS_LOG" "B6 = 5"        # COUNTA
check_contains "GSheetsCore12" "$GS_LOG" "C1 = 42"       # IF(1, 42, 99)
check_contains "GSheetsCore12" "$GS_LOG" "C2 = 99"       # IF(0, 42, 99)
check_contains "GSheetsCore12" "$GS_LOG" "C3 = 7"        # ABS(0-7)
check_contains "GSheetsCore12" "$GS_LOG" "C4 = 1024"     # POWER(2, 10)
check_contains "GSheetsCore12" "$GS_LOG" "C5 = 2"        # MOD(17, 5)
check_contains "GSheetsCore12" "$GS_LOG" "D1 = 100"      # AVG(B1=150, B4=50)

echo
echo "==== WebSpreadsheet smoke summary ===="
echo "  pass=$pass  fail=$fail  (logs: $LOGDIR/)"
[ "$fail" -eq 0 ]
