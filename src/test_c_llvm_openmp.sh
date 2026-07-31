#!/usr/bin/env bash
# Smoke test for `aipl2c --llvm` and `aipl2c --openmp`.
#
# For each sample we generate the C source, compile it with the
# corresponding toolchain, run the binary with a short timeout, and
# pass iff the captured output is non-empty.
set -u
cd "$(dirname "$0")/.."

AIPL2C=./_build/default/src/aipl2c.exe
[ -x "$AIPL2C" ] || { echo "[FATAL] $AIPL2C missing; run dune build"; exit 1; }

if ! command -v clang >/dev/null 2>&1; then
  echo "[FATAL] clang not in PATH"
  exit 1
fi
GCC=gcc-15
if ! command -v "$GCC" >/dev/null 2>&1; then
  if gcc --version 2>&1 | grep -q "Free Software Foundation"; then
    GCC=gcc
  else
    echo "[SKIP openmp] no GCC with -fopenmp on this host (Apple Clang lacks libomp)"
    GCC=""
  fi
fi

TMPROOT=$(mktemp -d /tmp/aipl-llvm-omp.XXXXXX)
trap "rm -rf '$TMPROOT'" EXIT
TIMEOUT=${TIMEOUT:-3}

SAMPLES=(Hello.aipl counter.aipl)

pass=0; fail=0; total=0
run_one() {
  local sample="$1" flag="$2" tag="$3" cc="$4" cflags="$5"
  total=$((total + 1))
  local base="${sample%.aipl}"
  local out="$TMPROOT/$tag/$base"
  mkdir -p "$TMPROOT/$tag"
  if ! "$AIPL2C" "abclc/$sample" -o "$out.c" "$flag" > "$out.gen.log" 2>&1; then
    fail=$((fail + 1)); printf '  FAIL  [%s] %s (aipl2c)\n' "$tag" "$sample"; return
  fi
  if ! $cc $cflags "$out.c" -o "$out" > "$out.cc.log" 2>&1; then
    fail=$((fail + 1)); printf '  FAIL  [%s] %s (cc)\n' "$tag" "$sample"
    head -5 "$out.cc.log" | sed 's/^/        /'
    return
  fi
  local stdout_buf
  stdout_buf=$(gtimeout "$TIMEOUT" "$out" 2>&1 | head -10)
  if [ -n "$stdout_buf" ]; then
    pass=$((pass + 1))
    printf '  PASS  [%s] %s  (head: %s)\n' "$tag" "$sample" "$(echo "$stdout_buf" | head -1)"
  else
    fail=$((fail + 1))
    printf '  FAIL  [%s] %s  (empty output)\n' "$tag" "$sample"
  fi
}

echo "[Phase 1] --llvm + clang"
for s in "${SAMPLES[@]}"; do run_one "$s" "--llvm" "llvm" "clang" "-O2 -pthread"; done

if [ -n "$GCC" ]; then
  echo "[Phase 2] --openmp + $GCC -fopenmp"
  for s in "${SAMPLES[@]}"; do run_one "$s" "--openmp" "openmp" "$GCC" "-O2 -fopenmp -pthread"; done
fi

echo
echo "==== llvm/openmp codegen smoke ===="
echo "  total: $total  pass: $pass  fail: $fail"
exit "$fail"
