# Web Spreadsheet — Next-Session Handoff

最終更新: 2026-05-20、HEAD = `4b01733`

このセッションでは AIPL ランタイム (browser-abcl + node-aipl-server + AIPL
インタプリタ) 上に **Google Sheets / Excel ライクな Web スプレッドシート** を
構築した.合計 **39 commits / Round 5..8 / 30+ phase** を積み上げ、現状で
**Phase 4 smoke 8/8 + Round 全 smoke 380+ assertion** がすべて green.

このドキュメントは「次セッションで開いたとき何が動いていて何が動いていない
かが 1 ファイルで分かる」ことを目的とする.

---

## TL;DR — 動作する最終形

- **URL**: `http://localhost:3000/spreadsheet.html` (api: `:8090`)
- **メインファイル**: `src/browser-abcl/spreadsheet.html` (~4100 行、ほぼ全機能)
- **AIPL ホスト**: `src/browser-abcl/spreadsheet.aipl` (Cell actor 9 個 + Bus + View)
- **AIPL runtime**: `src/browser-abcl/src/runtime.js` (canvas 描画 + spreadsheet 用 builtin)
- **API/WS サーバ**: `src/node-aipl-server/server.mjs` (`/api/sheet/<id>/{save,load}` + `/ws`)
- **永続データ**: `/tmp/aipl_sheets/<sheet_id>.json` (P4 auto-save + manual Save)

サーバ起動:
```bash
cd src/node-aipl-server && PORT=8090 node server.mjs &
cd src/browser-abcl     && npx serve -l 3000 . &
open http://localhost:3000/spreadsheet.html
```

ブラウザは Cmd+Shift+R でハードリロード (キャッシュ問題が頻発).

---

## アーキテクチャ概要

```
┌─────────────────── browser tab (spreadsheet.html) ─────────────────┐
│                                                                     │
│  ┌─ JS-side formula evaluator (~600 LOC) ─────────────────────┐   │
│  │   parseFormula / evalAst / evalRange / evalRangeGrid       │   │
│  │   maybeSpill (F6) / depGraph + cascadeRecompute (F13)      │   │
│  │   matchCondition / lwwWins / colToLetters / lettersToCol   │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─ per-sheet state Maps (MS rebinds on switchToSheet) ──────┐   │
│  │   cellValues / cellFormulas / cellFormats / cellClocks    │   │
│  │   cellNotes  / cellLocked   / cellNames                   │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─ AIPL Interpreter (src/runtime.js + spreadsheet.aipl) ────┐   │
│  │   Cell × 9 actors → Bus → View → canvas builtins           │   │
│  │   sheet_init / sheet_cell / sheet_select / sheet_select_   │   │
│  │   range / sheet_cell_bg / sheet_cell_note / sheet_peer_    │   │
│  │   cursor                                                    │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─ WebSocket client (C3-C6) ───────────────────────────────┐   │
│  │   sends: 11 frame types — see "Live sync" below            │   │
│  │   receives: applies under wsApplyingRemote=true guard      │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─ window._sheet — テスト hook ─────────────────────────────┐   │
│  │   Puppeteer smoke が中身を覗くための getter+method 群       │   │
│  └────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ↓  POST /api/sheet/<id>/save   GET /load
                                ↓  GET  /ws?sid=sheet:<id>
                ┌─────────── node-aipl-server (port 8090) ──────────┐
                │  server.mjs   /api/sheet/{save,load,list}         │
                │               /ws (broadcast per sid)             │
                │  /tmp/aipl_sheets/*.json                          │
                └────────────────────────────────────────────────────┘
```

---

## 完成した Phase 一覧 (Round 5 → 8)

