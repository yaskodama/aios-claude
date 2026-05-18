# Web Spreadsheet — Implementation Strategy Refinement Results (2026-05-18)

実行: `cd aice-evolution-v2 && AIPL_AI_PROVIDER=openai AIPL_AI_EVAL_WORKERS=8 python3 -m src.cli ../aice-pi-evolution/experiments/2026-05-18_web_spreadsheet_impl/AIPL_WebSpreadsheet_Impl.aice --ai --abcl`

16 個体 / 8 世代 / 8 cells filled / 約 7 分 (OpenAI gpt-4o-mini × 8 並列).

Round 2 は **refinement** round.Round 1 で採掘された MVP 設計
(T4 ActorPerCell + C1 ClientFull + S1 SingleUser + U2 Canvas_2D) を所与とし、
6 コンポーネントの**実装戦略**を 4 variant ずつ並べ、4096 cell 空間から
ベスト 6-tuple を採掘した.

## Top 5 elites

| Rank | id  | gen | composite | state_repr | concurrency_model | effect_handling | ownership |
|------|-----|----:|----------:|------------|-------------------|-----------------|-----------|
| 1    | I0013 | 5 | **0.716** | ADT         | actor_messages | capability      | gc        |
| 2    | I0007 | 0 | 0.693     | enum_state  | csp_channels   | monadic         | linear    |
| 3    | I0015 | 7 | 0.678     | ADT         | actor_messages | capability      | linear    |
| 4    | I0006 | 0 | 0.656     | enum_state  | actor_messages | implicit        | none      |
| 5    | I0002 | 0 | 0.656     | global_num  | csp_channels   | algebraic_effects| rc       |

### Round 1 → Round 2 軸シフト (重要)

Round 2 reviewer は round 1 の収束軸 (Functional, symbol_owned, structured, monadic, gc) を
**部分的にしか維持しなかった**:

| 軸 | Round 1 winner | Round 2 winner | 解釈 |
|---|---|---|---|
| concurrency_model | structured | **actor_messages** | 実装段階では AIPL の actor model がストレートな fit |
| effect_handling   | monadic     | **capability**     | CE-11 cap を formula 評価の sandbox に活用 |
| state_representation | symbol_owned | **ADT**         | cell value を tagged union (Int/Float/Str/Err) で表現 |
| ownership_model   | gc          | gc (保持)          | AIPL 標準路線 |

Round 1 が「設計の理想」を見たのに対し、round 2 reviewer は「実装時の現実」を
重視し、`actor_messages + capability + ADT` の組合せに振り直した.

## 6 コンポーネントの variant ランキング (top 5 平均)

### CA — CellActor Spawn Strategy

| Rank | Variant | Avg | Verdict |
|------|---------|----:|---------|
| 🥇   | **CA4 HybridSpawn**   | **0.557** | visible cells eager + 範囲外 lazy. scroll で boundary 越えに spawn |
| 2    | CA2 LazyOnEdit        | 0.543 | 編集時のみ spawn. empty cell は actor 持たない |
| 3    | CA3 BlockOfCells      | 0.531 | 10×10 タイル = 1 actor, 内部 dense array |
| 4    | CA1 EagerSpawn        | 0.529 | 全 cell を open 時に spawn |

スコア差 0.028 と小. 状況に応じて選択可だが、reviewer は **CA4 Hybrid** を最良と判断.

### FE — FormulaEval Strategy

| Rank | Variant | Avg | Verdict |
|------|---------|----:|---------|
| 🥇   | **FE4 ActorEval**     | **0.546** | 各 cell actor が自分の formula を評価. AIPL ど真ん中 |
| 2    | FE3 LazyMemoize       | 0.537 | Level-A eval + per-cell memoize, 依存 cell の invalidate |
| 3    | FE1 LevelAReuse       | 0.517 | metacircular.abcl 流用 (50-100 LOC で済む) |
| 3    | FE2 DirectInterp      | 0.517 | 専用 interpreter 新規実装 |

意外に **FE1 LevelAReuse が 3 位タイ**. 「LOC が最小」だけが基準ではなく、
正確な topological recompute が要求されると FE4 ActorEval が勝つ.

### P — Persistence backend

| Rank | Variant | Avg | Verdict |
|------|---------|----:|---------|
| 🥇   | **P3 DistCheckpoint**  | **0.546** | DR-4 既存 AIPL_DIST_CHECKPOINT_DIR を流用 |
| 2    | P2 FsRoundTrip         | 0.529 | read_file/write_file + CE-11 cap fs |
| 3    | P4 IndexedDB           | 0.506 | browser 専用、structured clone |
| ❌   | P1 LocalStorageOnly    | **0.411** | JS-B only. 最下位、JS-N との非対称が嫌われた |

P3 が勝った = 既存 infra 再利用の重要性. P1 圧倒的敗北は **3 ランタイム協調** の
重要さを示す.

### R — Renderer mode (U2 Canvas 内部)

| Rank | Variant | Avg | Verdict |
|------|---------|----:|---------|
| 🥇   | **R3 LayerComposite**  | **0.546** | grid/content/selection を別 canvas + GPU 合成 |
| 2    | R2 DirtyRect           | 0.537 | 変化矩形のみ再描画 |
| 3    | R1 FullRepaint         | 0.534 | 毎フレーム全 cell |
| ❌   | R4 OffscreenCanvas     | 0.471 | Worker 必須、ブラウザ依存強い |

### PA — Parser approach

