#!/usr/bin/env bash
# Phase 4 spreadsheet UI smoke runner (node-side).
#
# The actual HTML page (spreadsheet.html) needs a browser to render
# the canvas.  This script runs spreadsheet.abcl through the shared
# JS runtime in Node and verifies the runtime's sheetState is
# populated correctly (9 cells + selection on C3).
#
# usage:  bash src/browser-abcl/_smoke_spreadsheet.sh

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
LOGDIR="$HERE/_spreadsheet_logs"
rm -rf "$LOGDIR" && mkdir -p "$LOGDIR"
LOG="$LOGDIR/spreadsheet.log"

RUNNER="$LOGDIR/_runner.mjs"
cat > "$RUNNER" <<EOF
import { createRequire } from "node:module";
import * as fs from "node:fs";
const require = createRequire(import.meta.url);
const SRC = "$ROOT/src/browser-abcl/src";
const ast = await import(SRC + "/ast.js");
const tc  = await import(SRC + "/typecheck.js");
const rt  = await import(SRC + "/runtime.js");
const parser = require(SRC + "/parser/parser.js").parser;
parser.yy = ast;
const src = fs.readFileSync("$HERE/spreadsheet.abcl", "utf8");
const tree = parser.parse(src);
tc.runTypeCheck(tree);
const runtime = new rt.Runtime(()=>{});
runtime.injectFs(fs);
runtime.reset();
for (const cls of tree.classes) runtime.registerClass(cls);
const env = {};
for (const st of tree.statements) runtime.evalStmt(st, env);
runtime.scheduleAllActors();
await new Promise(r=>setTimeout(r, 800));
const s = runtime.sheetState;
if (!s) { console.error("FAIL: sheetState is null"); process.exit(1); }
console.log("rows=" + s.rows);
console.log("cols=" + s.cols);
console.log("cells=" + s.cells.length);
console.log("sel_row=" + s.sel.row);
console.log("sel_col=" + s.sel.col);
// dump some computed cell values
for (const c of s.cells) {
  console.log("cell[" + c.row + "][" + c.col + "]=" + c.val + ":" + c.kind);
}
EOF
node "$RUNNER" > "$LOG" 2>&1
rc=$?

pass=0; fail=0
check_contains() {
  local name="$1" expect="$2"
  if grep -qF -- "$expect" "$LOG"; then
    pass=$((pass+1)); printf '  PASS  %-22s | %s\n' "$name" "$expect"
  else
    fail=$((fail+1)); printf '  FAIL  %-22s | expected %s\n' "$name" "$expect"
    head -8 "$LOG" | sed 's/^/        /'
  fi
}

echo "[Phase 4] spreadsheet.abcl renders sheetState"
check_contains "rows"          "rows=3"
check_contains "cols"          "cols=3"
check_contains "9 cells"       "cells=9"
check_contains "selection"     "sel_row=2"
check_contains "selection"     "sel_col=2"
check_contains "C3 = SUM 1330" "cell[2][2]=1330:Formula"
check_contains "A1 literal"    "cell[0][0]=10:Value"
check_contains "C1 formula"    "cell[0][2]=30:Formula"

echo
echo "==== Phase 4 smoke summary ===="
echo "  pass=$pass  fail=$fail  rc=$rc  (logs: $LOGDIR/)"
[ "$fail" -eq 0 ]
