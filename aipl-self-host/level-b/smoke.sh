#!/usr/bin/env bash
# Run all Level B-1 samples and verify each emits the expected
# number of issues.  Returns 0 if every sample matches.

set -u
cd "$(dirname "$0")"

declare -a SAMPLES=(
  "SampleClean.aipl              0"
  "SampleArityViolation.aipl     2"
  "SampleTypeViolation.aipl      2"
  "SampleReturnViolation.aipl    1"
  "SampleUnion.aipl              1"
  "SampleSelfConsistency.aipl    1"
)

pass=0; fail=0
for entry in "${SAMPLES[@]}"; do
  set -- $entry
  sample="$1"
  expected_issues="$2"

  bash run.sh "samples/$sample" >/dev/null 2>&1
  log="out/${sample%.aipl}.log"
  actual=$(grep -E '^issues=' "$log" | sed 's/issues=//')
  if [ "$actual" = "$expected_issues" ]; then
    pass=$((pass+1))
    printf "  PASS  %-32s issues=%s\n" "$sample" "$actual"
  else
    fail=$((fail+1))
    printf "  FAIL  %-32s expected=%s actual=%s\n" "$sample" "$expected_issues" "$actual"
  fi
done

echo
echo "Level B-1 typeck samples: $pass pass / $fail fail"
exit "$fail"
