# AIPL_DroneMANET_Round3

> drone-hil の現行 MANET 層 (reactive_AODV + range_pruning + hop_count + link_break_detect + on_demand 近傍探索 + sos_priority + partition 時 drop) を seed に、山間部災害避難 UAV スウォーム (M-006) を実機 Xinu+Raspberry-Pi WiFi メッシュ上で運用するという固有条件 — 頻繁なネットワーク分断・UAV の高モビリティ・限られた RAM/CPU/WiFi・SOS フレームの低遅延要求・バッテリ制約 — の下で報われるルーティング設計を MAP-Elites で探索する。各個体は 7 軸の遺伝子 (routing_protocol/buffering_strategy/link_metric/topology_control/mobility_handling/neighbor_discovery/qos_priority) で、reviewer が各評価シナリオへの suitability を 0..1 で採点する。cell_axes=routing_protocol でプロトコル族ごとのベスト設計を archive する。

## 1. 発見された進化軌跡 (best champion lineage)

系譜長: 5 世代分

| step | id | gen | operator | paradigm | type_safety | concurrency_model |
|------|----|-----|----------|----------|-------------|-------------------|
| 0 | `I0012` | 0 | `seed` | ? | ? | ? |
| 1 | `I0014` | 1 | `mutation:axis_resample` | ? | ? | ? |
| 2 | `I0028` | 15 | `crossover:schema_partition_crossover` | ? | ? | ? |
| 3 | `I0029` | 16 | `mutation:axis_resample` | ? | ? | ? |
| 4 | `I0042` | 29 | `mutation:axis_resample` | ? | ? | ? |

## 2. 進化方向ベクトル (signed total movement, normalized)

- `qos_priority`: -0.48
- `link_metric`: +0.29
- `topology_control`: -0.24
- `buffering_strategy`: +0.00
- `mobility_handling`: +0.00
- `resource_awareness`: +0.00
- `congestion_awareness`: +0.00

**Lineage 内で新しく現れた (axis, value) ペア**:
- `topology_control = range_pruning`
- `qos_priority = none`
- `congestion_awareness = predictive_congestion`
- `link_metric = airtime_load`

## 3. Pareto フロンティア — 未充填セル (top 5 promising gaps)

| descriptor | 隣接セル最高 composite | 距離 | コヒーレント |
|-----------|------------------------|------|--------------|

## 4. ランキング（シナリオ別）

### Scenario: conservative
_重み: trend_alignment=0.45, cross_task_generality=0.2, implementability=0.15, evolvability=0.1, frontier_coverage=0.05, novelty=0.05_

| rank | id | paradigm | composite | Pareto層 | win-rate |
|------|----|----------|-----------|----------|----------|
| 1 | `I0006` | ? | 0.574 | 1 | 75% |
| 2 | `I0030` | ? | 0.571 | 1 | 50% |
| 3 | `I0042` | ? | 0.548 | 1 | 38% |

### Scenario: innovative
_重み: novelty=0.35, frontier_coverage=0.3, evolvability=0.15, trend_alignment=0.05, cross_task_generality=0.1, implementability=0.05_

| rank | id | paradigm | composite | Pareto層 | win-rate |
|------|----|----------|-----------|----------|----------|
| 1 | `I0006` | ? | 0.684 | 1 | 75% |
| 2 | `I0034` | ? | 0.683 | 1 | 62% |
| 3 | `I0030` | ? | 0.678 | 1 | 50% |

### Scenario: general_purpose
_重み: cross_task_generality=0.4, implementability=0.2, trend_alignment=0.15, evolvability=0.1, frontier_coverage=0.1, novelty=0.05_

| rank | id | paradigm | composite | Pareto層 | win-rate |
|------|----|----------|-----------|----------|----------|
| 1 | `I0030` | ? | 0.577 | 1 | 88% |
| 2 | `I0006` | ? | 0.555 | 1 | 62% |
| 3 | `I0034` | ? | 0.545 | 1 | 62% |

## 5. 上位候補の詳細

### I0006  (conservative の1位)
- 遺伝子: `routing_protocol=spray_and_wait_DTN, buffering_strategy=store_carry_forward, link_metric=energy_aware, topology_control=clustering, mobility_handling=trajectory_aware, neighbor_discovery=beaconless, qos_priority=sos_priority, resource_awareness=none, congestion_awareness=none`
- セル: `routing_protocol=spray_and_wait_DTN`
- composite (run-内): 0.651
- 最近傍既存パラダイム: **assembler**
- meta-fitness: trend_alignment=0.57, frontier_coverage=0.49, novelty=1.00, evolvability=0.53, cross_task_generality=0.49, implementability=0.60
- タスク別スコア: PartitionTolerance=0.43, HighMobilityResilience=0.73, SwarmScalability=0.37, EmbeddedFeasibility=0.53, SOSLatency=0.43, EnergyEfficiency=0.73, AODVCompatibility=0.23

### I0030  (general_purpose の1位)
- 遺伝子: `routing_protocol=bundle_forwarding, buffering_strategy=store_carry_forward, link_metric=energy_aware, topology_control=clustering, mobility_handling=trajectory_aware, neighbor_discovery=beaconless, qos_priority=sos_priority, resource_awareness=none, congestion_awareness=queue_backpressure`
- セル: `routing_protocol=bundle_forwarding`
- composite (run-内): 0.689
- 最近傍既存パラダイム: **assembler**
- meta-fitness: trend_alignment=0.56, frontier_coverage=0.54, novelty=1.00, evolvability=0.33, cross_task_generality=0.59, implementability=0.60
- タスク別スコア: PartitionTolerance=0.57, HighMobilityResilience=0.70, SwarmScalability=0.56, EmbeddedFeasibility=0.56, SOSLatency=0.56, EnergyEfficiency=0.73, AODVCompatibility=0.43

## 6. 留保 (uncertainty)

シナリオ間で順位が入れ替わる候補は、外的条件次第でいずれの方向にも有力です。単一の正解はなく、本レポートは meta-fitness 重み選択への依存を保持したまま提示しています。