| Phase | 内容 | Smoke |
|---|---|---|
| **Round 5/6 — 基本機能** | | |
| C3 | WebSocket realtime collab | - |
| C4 | DR-10 LWW per cell (Lamport ts + origin tiebreak) | 10/10 |
| C5 | Persist LWW clocks across save/load | 11/11 |
| U5 | Mouse-drag range selection | - |
| U7 | Keyboard nav (arrows / Tab / Enter / Delete / Escape) | 7/7 |
| U8 | Clipboard Cmd+C/V/X | 8/8 |
| U9 | Configurable cellWidth / rowHeight | 5/5 |
| U10 | Find / Replace / Replace-all | 10/10 |
| U11 | Sticky frozen header (1st row only) | 3/3 |
| U12 | Fill ↓ / Series (arithmetic) | 5/5 |
| U13 | Insert / Delete row / column | 8/8 |
| G4 | Dynamic grid 10×8 + Resize panel | 8/8 + 7/7 |
| G5 | Multi-letter cols AA..BH (max 60) | 9/9 |
| F5 | 20 new functions (AVERAGE, MEDIAN, COUNTIF, …) | 27/27 |
| F6 | Array-formula SPILL `=A1:A3*2` | 9/9 |
| F7 | String / mixed-type comparisons + `=` and `<>` | 16/16 |
| F8 | Conditional formatting (3 colors) | 4/4 |
| F9 | Per-cell comments + corner marker | 2/2 |
| F10 | Per-cell write-lock | 4/4 |
| F11 | Named cells `tax → A1` | 2/2 |
| Y2 | Chart kinds bar / line / pie | 4/4 |
| Y3 | Scatter chart | 1/1 |
| D1 | CSV import / export | 15/15 |
| D2 | XLSX export (hand-rolled ZIP + XML, no deps) | 14/14 |
| D3 | XLSX import (DEFLATE via DecompressionStream + sharedStrings) | 15/15 |
| D4 | Print / Save-as-PDF (`@media print`) | 2/2 |
| P4 | Debounced auto-save (3-sec idle) | 6/6 |
| C6 | Live peer cursor sync (color-coded outline) | 4/4 |
| Load-bc | Broadcast Load snapshot to ws peers | 6/6 |
| **Round 7 — ユーザ指定** | | |
| EQ | `=` prefix required for formulas; source round-trips | 8/8 |
| D5 | Loss-less JSON workbook export / import | 13/13 |
| MS | Multi-sheet workbook + `Sheet2!A1` cross-sheet refs | 11/11 |
| U14 | Undo / Redo panel + N-step jump (Cmd+Shift+Z / Cmd+Y) | 11/11 |
| F12 | Macros (record / save / play) | 10/10 |
| C7 | "Live: N peers" presence badge + 10s TTL | 5/5 |
| Y4 | Heatmap chart (blue → red color ramp) | 4/4 |
| **Round 8 — 追加機能** | | |
| F13 | Dependency-tracked auto-recompute | 11/11 |
| U15 | Shift + arrow range selection | 3/3 |
| F14 | Cross-sheet ranges in functions | 3/3 |
| D6 | Markdown table export | 5/5 |
| U16 | In-cell editor overlay (dblclick / F2 / typing) | 8/8 |
| **C3 follow-ups (Live 同期完備)** | | |
| - | Formula bar refresh on remote landing | 1/1 |
| - | Local sel highlight uses peer-color (follows cursor) | 3/3 |
| - | Synchronous selection highlight + dblclick syncs sel | 4/4 |
| - | F8 bg target follows live selection | 5/5 |
| - | F8 blank-default cfValue → unconditional paint | (repro) |
| - | F8 bg ws sync `{type:"bg"}` | 5/5 |
| - | F9/F10/F11 ws sync `{type:"note","lock","name"}` | 10/10 |
| - | G4/U9 ws sync `{type:"resize"}` | 8/8 |
| - | MS sync `{type:"sheet_add","_rename","_delete"}` | 6/6 |

**累計 smoke**: 約 380 assertion green (Phase 4 8 + Round 5/6 197 + Round 7 62 + Round 8 30 + Live 同期 42)

---

## Live 同期で流れる 11 種類のメッセージ