| Rank | Variant | Avg | Verdict |
|------|---------|----:|---------|
| 🥇   | **PA2 PrattParser**    | **0.543** | top-down operator precedence, 演算子拡張容易 |
| 🥇   | **PA4 LevelCPort**     | 0.543 | aipl-self-host/level-c/parser.abcl 拡張 (タイ) |
| 3    | PA1 RecursiveDescent   | 0.531 | AIPL function で素直に書く |
| ❌   | PA3 PEG_Generator      | 0.517 | 外部ライブラリ依存、JS-N 限定 |

PA2 と PA4 が同率. PA2 (Pratt) は単純で formula 文法に最適、PA4 (Level-C 流用) は
既存 infra 再利用. **PA4 を選べば「self-host 完了の結果がスプレッドシートに直結」**.

### IT — Integration Topology

| Rank | Variant | Avg | Verdict |
|------|---------|----:|---------|
| 🥇   | **IT2 EventBus**         | **0.566** | publish-subscribe, cell update → 依存 cell + UI が subscribe |
| 2    | IT3 DirectMsgPassing     | 0.563 | actor 同士直接 send, DR-8 spawn-tree 利用 |
| 3    | IT1 StarTopology         | 0.546 | 中央 Coordinator |
| ❌   | IT4 DataflowGraph        | 0.531 | 明示的 dependency graph (Scheduler actor) |

## 推奨実装 6-tuple

```
┌──────────────────────────────────────────────────────────────┐
│ Web Spreadsheet MVP — Implementation Strategy                │
├──────────────────────────────────────────────────────────────┤
│ CA4 HybridSpawn     ── visible eager + off-screen lazy       │
│ FE4 ActorEval       ── each cell actor evals own formula     │
│ P3  DistCheckpoint  ── reuse DR-4 AIPL_DIST_CHECKPOINT_DIR   │
│ R3  LayerComposite  ── grid/content/selection multi-canvas   │
│ PA4 LevelCPort      ── aipl-self-host/level-c/parser を拡張 │
│ IT2 EventBus        ── pub-sub topology                      │
└──────────────────────────────────────────────────────────────┘
```

(PA は PA2 PrattParser でも同率最良)

## 横断的タスクのスコア

| Task | Avg | Note |
|------|----:|------|
| implementability       | 0.814 | 全体的に実装可能 |
| TotalImplCost          | 0.554 | ≈ 2200 LOC レンジ (round 1 の見越し ≤2500 と整合) |
| ThreeRuntimeCoherence  | 0.529 | Py-I + JS-N + browser-abcl の 3 役割分担、まずまず |
| ExistingInfraReuse     | 0.500 | half-and-half — P3 + PA4 + DR-13 + CE-11 で 4-5 件再利用 |
| BackwardCompat         | 0.494 | やや低い — 新 dir / 別 subcommand での opt-in を徹底する必要 |
| paradigm_match         | 0.623 | 既存 paradigm との適合 |

## 既存 AIPL infra の再利用先 (推奨 6-tuple 経由)

| Infra | 利用先 | Reviewer 想定スコア |
|-------|--------|---|
| DR-4 AIPL_DIST_CHECKPOINT_DIR | **P3 DistCheckpoint** で save/restore | ✅ |
| DR-13 actor pool              | **CA4 HybridSpawn** で off-screen cell の spawn 管理 | ✅ |
| CE-11 capability              | formula 評価 sandbox (capability=ad-hoc cell access 制限) | ✅ |
| Level-C parser                | **PA4 LevelCPort** で formula 文法を拡張 | ✅ |
| WebSocket (server.mjs)        | future collab 拡張のための予約 | (S1 では未使用) |
| HMAC URL signing              | ShareLink で sheet 共有 + 改竄防止 | ✅ |
| DR-10 CRDT                    | S1 では使わず、S4/S2 の後続 round で活用 | (予約) |
| DR-11 saga                    | bulk-paste / undo の compensate に活用 | (将来) |

**再利用件数 6** (Level-A eval は FE4 だと不使用、FE3 を選ぶ場合のみ).

## LOC 内訳

| Component | Variant | LOC 見積もり |
|-----------|---------|-------------:|
| CellActor | CA4 HybridSpawn       | 200-300 |
| FormulaEval | FE4 ActorEval       | 300-400 |
| Persistence | P3 DistCheckpoint   |  80-120 |
| Renderer | R3 LayerComposite     | 250-350 |
| Parser | PA4 LevelCPort          | 150-250 |
| Integration | IT2 EventBus        | 150-220 |
| **MVP 合計** |                    | **≈ 1130-1640 LOC** |

(横断的タスク: ShareLink 200-300, ImportExportCSV 100-150 を加えると ~1500-2100 LOC)

Round 1 で見越した ≤2500 LOC レンジに収まる. ImplCostEstimator 0.554 とほぼ整合.

## Round 3 (実装フェーズ) への引継ぎ

1. **`src/python-aipl/samples/spreadsheet/`** または **`src/browser-abcl/spreadsheet/`** を起点
2. 最小 PR: PA4 LevelCPort + FE1 LevelAReuse の組合せで **Hello-Spreadsheet** demo (50 行程度)
3. Round 3 の前半で **CA4 + FE4 + P3** を実装、後半で **R3 + IT2** で UI 統合
4. PA は **PA4 LevelCPort** 推奨 (self-host 完成の結果を直接活用)

## 出力ファイル

- `aice-evolution-v2/out/AIPL_WebSpreadsheet_Impl.report.md` (自動生成)
- `aice-evolution-v2/out/AIPL_WebSpreadsheet_Impl.lineage.json`
- `aice-evolution-v2/out/AIPL_WebSpreadsheet_Impl.elite_map.json`
- `aice-evolution-v2/out/AIPL_WebSpreadsheet_Impl.ranking.json`
