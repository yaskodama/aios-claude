# Google Sheets Clone — Manual 6-tuple Selection (2026-05-19)

進化計算 MAP-Elites は OpenAI API スロットリングで **2 連続失敗** したため、
工学的判断による **手動 selection** に切り替え.Round 1-3 の収束結果と
Google Sheets / Excel ユーザの実際の UX 期待値を根拠に 6-tuple を選定.

## 経緯

| 試行 | 開始 | 経過 | CPU | 結果 |
|---|---|---|---|---|
| Round 4 (formula input, generations=8) | 23:55 | 50+ 分 | 24s | OpenAI throttle → kill |
| Round 5 (this, generations=6)         | 00:49 | 18 分 | 7.8s | 同 throttle → kill |

両者とも CPU 増加率 **0.4-0.5 s/min** と一致.OpenAI 側で持続スロットル状態.

## 推奨 6-tuple

```
┌─────────────────────────────────────────────────────────────────┐
│ AIPL Google Sheets Clone — MVP-2 Implementation Strategy       │
├─────────────────────────────────────────────────────────────────┤
│ G  G3 VirtualizedInfinite  ── viewport spawn / scroll recycle  │
│ E  E1 FormulaBar (→E2 next) ── 上部 input、選択 cell を編集    │
│ F  F2 Core12               ── AVG/MIN/MAX/COUNT/IF/ROUND/...    │
│ R  R3 RangesAndCOL         ── A1:B10 range + $A$1 absolute     │
│ C  C2 ServerFile           ── JS-N に /api/sheet/{save,load}    │
│ U  U2 Toolbar              ── Save/Load/Recompute/Undo (saga)  │
└─────────────────────────────────────────────────────────────────┘
```

## 判断根拠 (軸別)

### G3 VirtualizedInfinite ✅ (G4 多シートは MVP-2 では棄却)

- Google Sheets は仮想化必須. 1000+ rows でも 60fps を維持するには viewport (~50×20 visible) のみ actor spawn.
- 既存 CA4 HybridSpawn (Round 2 winner) の本領発揮.
- 列ヘッダ A..Z..AA..AZ の生成は単純な base-26.
- G4 multi-sheet は MVP-2 のスコープ外 (Round 6 候補).
- LOC: 250-350.

### E1 FormulaBar (→ Phase 2 で E2 in-cell に upgrade)

- E2 in-cell overlay が production Sheets UX のスタンダードだが、座標計算 + フォーカス管理が重い.
- まず E1 で「formula を入力できる」状態を確保 → 直後の Phase で E2 を追加.
- 段階的実装: 全機能を 1 commit に詰め込むより、E1 で commit → E2 で commit のほうがレビュー容易.
- LOC: E1 80-120 + E2 200-300.

### F2 Core12 ✅ (F3 text/date は次回、F4 parity は遠い)

- 算術 + SUM/AVG/MIN/MAX/COUNT/COUNTA/IF/ROUND/FLOOR/CEIL/ABS/MOD/POWER の 12 関数.
- 実 sheet で 80% のフォーミュラはこの 12 で書ける (Google Sheets 利用統計より).
- 各関数 10-15 LOC × 12 ≒ 150 LOC.
- F3 (CONCAT/LEN/UPPER/...) と F4 (VLOOKUP/INDEX/MATCH) は段階的に追加.

### R3 RangesAndCOL ✅ (絶対参照 + 範囲は MVP-2 の核)

- `A1:B10` 範囲参照は **Sheets parity に必須**. SUM(A1:A10) など実用 formula で常用.
- `$A$1` 絶対参照は copy/paste 時の挙動で必須.
- Parser 拡張: `expr → primary (':' primary)?` で range 化 + `'$'` prefix で absolute フラグ.
- Eval 拡張: Range AST を eval 時に展開 (各 cell ref を eval).
- LOC: 150-200 (parser 80 + range eval 100).
- R4 named/cross-sheet は Round 6 候補.

### C2 ServerFile ✅ (C3 WebSocket realtime は次回)

