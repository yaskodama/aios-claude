# WebSpreadsheet — AIPL implementation (round 3, in progress)

進化計算 round 1-2 で採掘された設計を実装に落とすブランチ.
具体的な選択は:

- Round 1: `aice-pi-evolution/experiments/2026-05-18_web_spreadsheet/RESULTS.md`
- Round 2: `aice-pi-evolution/experiments/2026-05-18_web_spreadsheet_impl/RESULTS.md`

| 項目 | 選定 |
|---|---|
| T (cell 表現)  | T4 ActorPerCell |
| C (計算位置)   | C1 ClientFull |
| S (同期)       | S1 SingleUser (MVP) |
| U (UI)         | U2 Canvas_2D |
| CA (spawn)     | CA4 HybridSpawn |
| FE (eval)      | FE4 ActorEval |
| P  (永続化)    | P3 DistCheckpoint |
| R  (renderer)  | R3 LayerComposite |
| PA (parser)    | PA4 LevelCPort |
| IT (topology)  | IT2 EventBus |

## Phase 進捗

| Phase | 内容 | サンプル | 状態 |
|---|---|---|---|
| 0 | AST-formula eval (parser なし) | `HelloSheet.abcl` | ✅ 5 assertion |
| 1 | PA4 formula parser (`A1`, `+`, `SUM(...)`) | `StringFormulaSheet.abcl` | ✅ 4 assertion |
| 2 | CA4 cell actors + FE4 ActorEval | `ActorSheet.abcl` | ✅ 5 assertion |
| 3 | P3 persistence (save/load) | `PersistedSheet.abcl` | ✅ 5 assertion |
| 4 | R3 renderer + IT2 event bus | `src/browser-abcl/spreadsheet.{html,abcl}` | ✅ 8 assertion |

## Round 5 (Google Sheets parity build-out)

進化計算は OpenAI throttle で 2 連続失敗 → 工学的判断で手動 6-tuple 選定.
詳細は `aice-pi-evolution/experiments/2026-05-19_google_sheets_clone/RESULTS.md`.

| Phase | 内容 | サンプル | 状態 |
|---|---|---|---|
| 5.0 | F2 Core12 functions (12 新関数) | `GSheetsCore12.abcl` | ✅ 12 assertion |
| 5.1 | R3 Ranges + Absolute (`A1:B10`, `$A$1`) | `GSheetsRanges.abcl` | ✅ 10 assertion |
| 5.2 | G3 VirtualizedInfinite (viewport spawn) | `GSheetsVirtualized.abcl` | ✅ 10 assertion |
| 5.3 | E1 FormulaBar (DOM input) | `src/browser-abcl/spreadsheet.html` | ✅ (browser-only, smoke unchanged) |
| 5.4 | C2 ServerFile (JS-N /api/sheet/...) | `src/node-aipl-server/server.mjs` + `spreadsheet.html` | ✅ 4 server smoke |
| 5.5 | U2 Toolbar + Undo (DR-11 saga 流用) | `src/browser-abcl/spreadsheet.html` + `runtime.js` cell-replace fix | ✅ |
| C3  | WebSocket realtime collab between browsers | `src/browser-abcl/spreadsheet.html` + `src/node-aipl-server/server.mjs` /ws | ✅ |
| C4  | DR-10 LWW per cell (Lamport ts + originId tiebreak) | `src/browser-abcl/src/lww.js` + `_smoke_lww.{mjs,sh}` | ✅ 10 assertion |
| U5  | Mouse-drag range selection + range highlight overlay | `src/browser-abcl/spreadsheet.html` + `runtime.js` sheet_select_range | ✅ (Puppeteer drag A1→B2 verified) |
| U7  | Keyboard nav (arrows / Tab / Enter↓ / Delete / Escape) | `src/browser-abcl/spreadsheet.html` selection-vs-editing mode | ✅ 7 assertion |
| G4  | Dynamic grid: default 10×8 + 📐 Resize (preserves cells) | `src/browser-abcl/spreadsheet.abcl` + `spreadsheet.html` | ✅ 7 assertion |
| U8  | Clipboard: Cmd/Ctrl + C / V / X over range or cell (undo-aware) | `src/browser-abcl/spreadsheet.html` | ✅ 8 assertion |
| F5  | 20 new functions: AVERAGE/MEDIAN/SQRT/INT/SIGN/EXP/LN/LOG10/PI/STDEV/VAR/LARGE/SMALL/AND/OR/NOT/COUNTIF/SUMIF/AVERAGEIF/IFERROR/WEEKDAY | `src/browser-abcl/spreadsheet.html` evalAst | ✅ 27 assertion |

## smoke

```sh
bash src/python-aipl/samples/spreadsheet/_smoke.sh
# → pass=51  fail=0 (Phase 0 + 1 + 2 + 3 + 5.0 + 5.1 + 5.2)

bash src/browser-abcl/_smoke_spreadsheet.sh
# → pass=8  fail=0 (Phase 4 — browser UI via node-side bridge)
```

Phase 4 の HTML を実際にブラウザで開く:
```sh
cd src/browser-abcl && npx serve .
# → http://localhost:3000/spreadsheet.html
```

## 学んだこと (Phase 2)

Round 2 RESULTS.md は FE4 ActorEval について「synchronous formula chain で deadlock 可能性」と
警告していた.第一次実装で正確にこの問題に当たった: `Sheet → Cell.read → Sheet.read_cell`
の back-edge が Sheet を busy のまま自分自身に send → deadlock.

修正: **Sheet を経由しない**.各 Cell が `dep_ids` / `dep_refs` 配列 (Sheet が
新規 cell を push し続ける同じ配列を by-ref で共有) を持ち、Ref node 解決は
ローカル lookup → `now other.read()` で **Cell→Cell 直接**.

もう一つの教訓: AIPL actor は `now self.X()` を再帰的にできない.再帰 eval は
プレーンな top-level 関数として書く必要あり (`eval_one(node, dep_ids, dep_refs)`).

## 進化計算 → 実装の橋渡し

- `RESULTS.md` の LOC 内訳と推奨 6-tuple は **そのまま実装の北極星**
- 各 phase で増分実装、smoke で前 phase が破綻していないことを確認
- ≤2500 LOC ceiling は round 1-2 で何度も繰り返し確認された制約
