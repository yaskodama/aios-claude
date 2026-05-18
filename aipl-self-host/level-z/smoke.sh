#!/usr/bin/env bash
# Level Z (full self-host) smoke runner.
#
# Verifies:
#   1. Pure-AIPL pipeline (lexer + parser + eval) runs each
#      level-z/samples/*LevelZ.abcl and emits a "[level-z] done"
#      marker plus the expected stdout.
#   2. IO bridge sample executes under the host with capability
#      checks (advisory mode) and again under AIPL_CAP_STRICT=1
#      where a missing grant must raise.
#
# usage:  bash aipl-self-host/level-z/smoke.sh

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
mkdir -p out

pass=0; fail=0

check_contains() {
  local name="$1" log="$2" expect="$3"
  if grep -qF -- "$expect" "$log"; then
    pass=$((pass+1)); printf '  PASS  %-20s | %s\n' "$name" "$expect"
  else
    fail=$((fail+1)); printf '  FAIL  %-20s | expected %q not found\n' "$name" "$expect"
    sed -n '1,5p' "$log" | sed 's/^/        /'
  fi
}

# ── Phase 1: pure-AIPL self-host pipeline ────────────────────────
echo "[Phase 1] AIPL-side lexer + parser + eval"

run_lvz() {
  local sample="$1" name
  name=$(basename "$sample" .abcl)
  local log="$HERE/out/${name}.log"
  python3 "$HERE/bootstrap.py" "$sample" > "$log" 2>&1
  echo "$log"
}

# Hello
log=$(run_lvz "$HERE/samples/HelloLevelZ.abcl")
check_contains "HelloLevelZ"  "$log" "Hello from Level Z"
check_contains "HelloLevelZ"  "$log" "[level-z] done"

# Arith
log=$(run_lvz "$HERE/samples/ArithLevelZ.abcl")
check_contains "ArithLevelZ"  "$log" "45"
check_contains "ArithLevelZ"  "$log" "[level-z] done"

# Loop
log=$(run_lvz "$HERE/samples/LoopLevelZ.abcl")
check_contains "LoopLevelZ"   "$log" "10"
check_contains "LoopLevelZ"   "$log" "[level-z] done"

# ── Phase 2: IO bridge (host-level, with capability checks) ──────
echo
echo "[Phase 2] IoBridge + capability gating"

IO_LOG="$HERE/out/IoBridge.log"
cat "$HERE/io_bridge.abcl" "$HERE/samples/SampleIoBridge.abcl" > /tmp/_lvZ_iobridge.abcl
AIPL_AI_PROVIDER=mock python3 "$HERE/../../src/python-aipl/aipl_main.py" \
    /tmp/_lvZ_iobridge.abcl > "$IO_LOG" 2>&1
check_contains "IoBridge"     "$IO_LOG" "[io] write done"
check_contains "IoBridge"     "$IO_LOG" "[io] read = hello self-host"
check_contains "IoBridge"     "$IO_LOG" "[io] ai_simple ="

STRICT_LOG="$HERE/out/IoBridgeStrict.log"
cat > /tmp/_lvZ_strict.abcl <<'EOF'
class IoBridge {
  method read(path) {
    check_capability("fs");
    var s = read_file(path);
    reply(s);
  }
}
var io = new IoBridge();
var s = now io.read("/tmp/levelz_io_demo.txt");
print("[strict] should not reach: " + s);
EOF
AIPL_CAP_STRICT=1 AIPL_AI_PROVIDER=mock python3 "$HERE/../../src/python-aipl/aipl_main.py" \
    /tmp/_lvZ_strict.abcl > "$STRICT_LOG" 2>&1
check_contains "IoBridgeStrict" "$STRICT_LOG" "capability denied"

echo
echo "==== Level Z (full self-host) smoke summary ===="
echo "  pass=$pass  fail=$fail  (logs: $HERE/out/)"
[ "$fail" -eq 0 ]
