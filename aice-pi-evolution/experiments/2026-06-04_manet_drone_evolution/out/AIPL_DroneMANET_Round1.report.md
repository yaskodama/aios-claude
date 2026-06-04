# AIPL_DroneMANET_Round1

> drone-hil の現行 MANET 層 (reactive_AODV + range_pruning + hop_count + link_break_detect + on_demand 近傍探索 + sos_priority + partition 時 drop) を seed に、山間部災害避難 UAV スウォーム (M-006) を実機 Xinu+Raspberry-Pi WiFi メッシュ上で運用するという固有条件 — 頻繁なネットワーク分断・UAV の高モビリティ・限られた RAM/CPU/WiFi・SOS フレームの低遅延要求・バッテリ制約 — の下で報われるルーティング設計を MAP-Elites で探索する。各個体は 7 軸の遺伝子 (routing_protocol/buffering_strategy/link_metric/topology_control/mobility_handling/neighbor_discovery/qos_priority) で、reviewer が各評価シナリオへの suitability を 0..1 で採点する。cell_axes=routing_protocol でプロトコル族ごとのベスト設計を archive する。

## 1. 発見された進化軌跡 (best champion lineage)

系譜長: 3 世代分

| step | id | gen | operator | paradigm | type_safety | concurrency_model |
|------|----|-----|----------|----------|-------------|-------------------|
| 0 | `I0004` | 0 | `seed:explicit` | ? | ? | ? |
| 1 | `I0015` | 3 | `crossover:schema_partition_crossover` | ? | ? | ? |
| 2 | `I0019` | 7 | `mutation:axis_resample` | ? | ? | ? |

## 2. 進化方向ベクトル (signed total movement, normalized)

- `link_metric`: +0.52
- `buffering_strategy`: +0.17
- `mobility_handling`: +0.17
- `topology_control`: +0.13
- `qos_priority`: +0.00

**Lineage 内で新しく現れた (axis, value) ペア**:
- `buffering_strategy = store_carry_forward`
- `link_metric = energy_aware`
- `topology_control = clustering`
- `mobility_handling = trajectory_aware`
- `neighbor_discovery = adaptive_rate_hello`

## 3. Pareto フロンティア — 未充填セル (top 5 promising gaps)

| descriptor | 隣接セル最高 composite | 距離 | コヒーレント |
|-----------|------------------------|------|--------------|

## 4. ランキング（シナリオ別）

### Scenario: conservative
_重み: trend_alignment=0.45, cross_task_generality=0.2, implementability=0.15, evolvability=0.1, frontier_coverage=0.05, novelty=0.05_

| rank | id | paradigm | composite | Pareto層 | win-rate |
|------|----|----------|-----------|----------|----------|
| 1 | `I0009` | ? | 0.675 | 1 | 100% |
| 2 | `I0017` | ? | 0.637 | 1 | 71% |
| 3 | `I0019` | ? | 0.616 | 1 | 43% |

### Scenario: innovative
_重み: novelty=0.35, frontier_coverage=0.3, evolvability=0.15, trend_alignment=0.05, cross_task_generality=0.1, implementability=0.05_

| rank | id | paradigm | composite | Pareto層 | win-rate |
|------|----|----------|-----------|----------|----------|
| 1 | `I0009` | ? | 0.821 | 1 | 86% |
| 2 | `I0019` | ? | 0.728 | 1 | 43% |
| 3 | `I0017` | ? | 0.719 | 1 | 86% |

### Scenario: general_purpose
_重み: cross_task_generality=0.4, implementability=0.2, trend_alignment=0.15, evolvability=0.1, frontier_coverage=0.1, novelty=0.05_

| rank | id | paradigm | composite | Pareto層 | win-rate |
|------|----|----------|-----------|----------|----------|
| 1 | `I0009` | ? | 0.651 | 1 | 86% |
| 2 | `I0017` | ? | 0.629 | 1 | 71% |
| 3 | `I0019` | ? | 0.597 | 1 | 43% |

## 5. 上位候補の詳細

### I0009  (conservative の1位)
- 遺伝子: `routing_protocol=spray_and_wait_DTN, buffering_strategy=store_carry_forward, link_metric=energy_aware, topology_control=clustering, mobility_handling=trajectory_aware, neighbor_discovery=beaconless, qos_priority=sos_priority`
- セル: `routing_protocol=spray_and_wait_DTN`
- composite (run-内): 0.668
- 最近傍既存パラダイム: **assembler**
- meta-fitness: trend_alignment=0.65, frontier_coverage=0.68, novelty=1.00, evolvability=1.00, cross_task_generality=0.54, implementability=0.60
- タスク別スコア: PartitionTolerance=0.43, HighMobilityResilience=0.70, SwarmScalability=0.50, EmbeddedFeasibility=0.50, SOSLatency=0.67, EnergyEfficiency=0.73, AODVCompatibility=0.23

## 6. 留保 (uncertainty)

シナリオ間で順位が入れ替わる候補は、外的条件次第でいずれの方向にも有力です。単一の正解はなく、本レポートは meta-fitness 重み選択への依存を保持したまま提示しています。