| Frame | キー | 概要 |
|---|---|---|
| `cell` | row, col, val, kind, formula, fmt, ts, origin | 通常のセル値変更 (LWW 付き) |
| `cursor` | row, col, origin, color | カーソル位置 (C6) |
| `load` | snapshot | フルロード時の一括配信 |
| `bg` | row, col, color, origin | F8 背景色 |
| `note` | row, col, text, origin | F9 コメント |
| `lock` | id, locked, origin | F10 ロック |
| `name` | name, target, origin | F11 named cell |
| `resize` | rows, cols, cellW, rowH, origin | G4/U9 グリッド寸法 |
| `sheet_add` | name, origin | MS シート作成 |
| `sheet_rename` | oldName, newName, origin | MS リネーム |
| `sheet_delete` | name, origin | MS 削除 |

すべての受信パスは `wsApplyingRemote=true` ガードでループを防ぐ.

---

## 主要 UI 要素 (上から順)

1. **canvas** — メインのグリッド表示 (10×8 default, 最大 50×60)
2. **freeze first row** checkbox + `frozenHeader` sticky bar (U11)
3. **cellLabel** + **formulaBar** — 選択セルの参照 + 編集
4. **sheetIdRow** — sheet_id 入力 + `🟢 Live` toggle + presence badge
5. **resizeRow** — `rows / cols / cellW / rowH` + `📐 Resize`
6. **formatRow** — 数値/通貨/パーセント/日付 (per-cell format menu)
7. **noteRow** — F9 コメント + `🔒 lock` ボタン
8. **macroRow** — F12 マクロ (record/save/play)
9. **nameRow** — F11 named cell 定義
10. **findRow** — U10 検索/置換
11. **cfRow** — F8 条件付き書式 (red/yellow/green/clear)
12. **rangeRow** — Sort↑↓ / Filter / Chart (種別 dropdown) / Fill ↓ / Series / Insert+Delete row/col
13. **chart** canvas — グラフ描画領域
14. **sheetTabs** (MS) — シートタブバー
15. **controls** toolbar — Run / Save / Load / Recompute / Undo / Redo / 📜 History / CSV / XLSX / PDF / Markdown / JSON / etc.
16. **historyPanel** (U14, 隠れている) — Undo/Redo 履歴可視化
17. **inCellEditor** (U16, 隠れている) — セル上で直接編集する `<input>`

---

## キーボード

| Key | 動作 |
|---|---|
| Arrow keys | セル移動 |
| Shift+Arrow | 範囲拡張 (U15) |
| Tab / Shift+Tab | 水平移動 |
| Enter | formula bar に focus → 入力 |
| Delete / Backspace | 選択セル (or 範囲) クリア |
| Escape | 範囲解除 / 編集キャンセル |
| F2 | in-cell editor 起動 (U16) |
| 印字可能文字 | 自動で in-cell editor + その文字から開始 |
| ダブルクリック | in-cell editor 起動 |
| Cmd/Ctrl + C/V/X | clipboard (U8) |
| Cmd/Ctrl + Z | Undo |
| Cmd/Ctrl + Shift + Z | Undo (alternate) |
| Cmd/Ctrl + Y | Redo |

---

## 数式リファレンス

```text
=42                  リテラル
=A1+B1               セル参照 + 算術
=A1:A3*2             SPILL — A1, A2, A3 を 2 倍して 3 セル展開 (F6)
=Sheet2!A1           クロスシート参照 (MS)
=SUM(Sheet2!A1:A3)   クロスシート範囲 (F14)
=IF(A1>10, "big", "small")        条件分岐 + 文字列
=COUNTIF(A1:C3, ">100")           条件付き集計 (F5)
=SUMIF(A1:C3, ">=30")
=AVERAGEIF(A1:C3, "<25")
=IFERROR("", 99)                  エラーハンドリング
=A1="hello"                       文字列等価 (F7, EQ 必要)
=A1<>0                            not-equal (F7)
=LARGE(A1:A10, 2) / SMALL / MEDIAN / STDEV / VAR
=AVERAGE / SQRT / INT / SIGN / EXP / LN / LOG10 / PI()
=AND / OR / NOT
=WEEKDAY(TODAY())
=CONCAT / LEN / UPPER / LOWER / TRIM / SUBSTITUTE / LEFT / RIGHT / MID
=DATE / YEAR / MONTH / DAY / NOW
=VLOOKUP / HLOOKUP / INDEX / MATCH / CHOOSE
=tax * 100           named cell alias (F11)
```

