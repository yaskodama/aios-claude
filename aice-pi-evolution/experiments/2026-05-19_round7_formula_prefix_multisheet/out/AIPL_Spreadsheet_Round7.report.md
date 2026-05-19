# AIPL_Spreadsheet_Round7

> Round 6 完了状態 (browser-abcl spreadsheet + node-aipl-server /ws + LWW persist + 50+ functions + CSV/XLSX round-trip + multi-letter cols + peer cursors) を base に、(EQ) 数式プレフィックス `=` 必須化と保存時の formula 文字列 round-trip、(MS) 複数シート + cross-sheet refs、加えて (U14 Undo パネル / F12 マクロ / D5 JSON 全状態 export / C7 Presence / Y4 heatmap) の 7 phase を積み増す.既存 235 assertion + Phase 4 smoke 8/8 は absolute compat floor、新機能は全て opt-in (新 UI 要素・新 endpoint・新メッセージ type).

## 1. 発見された進化軌跡 (best champion lineage)

系譜長: 4 世代分

| step | id | gen | operator | paradigm | type_safety | concurrency_model |
|------|----|-----|----------|----------|-------------|-------------------|
| 0 | `I0001` | 0 | `seed` | BASIC | none | structured |
| 1 | `I0025` | 17 | `crossover:schema_partition_crossover` | BASIC | high | actor_messages |
| 2 | `I0033` | 25 | `mutation:coherent_paradigm_shift` | C | medium | actor_messages |
| 3 | `I0037` | 29 | `crossover:schema_partition_crossover` | C | high | actor_messages |

## 2. 進化方向ベクトル (signed total movement, normalized)

- `type_safety`: +0.75
- `concurrency_model`: -0.25
- `ownership_model`: +0.00

**Lineage 内で新しく現れた (axis, value) ペア**:
- `concurrency_model = actor_messages`
- `type_safety = high`
- `effect_handling = algebraic_effects`
- `paradigm = C`
- `state_representation = enum_state`
- `type_safety = medium`
- `effect_handling = implicit`

## 3. Pareto フロンティア — 未充填セル (top 5 promising gaps)

| descriptor | 隣接セル最高 composite | 距離 | コヒーレント |
|-----------|------------------------|------|--------------|

## 4. ランキング（シナリオ別）

### Scenario: conservative
_重み: trend_alignment=0.45, cross_task_generality=0.2, implementability=0.15, evolvability=0.1, frontier_coverage=0.05, novelty=0.05_

| rank | id | paradigm | composite | Pareto層 | win-rate |
|------|----|----------|-----------|----------|----------|
| 1 | `I0008` | ParallelOOP | 0.694 | 1 | 100% |
| 2 | `I0025` | BASIC | 0.671 | 2 | 80% |
| 3 | `I0037` | C | 0.647 | 3 | 60% |

### Scenario: innovative
_重み: novelty=0.35, frontier_coverage=0.3, evolvability=0.15, trend_alignment=0.05, cross_task_generality=0.1, implementability=0.05_

| rank | id | paradigm | composite | Pareto層 | win-rate |
|------|----|----------|-----------|----------|----------|
| 1 | `I0008` | ParallelOOP | 0.504 | 1 | 100% |
| 2 | `I0025` | BASIC | 0.468 | 2 | 80% |
| 3 | `I0037` | C | 0.433 | 3 | 60% |

### Scenario: general_purpose
_重み: cross_task_generality=0.4, implementability=0.2, trend_alignment=0.15, evolvability=0.1, frontier_coverage=0.1, novelty=0.05_

| rank | id | paradigm | composite | Pareto層 | win-rate |
|------|----|----------|-----------|----------|----------|
| 1 | `I0008` | ParallelOOP | 0.619 | 1 | 100% |
| 2 | `I0025` | BASIC | 0.595 | 2 | 80% |
| 3 | `I0037` | C | 0.572 | 3 | 60% |

## 5. 上位候補の詳細

### I0008  (conservative の1位)
- 遺伝子: `paradigm=ParallelOOP, state_representation=register_int, concurrency_model=actor_messages, type_safety=high, effect_handling=algebraic_effects, ownership_model=none`
- セル: `paradigm=ParallelOOP`
- composite (run-内): 0.649
- 最近傍既存パラダイム: **ParallelOOP**
- 越えている軸: state_representation: symbol_owned -> register_int, ownership_model: borrow_check -> none
- meta-fitness: trend_alignment=0.81, frontier_coverage=0.50, novelty=0.40, evolvability=0.53, cross_task_generality=0.50, implementability=0.87
- タスク別スコア: EQ_FormulaPrefix=0.50, MS_MultipleSheets=0.50, U14_UndoRedoPanel=0.50, F12_MacroNamedOperations=0.50, D5_JSONFullExport=0.50, C7_PresenceIndicator=0.50, Y4_HeatmapChart=0.50, BackwardCompat=0.50, ImplCost=0.50

## 6. 留保 (uncertainty)

シナリオ間で順位が入れ替わる候補は、外的条件次第でいずれの方向にも有力です。単一の正解はなく、本レポートは meta-fitness 重み選択への依存を保持したまま提示しています。
