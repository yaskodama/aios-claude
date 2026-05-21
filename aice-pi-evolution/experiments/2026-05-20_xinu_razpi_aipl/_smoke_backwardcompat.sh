#!/usr/bin/env bash
# R_BackwardCompat smoke — every abclc/*.abcl typechecks under the
# current typing_env / c_translator after R0..G5 + F1/F2 work.
#
# The cross-cutting "R" constraint of Round 1's design said:
#   "既存 71 sample 全 --check 通過の再走査"
#
# This script:
#   (1) runs aipl2c --check  on every abclc/*.abcl              (TYPECHECK)
#   (2) runs aipl2c --xinu   on every abclc/*.abcl              (XINU CODEGEN)
#   (3) reports counts and per-failure file so future sessions
#       can spot regressions immediately.
#
# Acceptance:
#   --check     MUST be 100% PASS (regression gate)
#   --xinu      partial coverage; 13 of the typed-feature-demo
#               samples are known to fail codegen at HEAD and that
#               predates this session — they typecheck but the
#               C backend doesn't yet target the Phase11..15 typed
#               features.  Captured here so any new failure is
#               obvious.
set -u
cd "$(dirname "$0")/../../.."
ROOT=$PWD
EXE="$ROOT/_build/default/src/aipl2c.exe"

dune build src/aipl2c.exe >/tmp/_bc_build.log 2>&1 || {
  echo "FAIL: dune build"; tail /tmp/_bc_build.log; exit 1; }

KNOWN_XINU_FAILS=(
  abclc/Arrays.abcl
  abclc/DynamicWorkerPool.abcl
  abclc/Functions.abcl
  abclc/Generics.abcl
  abclc/Phase11_TypedCounter.abcl
  abclc/Phase12_EffectsLog.abcl
  abclc/Phase13_Channels.abcl
  abclc/Phase14_Linear.abcl
  abclc/Phase15_Owned.abcl
  abclc/Records.abcl
  abclc/RemoteClient.abcl
  abclc/Tuples.abcl
  abclc/TypedDemo.abcl
)

PASS=0; FAIL=0

# (1) --check: must be 100%.
echo "=== R_BackwardCompat: aipl2c --check ==="
ck_pass=0; ck_fail=0; ck_fail_list=""
for f in abclc/*.abcl; do
  if "$EXE" "$f" --check >/dev/null 2>&1; then
    ck_pass=$((ck_pass+1))
  else
    ck_fail=$((ck_fail+1))
    ck_fail_list="$ck_fail_list $f"
  fi
done
echo "  PASS=$ck_pass FAIL=$ck_fail of $((ck_pass+ck_fail))"
if [ "$ck_fail" -eq 0 ]; then
  PASS=$((PASS+1))
  echo "  PASS: typechecker regression-clean"
else
  FAIL=$((FAIL+1))
  echo "  FAIL: typechecker regressions —$ck_fail_list"
fi

# (2) --xinu codegen: partial.  Any NEW failure beyond the known list
# is a regression.
echo
echo "=== R_BackwardCompat: aipl2c --xinu ==="
xn_pass=0; xn_fail=0; xn_new_fail=""
for f in abclc/*.abcl; do
  if "$EXE" "$f" --xinu -o /tmp/_bc_xinu.c --max-msgs 0 >/dev/null 2>&1; then
    xn_pass=$((xn_pass+1))
  else
    xn_fail=$((xn_fail+1))
    # Check if file is in known-fail list
    known=0
    for kf in "${KNOWN_XINU_FAILS[@]}"; do
      if [ "$f" = "$kf" ]; then known=1; break; fi
    done
    if [ "$known" -eq 0 ]; then
      xn_new_fail="$xn_new_fail $f"
    fi
  fi
done
echo "  PASS=$xn_pass FAIL=$xn_fail of $((xn_pass+xn_fail))"
echo "  known-fail allowlist: ${#KNOWN_XINU_FAILS[@]} samples"
if [ -z "$xn_new_fail" ]; then
  PASS=$((PASS+1))
  echo "  PASS: no NEW xinu-codegen failures (regression-clean)"
else
  FAIL=$((FAIL+1))
  echo "  FAIL: NEW xinu-codegen failures —$xn_new_fail"
fi

echo
echo "============================"
echo "R_BackwardCompat: PASS=$PASS FAIL=$FAIL  (expected PASS=2 FAIL=0)"
[ $FAIL -eq 0 ]