依存セルが変わると **F13 が自動再計算** する (Recompute ボタン不要).

---

## ファイルマップ (重要なもの)

```
src/browser-abcl/
├── spreadsheet.html          # メイン (~4100 行) — UI + 数式評価 + ws
├── spreadsheet.aipl          # AIPL Cell actor (9 セルの初期データ)
├── src/
│   ├── runtime.js            # canvas 描画 + spreadsheet 用 builtin
│   ├── lww.js                # lwwWins / newClientId
│   ├── ast.js, interpreter.js, parser/, typecheck.js  # AIPL core
├── _smoke_spreadsheet.sh     # Phase 4 smoke (8 assertion)
├── _smoke_lww.{mjs,sh}       # LWW smoke (10 assertion)
└── (ad-hoc tests live in /tmp/_ppt/_*.mjs — see git log for which)

src/node-aipl-server/
├── server.mjs                # /api/sheet/{save,load,list} + /ws
└── _smoke_test.sh            # 14 assertion (api + ws)

src/python-aipl/samples/spreadsheet/
├── README.md                 # phase table (long)
└── NEXT_SESSION.md           # ← このファイル

aice-pi-evolution/experiments/2026-05-19_round7_formula_prefix_multisheet/
├── AIPL_Spreadsheet_Round7.aice    # Round 7 設計仕様
├── AIPL_Spreadsheet_Round7.ga.json # MAP-Elites IR
└── out/                            # 進化計算結果 (mock evaluator, 38 個体)
```

---

## 既知の制限事項 / 未対応項目

1. **クロスシート Live 同期は MS タブメタのみ**.
   セル frame (`cell`, `bg`, `note`, etc.) に `sheet` フィールドが無いため、
   ピアが Sheet2 を見ている状態で受信した frame は無条件で active sheet に
   書き込まれる.→ 同じシート名にいる時のみ完全同期.

2. **AIPL Cell actor は初期 9 個のみ**.spreadsheet.aipl の 9 個の
   ハードコード Cell が動くだけで、UI からの追加・編集は JS 側 cellValues
   経由 (AIPL のセルアクター数は変動しない).

3. **マクロは workbook scope 単発**.シート切り替えで macros Map も
   各シート独立だが、cross-sheet macro 再生はテストしてない.

4. **チャート設定は ws 非同期**.peer の `📊 Chart` 押下は伝播しない.

5. **U16 in-cell editor は 1 セル単位**.範囲一括の Ctrl+Enter は未実装.

6. **Cmd+F (ブラウザ Find) は奪われている**.U10 検索は専用 row 使用.

7. **数式パーサのエラーは式が壊れていると単なる 0 を返す**.
   IFERROR でラップしないと壊れた `=A+` のような式が 0 になる.

8. **chart の `gatherChartPairs` は cellValues に依存**.
   AIPL 初期化直後の 200ms 間は空マップなので chart 描画は遅延.

9. **Markdown export は値のみ** (formula source を出さない).

10. **クロスタブ通信のセキュリティは ws 平文**.HTTPS / 認証なし.

---

## 次セッションでやり得る候補

優先度 A (User がリクエストしそう):
- **セル frame に `sheet` フィールド** — クロスシート Live 同期の完全化 (~30 LOC)
- **U17 右クリックコンテキストメニュー** — copy/paste/insert row 等を一箇所に
- **U18 数式オートコンプリート** — `=SU` → SUM/SUMIF 候補

優先度 B:
- **F15 IFS / SWITCH / 統計関数 (CORREL, FORECAST)**
- **U19 1 列目固定 (frozen first column)** — U11 の col 版
- **F16 配列 SPILL の拡張** — `=A1:A3 + B1:B3` のような vec+vec
- **Y5 グラフタイトル + 凡例の編集 UI**

