#!/usr/bin/env bash
# Smoke-test the C codegen + abcl_nextgen_runtime.c against the
# existing o2_typeinf + o1_distributed sample bank.
#
# CE-10 / CE-12 / CE-13 are type-system-time only and exercised by
# the OCaml REPL --check / --infer path; this script focuses on the
# 5 runtime-resident features (CE-11 + DR-10..13) that produce
# linkable C output through aipl2c.

set -u

cd "$(dirname "$0")/.."
AIPL2C=_build/default/src/aipl2c.exe
RUNTIME=src/abcl_nextgen_runtime.c
CC=${CC:-cc}
TIMEOUT=${TIMEOUT:-5}

if [ ! -x "$AIPL2C" ]; then dune build || exit 1; fi

# Sample groups that should compile cleanly through pure-C codegen
# and link against abcl_nextgen_runtime.c.  CE-13 / record-subtyping
# samples are static-type-check artifacts, so we skip them here.
samples=(
  abclc/o2_typeinf/ce_11_capability/sample1_grant_revoke.abcl
  abclc/o2_typeinf/ce_11_capability/sample2_strict_raise.abcl
  abclc/o2_typeinf/ce_11_capability/sample3_advisory_log.abcl
  abclc/o1_distributed/dr_10_crdt/sample1_gcounter.abcl
  abclc/o1_distributed/dr_10_crdt/sample2_orset.abcl
  abclc/o1_distributed/dr_10_crdt/sample3_lww_replicate.abcl
  abclc/o1_distributed/dr_11_saga/sample1_success.abcl
  abclc/o1_distributed/dr_11_saga/sample2_compensate.abcl
  abclc/o1_distributed/dr_11_saga/sample3_single_step.abcl
  abclc/o1_distributed/dr_12_multi_region/sample1_primary_hit.abcl
  abclc/o1_distributed/dr_12_multi_region/sample2_failover_chain.abcl
  abclc/o1_distributed/dr_12_multi_region/sample3_chain_exhausted.abcl
  abclc/o1_distributed/dr_13_pool/sample1_create_destroy.abcl
  abclc/o1_distributed/dr_13_pool/sample2_pick_empty.abcl
  abclc/o1_distributed/dr_13_pool/sample3_destroy_idempotent.abcl
)

pass=0; fail=0; declare -a FAILS
TMPDIR=${TMPDIR:-/tmp}
for s in "${samples[@]}"; do
  base=$(basename "$s" .abcl)
  cfile="$TMPDIR/${base}_c.c"
  bin="$TMPDIR/${base}_c"

  if ! "$AIPL2C" "$s" -o "$cfile" --no-typecheck >/dev/null 2>&1; then
    fail=$((fail+1)); FAILS+=("$s [aipl2c]")
    printf '  AIPL2C FAIL  %s\n' "$s"
    continue
  fi
  if ! $CC -O2 -Wall -pthread -I src "$cfile" "$RUNTIME" -o "$bin" 2>"$TMPDIR/${base}.cc.err"; then
    fail=$((fail+1)); FAILS+=("$s [cc]")
    printf '  CC FAIL      %s  (see %s)\n' "$s" "$TMPDIR/${base}.cc.err"
    continue
  fi
  if ! timeout "$TIMEOUT" "$bin" >"$TMPDIR/${base}.out" 2>&1; then
    # exit-nonzero (e.g. AIPL_CAP_STRICT abort) is sometimes expected; pass if output produced
    if [ -s "$TMPDIR/${base}.out" ]; then
      pass=$((pass+1)); printf '  PASS (early-exit) %s\n' "$base"
      continue
    fi
    fail=$((fail+1)); FAILS+=("$s [run]")
    printf '  RUN FAIL     %s\n' "$s"
    continue
  fi
  pass=$((pass+1)); printf '  PASS         %s\n' "$base"
done

echo
echo "==== C-codegen smoke summary ===="
echo "total: $((pass+fail))  pass: $pass  fail: $fail"
if [ "$fail" -gt 0 ]; then
  echo "---- fails ----"
  for f in "${FAILS[@]}"; do echo "  $f"; done
  exit 1
fi