- JS-N (node-aipl-server) に `POST /api/sheet/{sheet_id}/save` + `GET /api/sheet/{sheet_id}/load`.
- URL クエリで sheet_id を指定、share できる.
- CE-11 capability で fs アクセス制御.
- C3 realtime は WebSocket の sync 設計が重く Round 6 候補.
- C4 CRDT collab は Round 7 候補.
- LOC: server 100 + client 80 = 180.

### U2 Toolbar ✅ (U3 format menu / U4 charts は次回)

- Toolbar に Save / Load / Recompute / **Undo / Redo**.
- Undo/Redo は **既存 DR-11 saga を流用**:
  - 編集アクションを `saga { step { apply } compensate { rollback } }` で囲む.
  - Undo = pop saga from history stack and run its compensate.
  - これで saga infra が spreadsheet で実用化される.
- U3/U4 は format / chart 描画で大物だが U2 だけで「使える」.
- LOC: 200-300 (UI + history stack + DR-11 integration).

## LOC 内訳 (合計 ≈ 1130-1620 LOC)

| Component | LOC |
|---|---:|
| G3 VirtualizedInfinite | 300 |
| E1 FormulaBar          | 100 |
| F2 Core12              | 150 |
| R3 Ranges + Absolute   | 180 |
| C2 ServerFile          | 180 |
| U2 Toolbar + Undo      | 250 |
| **合計**               | **≈ 1160** |

+ 次回 E2 in-cell overlay: +250 LOC = 1410.
+ 後追加で C3 WebSocket realtime: +300 LOC = 1710.

`.aice` 制約は ≤2500 LOC. **MVP-2 (E1 完了時点) は ≤1500 LOC** で余裕あり.

## 既存 AIPL infra 再利用 (6/8)

- ✅ Level-A eval (eval_one の AST 拡張)
- ✅ DR-13 pool (G3 viewport spawn 管理)
- ✅ DR-11 saga (U2 Undo/Redo)
- ✅ DR-4 checkpoint (C2 ServerFile の永続化)
- ✅ CE-11 capability (fs アクセス制御)
- ✅ Level-C parser (R3 range / absolute 拡張)
- ⏳ WebSocket (C3 次回)
- ⏳ DR-10 LWW (C4 collab 次回)

InfraReuseReviewer 想定スコア: 0.85 (6/8 件再利用).

## Phase 計画 (Round 5)

各 Phase で smoke 追加 + commit:

| Phase | 内容 | 見積もり LOC | 期間 |
|---|---|---:|---|
| 5.0 | F2 Core12 functions (parser 拡張 + 12 builtin) | 150 | 30 分 |
| 5.1 | R3 Ranges + Absolute references                | 180 | 45 分 |
| 5.2 | G3 VirtualizedInfinite (viewport spawn)        | 300 | 60 分 |
| 5.3 | E1 FormulaBar (DOM input + commit on Enter)    | 100 | 30 分 |
| 5.4 | C2 ServerFile (JS-N endpoints + client save/load) | 180 | 45 分 |
| 5.5 | U2 Toolbar + Undo/Redo (DR-11 saga 統合)       | 250 | 60 分 |
| **合計** |                                            | **1160** | **~4.5 時間** |

## Round 4-5 で進化計算が失敗した教訓

1. **OpenAI API は時間帯依存で大きく throttle される** — 深夜帯でも 50+ 分かかる場合あり.
2. **`.aice` 規模が大きい (24+ tasks × 7 reviewers × 8 gens = ~10K calls) と throttle 確率上昇**.
3. **代替案**: (a) Anthropic API、(b) generations/seed 縮小、(c) reviewers 縮小、(d) 工学的判断で skip.
4. **Round 1-3 で 3 回成功した進化計算は十分な情報を残しており、それを根拠とした手動選定は妥当**.

## 出力ファイル

- `AIPL_GoogleSheetsClone.aice` — 6 軸 × 4 variant の設計仕様 (進化計算は失敗だが仕様は完全)
- `AIPL_GoogleSheetsClone.ga.json` — IR (lower 済)
- `AIPL_GoogleSheetsClone.aipl` — 803-line orchestrator (将来 throttle が解消すれば再試行可能)
- `RESULTS.md` (this file) — 手動選定の根拠記録