優先度 C (大物):
- **U20 マウスドラッグで列幅変更** — ヘッダ境界をドラッグ
- **AIPL → JS 関数バインディング統合** — AIPL 側からも JS の関数を呼べる
- **オフライン PWA 対応** — IndexedDB + Service Worker
- **F17 Pivot table** — クロス集計

---

## 進化計算アーティファクト (Round 7)

`AIPL_Spreadsheet_Round7.aice` → `AIPL_Spreadsheet_Round7.ga.json` → MAP-Elites
30 世代 / 38 個体 (mock evaluator) を実行.

結果: 全 3 シナリオ (conservative / innovative / general_purpose) で
`I0008 (ParallelOOP / type_safety=high / actor_messages /
algebraic_effects)` が 1 位.AIPL 既存軸 (actor + LWW = actor_messages)
と一致、Round 6 までの選択が validated.

実 LLM 評価は OpenAI throttle 履歴 (Round 4/5 で 18-50 分ハング) があるため
未実施.`--ai` フラグ + `OPENAI_API_KEY` で起動可だがリスクあり.

---

## サーバ状態のスナップショット

`/tmp/aipl_sheets/` に保存済みの `<sheet_id>.json` ファイル群:
- `demo` (10×8 default, 9 セルの初期データ)
- `p4_test_*` (P4 smoke の残骸)
- `eq_test_*`, `bg_sync_*`, `noteLockName_*`, `sheet_tab_sync_*` etc.

これらは `curl http://localhost:8090/api/sheet/list` で列挙可.

---

## デバッグ用 hook (window._sheet)

ブラウザ DevTools console で `window._sheet` から直接呼べる:

```javascript
// 状態 inspect
window._sheet.cells          // sheetState.cells
window._sheet.state          // sheetState 本体
window._sheet.cellValues     // Map<id, val>
window._sheet.cellFormulas   // Map<id, "=...">
window._sheet.cellFormats    // Map<id, format>
window._sheet.cellClocks     // Map<id, {ts,origin}>
window._sheet.cellNotes      // Map<id, text>
window._sheet.cellLocked     // Set<id>
window._sheet.cellNames      // Map<name, target>
window._sheet.cellBgs        // Map<"r,c", color>
window._sheet.clientId       // "c-xxxxxx"
window._sheet.lamport        // 現在の論理時計
window._sheet.workbook       // {sheets:[…], activeIdx}
window._sheet.macros         // Map<name, ops>
window._sheet.peerActivity   // Map<origin, {row,col,color,at}>
window._sheet.depGraph       // Map<formulaId, Set<dep_id>>
window._sheet.reverseDeps    // Map<dep_id, Set<formulaId>>

// API
window._sheet.evalFormula("SUM(A1:C3)")
window._sheet.setSelected(row, col)
window._sheet.importCsv("a,b\n1,2", { row: 0, col: 0 })
window._sheet.buildCsv() / buildXlsx() / buildMarkdown() / buildJsonWorkbook()
window._sheet.macroStart() / macroStop() / macroSave() / macroPlay("name")
window._sheet.cascadeRecompute(["A1"])
window._sheet.addSheet("Sheet3") / switchToSheet(idx)
```

---

## 既存 smoke の一括実行

```bash
# Phase 4 (AIPL の Cell actor が canvas を populate するか) — 8 assertion
bash src/browser-abcl/_smoke_spreadsheet.sh

# LWW pure unit + 実 ws 経由の race test — 10 assertion
bash src/browser-abcl/_smoke_lww.sh

# node-aipl-server (api + ws + save/load + CORS) — 14 assertion
bash src/node-aipl-server/_smoke_test.sh

# Puppeteer smoke 群 (環境依存、/tmp/_ppt から)
cd /tmp/_ppt && for s in _*.mjs; do echo "=== $s ==="; node "$s" | tail -3; done
```

---

## 直近 39 commit (要約)

