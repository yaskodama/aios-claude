#!/usr/bin/env bash
# Py-I next-gen 24 samples (8 features × 3) smoke runner.
#
# usage:
#   bash src/python-aipl/samples/nextgen/_smoke_nextgen.sh

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PYAIPL="$(cd "$HERE/../.." && pwd)"          # src/python-aipl
LOGDIR="$HERE/_logs"
rm -rf "$LOGDIR" && mkdir -p "$LOGDIR"

cd "$PYAIPL"

export AIPL_AI_PROVIDER="${AIPL_AI_PROVIDER:-mock}"
export AIPL_DIST_ENABLE="${AIPL_DIST_ENABLE:-1}"
export AIPL_DIST_LOG_FILE="${AIPL_DIST_LOG_FILE:-$LOGDIR/aipl_dist.ndjson}"
: > "$AIPL_DIST_LOG_FILE"

# Per-sample env (case is bash-3.2 friendly).
env_for() {
  case "$1" in
    ce11_capability/sample2_strict_raise.abcl) echo "AIPL_CAP_STRICT=1" ;;
    ce12_refinement/sample1_satisfiable.abcl)  echo "AIPL_REFINE_UNIFY=1" ;;
    ce12_refinement/sample2_window_unsat.abcl) echo "AIPL_REFINE_CHECK=1" ;;
    ce12_refinement/sample3_subset_implied.abcl) echo "AIPL_REFINE_UNIFY=1" ;;
    dr12_region/sample1_primary_hit.abcl)
      echo "AIPL_REGION=us-east-1 AIPL_REGION_FAILOVER=us-east-1,eu-west-1 AIPL_ROUTE_REGION_us-east-1=Greeter:fast" ;;
    dr12_region/sample2_failover_chain.abcl)
      echo "AIPL_REGION=us-east-1 AIPL_REGION_FAILOVER=us-east-1,eu-west-1,ap-northeast-1 AIPL_ROUTE_REGION_eu-west-1=Greeter:slow" ;;
    dr12_region/sample3_chain_exhausted.abcl)
      echo "AIPL_REGION=us-east-1 AIPL_REGION_FAILOVER=us-east-1,eu-west-1" ;;
    *) echo "" ;;
  esac
}

# Samples whose `--check` is expected to flag a type error.
# (Plain `run` is still allowed since Py-I's runtime is permissive.)
expect_check_type_error() {
  case "$1" in
    ce13_record_subtyping/sample2_disjoint_rejected.abcl) return 0 ;;
    *) return 1 ;;
  esac
}

pass=0; fail=0; total=0
for rel in $(cd "$HERE" && find ce* dr* -name "sample*.abcl" | sort); do
  total=$((total+1))
  abs="$HERE/$rel"
  envvars="$(env_for "$rel")"
  log="$LOGDIR/$(echo "$rel" | tr / _).log"
  if [ -n "$envvars" ]; then
    eval "env $envvars timeout 20 python3 aipl_main.py '$abs'" >"$log" 2>&1
  else
    timeout 20 python3 aipl_main.py "$abs" >"$log" 2>&1
  fi
  rc=$?

  if [ "$rc" -ne 0 ]; then
    fail=$((fail+1)); printf '  FAIL  %s  (rc=%d)\n' "$rel" "$rc"
    sed -n '1,5p' "$log" | sed 's/^/        /'
    continue
  fi

  # If this sample is also expected to surface a type error under
  # `--check`, run the static checker as a secondary assertion.
  if expect_check_type_error "$rel"; then
    check_log="$LOGDIR/$(echo "$rel" | tr / _).check.log"
    if [ -n "$envvars" ]; then
      eval "env $envvars timeout 10 python3 aipl_main.py --check '$abs'" >"$check_log" 2>&1 || true
    else
      timeout 10 python3 aipl_main.py --check "$abs" >"$check_log" 2>&1 || true
    fi
    if grep -qE '\[unify\]|\[field\]|type error|UnifyError|TypeError|disjoint|record fields|no rule to unify' "$check_log"; then
      pass=$((pass+1)); printf '  PASS  %s  (+ --check flags type error)\n' "$rel"
    else
      fail=$((fail+1)); printf '  FAIL  %s  (--check did not flag type error)\n' "$rel"
      sed -n '1,5p' "$check_log" | sed 's/^/        /'
    fi
    continue
  fi

  pass=$((pass+1)); printf '  PASS  %s\n' "$rel"
done

echo
echo "==== Py-I next-gen smoke summary ===="
echo "total: $total  pass: $pass  fail: $fail  (logs: $LOGDIR/)"
[ "$fail" -eq 0 ]
