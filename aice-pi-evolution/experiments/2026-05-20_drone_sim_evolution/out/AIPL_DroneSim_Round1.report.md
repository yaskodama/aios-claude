# AIPL_DroneSim_Round1

> Round 0 の M-006 再現シミュレータ (drone_sim_v0.html) を seed に、Direction A (論文課題の解消) + Direction B (機能拡張) + Direction C (AIPL/abclc 統合) + Direction D (現実モデル) の 4 軸で進化させる. 既存挙動 (UAV1 巡回 + UAV2 誘導 + 8 試行制限 + 表 1 初期値) は absolute compat floor、新機能は全て opt-in (toggle/別ボタン/別パネル). 各 phase は HTML 1 ファイル + Puppeteer smoke のセットで commit.

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
- タスク別スコア: A1_AlphaBetaGammaSlider=0.50, A2_UAV1SweepOptimization=0.50, A3_StatisticsPanel=0.50, A4_ScenarioSelector=0.50, B1_NDrones=0.50, B2_SecondaryDisaster=0.50, B3_SOSBroadcast=0.50, B4_BatteryWind=0.50, C1_UAVAsAIPLActor=0.50, C2_MultiCommanderWS=0.50, D1_RealTerrainTile=0.50, D2_LearnedRouting=0.50, D3_SurvivorMobility=0.50, R0_BackwardCompat=0.50, ImplCost=0.50

## 6. 留保 (uncertainty)

シナリオ間で順位が入れ替わる候補は、外的条件次第でいずれの方向にも有力です。単一の正解はなく、本レポートは meta-fitness 重み選択への依存を保持したまま提示しています。