```
4b01733 MS: sync sheet-tab add / rename / delete over ws
b0fe458 G4/U9: sync grid resize over ws
909bca7 F9/F10/F11: sync notes / locks / named cells over ws
6496a9e F8: sync background-color paint over WebSocket
de45c11 F8: blank-by-default cf value (paints unconditionally)
d05e07c F8: bg-color target follows the live selection
3595053 C6: synchronous selection highlight + dblclick syncs sel
f4a10c6 C6: local selection tint = own peer-color (follows cursor)
e70be39 C3: refresh formula bar / format / note on remote landing
cac7400 U16: in-cell editor overlay (Round 8 step 3)
cbc7cc4 U15 + F14 + D6 batch (Round 8 step 2)
e836125 F13: dependency-tracked auto-recompute (Round 8 step 1)
394e60f U14 + F12 + C7 + Y4: Round 7 completion batch
a8872d6 MS: multi-sheet workbook (Round 7, step 3)
ed3ea43 D5: loss-less JSON workbook export / import (Round 7, step 2)
2355fa6 EQ: require `=` prefix for formulas (Round 7, step 1)
4177d36 C6: lighter peer-cursor color + soft fill overlay
468c1f1 round7: run MAP-Elites with mock_v1 evaluator (30 gen, 38 ind)
cc4c662 ga.json: lower Round 7 .aice to evolution IR
e8116a9 aice: Round 7 design — `=` formula prefix + multi-sheet + 5 candidates
3571f20 U13 + F10 + F11 + Y3 + C6 batch
3aa7d43 U11 + U12 + F8 + F9 + D4 batch
0c78cfd D3: XLSX import (round-trips D2 + reads Excel/Sheets)
d08387c U10: find / replace / replace-all
69f4483 Load: broadcast snapshot to ws peers
74c79f4 U9 + F6 + D2 + F7: cell sizing, SPILL, XLSX, str-cmp
26f5e4e C5: persist LWW clocks (ts/origin) across save/load
c78d288 Load: reshape canvas + sync resize inputs
c5618cf P4: debounced auto-save (3-sec idle)
5437c6a G5: multi-letter column headers (AA..BH) up to 60 cols
48d4fde D1: CSV import / export
907ed9f Y2: line + pie chart kinds
4c4513e F5: 20 new formula functions
273685c U8: in-memory clipboard (Cmd/Ctrl + C / V / X)
11d078a G4: dynamic grid (default 10×8) + Resize UI
c6eae12 U7: keyboard navigation + range-clear
f6f4f3c U5: mouse-drag range selection
829fe9c C4: per-cell LWW (Lamport ts + originId tiebreak)
d470dc1 C3: WebSocket realtime collab between browsers
```

---

## 重要メモ

- AIPL 拡張子は `.aipl` (`.aipl` ではない) — 過去の混同に注意 (`feedback_aipl_extension.md`)
- `.aice` は YAML ではなく C 風 DSL、`//` で行コメント (`feedback_aice_dsl_syntax.md`)
- 数式は `=` 必須 (EQ 以降の規約) — 平文文字列 "A1+B1" は数値 0 ではなく文字列 "A1+B1" になる
- 各セルの ws 配信は `wsApplyingRemote=true` 内では発火しない (エコー防止)
- module-scope `let cellValues` などは MS によりシート切り替え時に再バインドされる →
  `window._sheet.cellValues` は getter にしないと古い参照をキャプチャしてしまう
- canvas は `Math.max(720, 60+(cols+1)*cellW) × Math.max(380, 60+(rows+1)*rowH)` で自動拡縮
- 進化計算 (`aice-evolution-v2/src/cli.py --no-run`) は IR 生成までは安定、`--ai` で
  実 LLM 評価は throttle リスクあり

---

このドキュメントを最新に保つ責任は次セッションの私 (Claude) にあります.
重要な phase を追加した場合、必ずこの NEXT_SESSION.md と
`src/python-aipl/samples/spreadsheet/README.md` の両方を更新してください.
