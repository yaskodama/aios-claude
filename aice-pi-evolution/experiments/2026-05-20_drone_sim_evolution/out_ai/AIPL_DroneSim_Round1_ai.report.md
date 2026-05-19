# AIPL_DroneSim_Round1_ai

> Round 0 の M-006 再現シミュレータ (drone_sim_v0.html) を seed に、Direction A (論文課題の解消) + Direction B (機能拡張) + Direction C (AIPL/abclc 統合) + Direction D (現実モデル) の 4 軸で進化させる. 既存挙動 (UAV1 巡回 + UAV2 誘導 + 8 試行制限 + 表 1 初期値) は absolute compat floor、新機能は全て opt-in (toggle/別ボタン/別パネル). 各 phase は HTML 1 ファイル + Puppeteer smoke のセットで commit.

## 1. 発見された進化軌跡 (best champion lineage)

系譜長: 2 世代分

| step | id | gen | operator | paradigm | type_safety | concurrency_model |
|------|----|-----|----------|----------|-------------|-------------------|
| 0 | `I0003` | 0 | `seed` | C | high | threads_locks |
| 1 | `I0009` | 5 | `mutation:coherent_paradigm_shift` | ParallelOOP | high | actor_messages |

## 2. 進化方向ベクトル (signed total movement, normalized)

- `concurrency_model`: +1.00
- `type_safety`: +0.00
- `ownership_model`: +0.00

**Lineage 内で新しく現れた (axis, value) ペア**:
- `paradigm = ParallelOOP`
- `state_representation = symbol_owned`
- `concurrency_model = actor_messages`

## 3. Pareto フロンティア — 未充填セル (top 5 promising gaps)

| descriptor | 隣接セル最高 composite | 距離 | コヒーレント |
|-----------|------------------------|------|--------------|
| paradigm=assembler | 0.32 | 1 | yes |

## 4. ランキング（シナリオ別）

### Scenario: conservative
_重み: trend_alignment=0.45, cross_task_generality=0.2, implementability=0.15, evolvability=0.1, frontier_coverage=0.05, novelty=0.05_

| rank | id | paradigm | composite | Pareto層 | win-rate |
|------|----|----------|-----------|----------|----------|
| 1 | `I0001` | BASIC | 0.459 | 1 | 67% |
| 2 | `I0003` | C | 0.414 | 1 | 100% |
| 3 | `I0009` | ParallelOOP | 0.395 | 1 | 0% |

### Scenario: innovative
_重み: novelty=0.35, frontier_coverage=0.3, evolvability=0.15, trend_alignment=0.05, cross_task_generality=0.1, implementability=0.05_

| rank | id | paradigm | composite | Pareto層 | win-rate |
|------|----|----------|-----------|----------|----------|
| 1 | `I0003` | C | 0.565 | 1 | 33% |
| 2 | `I0001` | BASIC | 0.428 | 1 | 0% |
| 3 | `I0009` | ParallelOOP | 0.384 | 1 | 100% |

### Scenario: general_purpose
_重み: cross_task_generality=0.4, implementability=0.2, trend_alignment=0.15, evolvability=0.1, frontier_coverage=0.1, novelty=0.05_

| rank | id | paradigm | composite | Pareto層 | win-rate |
|------|----|----------|-----------|----------|----------|
| 1 | `I0003` | C | 0.385 | 1 | 67% |
| 2 | `I0001` | BASIC | 0.364 | 1 | 0% |
| 3 | `I0009` | ParallelOOP | 0.347 | 1 | 100% |

## 5. 上位候補の詳細

### I0001  (conservative の1位)
- 遺伝子: `paradigm=BASIC, state_representation=register_int, concurrency_model=structured, type_safety=none, effect_handling=capability, ownership_model=none`
- セル: `paradigm=BASIC`
- composite (run-内): 0.302
- 最近傍既存パラダイム: **assembler**
- 越えている軸: concurrency_model: none -> structured, effect_handling: implicit -> capability
- meta-fitness: trend_alignment=0.50, frontier_coverage=0.33, novelty=0.40, evolvability=0.83, cross_task_generality=0.00, implementability=0.76
- タスク別スコア: A1_AlphaBetaGammaSlider=0.00, A2_UAV1SweepOptimization=0.00, A3_StatisticsPanel=0.00, A4_ScenarioSelector=0.00, B1_NDrones=0.00, B2_SecondaryDisaster=0.00, B3_SOSBroadcast=0.00, B4_BatteryWind=0.00, C1_UAVAsAIPLActor=0.00, C2_MultiCommanderWS=0.00, D1_RealTerrainTile=0.00, D2_LearnedRouting=0.00, D3_SurvivorMobility=0.00, R0_BackwardCompat=0.00, ImplCost=0.00

### I0003  (innovative の1位)
- 遺伝子: `paradigm=C, state_representation=register_int, concurrency_model=threads_locks, type_safety=high, effect_handling=algebraic_effects, ownership_model=rc`
- セル: `paradigm=C`
- composite (run-内): 0.308
- 最近傍既存パラダイム: **Java_OOP**
- 越えている軸: state_representation: enum_state -> register_int, effect_handling: implicit -> algebraic_effects, ownership_model: gc -> rc
- meta-fitness: trend_alignment=0.31, frontier_coverage=0.50, novelty=0.60, evolvability=1.00, cross_task_generality=0.00, implementability=0.79
- タスク別スコア: A1_AlphaBetaGammaSlider=0.00, A2_UAV1SweepOptimization=0.00, A3_StatisticsPanel=0.00, A4_ScenarioSelector=0.00, B1_NDrones=0.00, B2_SecondaryDisaster=0.00, B3_SOSBroadcast=0.00, B4_BatteryWind=0.00, C1_UAVAsAIPLActor=0.00, C2_MultiCommanderWS=0.00, D1_RealTerrainTile=0.00, D2_LearnedRouting=0.00, D3_SurvivorMobility=0.00, R0_BackwardCompat=0.00, ImplCost=0.00

## 6. 留保 (uncertainty)

シナリオ間で順位が入れ替わる候補は、外的条件次第でいずれの方向にも有力です。単一の正解はなく、本レポートは meta-fitness 重み選択への依存を保持したまま提示しています。
