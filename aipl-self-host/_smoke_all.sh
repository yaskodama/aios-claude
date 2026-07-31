#!/usr/bin/env bash
# Master smoke runner — exercises every self-host level + reports a
# combined PASS/FAIL count.
#
# usage:  bash aipl-self-host/_smoke_all.sh

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"

total_pass=0
total_fail=0

# ── Level A: no smoke.sh, run each sample and check non-empty output
echo "[level-a] running 4 samples ..."
cd "$HERE/level-a"
mkdir -p out
a_pass=0; a_fail=0
for s in samples/*.aipl; do
  name=$(basename "$s" .aipl)
  bash run.sh "$s" >/dev/null 2>&1
  if grep -q "expected" "out/$name.log" 2>/dev/null; then
    a_pass=$((a_pass+1))
  else
    a_fail=$((a_fail+1))
  fi
done
printf "  level-a      %2d pass / %d fail\n" "$a_pass" "$a_fail"
total_pass=$((total_pass + a_pass)); total_fail=$((total_fail + a_fail))

# ── Levels with their own smoke.sh
for lvl in level-c level-c2 level-c3 level-b level-b2 level-b3 level-b4 level-b5 level-z; do
  if [ -f "$HERE/$lvl/smoke.sh" ]; then
    cd "$HERE/$lvl"
    summary=$(bash smoke.sh 2>&1 | tail -1)
    # smoke summaries vary: extract counts from "pass=N  fail=M" or
    # "N pass / M fail".
    p=$(echo "$summary" | grep -oE 'pass[= ][0-9]+|[0-9]+ pass' | grep -oE '[0-9]+' | head -1)
    f=$(echo "$summary" | grep -oE 'fail[= ][0-9]+|[0-9]+ fail' | grep -oE '[0-9]+' | head -1)
    p=${p:-0}; f=${f:-0}
    printf "  %-12s %2d pass / %d fail\n" "$lvl" "$p" "$f"
    total_pass=$((total_pass + p)); total_fail=$((total_fail + f))
  fi
done

echo
echo "==== self-host master smoke ===="
echo "total: $((total_pass + total_fail))  pass: $total_pass  fail: $total_fail"
[ "$total_fail" -eq 0 ]
