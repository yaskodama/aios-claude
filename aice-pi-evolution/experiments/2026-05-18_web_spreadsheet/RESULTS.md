# Web Spreadsheet — MAP-Elites Design Exploration Results (2026-05-18)

実行: `cd aice-evolution-v2 && AIPL_AI_PROVIDER=openai AIPL_AI_EVAL_WORKERS=8 python3 -m src.cli ../aice-pi-evolution/experiments/2026-05-18_web_spreadsheet/AIPL_WebSpreadsheet.aice --ai --abcl`

16 個体 / 8 世代 / 11 cells filled / 約 5 分 (OpenAI gpt-4o-mini × 8 並列).

## Top 5 elites

| Rank | id  | gen | composite | state_repr  | concurrency_model | effect_handling | ownership |
|------|-----|----:|----------:|-------------|-------------------|-----------------|-----------|
| 1    | I0011 | 3 | **0.802** | symbol_owned | structured      | monadic         | gc        |
| 2    | I0006 | 0 | 0.746     | symbol_owned | csp_channels    | capability      | gc        |
| 3    | I0004 | 0 | 0.743     | ADT          | structured      | monadic         | rc        |
| 4    | I0002 | 0 | 0.682     | symbol_owned | threads_locks   | monadic         | linear    |
| 5    | I0008 | 0 | 0.656     | ADT          | actor_messages  | capability      | gc        |

**収束軸** (top 2 で一致): `state_representation=symbol_owned`, `concurrency_model=structured`,
`effect_handling=monadic`, `ownership_model=gc`. これは round 6 / 7 と同じパターン
(AIPL の ParallelOOP + structured + gc).

## 4 軸の variant ランキング (top 5 elite 平均)

### T — Cell Representation

| Rank | Variant | Avg | Verdict |
|------|---------|----:|---------|
| 🥇   | **T4 ActorPerCell**  | **0.660** | AIPL ネイティブ. 1 cell = 1 actor + LWW. DR-13 pool が支える. |
| 2    | T1 DenseMatrix       | 0.609 | 単純、ベンチ有利だが sparse data でメモリ無駄 |
| 3    | T2 SparseMap         | 0.600 | 95% empty な実 sheet で空間効率良 |
| ❌   | T3 Columnar          | 0.574 | analytics 専用で general-purpose には不適 |

### C — Compute Location

| Rank | Variant | Avg | Verdict |
|------|---------|----:|---------|
| 🥇   | **C1 ClientFull**       | **0.683** | オフライン可、レスポンス即時. AIPL Level-A eval を client へ移植 |
| 2    | C3 Hybrid               | 0.643 | best UX だが double-impl コスト |
| 3    | C2 ServerFull           | 0.623 | thin client, collab 自然だがオフライン不可 |
| ❌   | C4 ActorDistributed     | **0.466** | AIPL native だが debug 困難、MVP overkill (圧倒的最下位) |

### S — Sync Model

| Rank | Variant | Avg | Verdict |
|------|---------|----:|---------|
| 🥇   | **S1 SingleUser**       | **0.600** | MVP として最小. collab は後続 round で追加 |
| 2    | S4 ServerAuthoritative  | 0.571 | optimistic client + server CRDT merge の中間 |
| 3    | S2 CRDT-LWW             | 0.554 | DR-10 LWW prim 直結だが MVP overkill 判定 |
| ❌   | S3 OperationalTransform | 0.543 | AIPL 未提供、0 から書く必要 |

### U — UI Rendering

| Rank | Variant | Avg | Verdict |
|------|---------|----:|---------|
| 🥇   | **U2 Canvas_2D**         | **0.626** | 100k cells でも軽量、styling は描画コード側 |
| 2    | U1 DOM_VirtualScroll     | 0.606 | accessibility 良、styling 自由 |
| 2    | U3 SVG                   | 0.606 | scalable, 印刷 / export 強 |
| ❌   | U4 WebGL                 | 0.563 | million-cell scale だが MVP には過剰 |

## 推奨 MVP 設計: **(T4, C1, S1, U2)**

```
┌─────────────────────────────────────────────────┐
│ Web Spreadsheet MVP (AIPL-based)                │
├─────────────────────────────────────────────────┤
│ T4  ActorPerCell      ── 1 cell = 1 AIPL actor │
│ C1  ClientFull        ── browser-abcl で formula│
│ S1  SingleUser        ── MVP は単独編集のみ     │
│ U2  Canvas_2D         ── 単一 canvas で全描画   │
└─────────────────────────────────────────────────┘
```

**理由**: AIPL の actor model を最大限活かしつつ MVP コストを最小化する組合せ.
S1 → S2 → S4 の段階的拡張で collab を後で乗せる戦略.

## 横断的タスクのスコア

| Task | Avg | Note |
|------|----:|------|
| FormulaCore               | 0.649 | Level-A metacircular eval 流用 |
| ImportExportCSV           | 0.629 | read_file/write_file + str_split で MVP |
| ShareLinkAndPermissions   | 0.623 | CE-11 cap + HMAC-signed URL |
| ExcelSheetsParity         | 0.614 | core 4 軸 (cell+formula+collab+share) のうち 3 つ達成 |
| BackwardCompat26          | 0.609 | 既存 26 機能 + 71 abclc + 14 JS nextgen + 47 self-host smoke 無修正動作 |
| ImplCostMVP               | 0.597 | ≤4000 LOC レンジ |
| PersistenceLayer          | 0.589 | AIPL_DIST_CHECKPOINT_DIR (DR-4) と読書 file |
| TwoRuntimeFloor           | 0.557 | Py-I + JS-N + browser-abcl の 3 ランタイム協調 |

## 見積もり LOC

| Component | LOC 見積もり |
|-----------|--------------:|
| T4 ActorPerCell (cell actor + DR-13 pool 設定) | 300-500 |
| C1 ClientFull (Level-A eval + builtin func table) | 200-300 |
| S1 SingleUser (localStorage / fs persistence) | 50-100 |
| U2 Canvas_2D (rendering loop + text/border) | 200-300 |
| FormulaCore (parser + ref/range + 5 関数 + topological recompute) | 250-400 |
| PersistenceLayer (load/save with CE-11 cap) | 100-200 |
| ShareLinkAndPermissions (URL + HMAC) | 200-300 |
| ImportExportCSV (str_split + escape) | 100-150 |
| **MVP 合計** | **≈ 1400-2250 LOC** |

ImplCostEstimator 評価 (0.597) が見越したレンジ ≤4000 LOC の **下半分** に収まる見込み.

## 次の round / 実装フェーズ

1. **Round 9 (variant refinement)**: 必要なら T4 内部 (actor cluster strategy) や U2 内部 (renderer
   batching strategy) に zoom in.
2. **Round 10 (implementation phase)**: Py-I/JS で MVP を実装. (T4, C1, S1, U2) クワドルプル.
3. **Round 11+ (collab 後追加)**: S1 → S4 ServerAuthoritative → S2 CRDT に段階的に拡張.

## 出力ファイル (aice-evolution-v2/out/)

- `AIPL_WebSpreadsheet.lineage.json` — 16 個体の全 fitness_components
- `AIPL_WebSpreadsheet.elite_map.json` — 11 cells filled
- `AIPL_WebSpreadsheet.ranking.json` — 5 scenario の Pareto/pairwise
- `AIPL_WebSpreadsheet.report.md` — 自動生成レポート
