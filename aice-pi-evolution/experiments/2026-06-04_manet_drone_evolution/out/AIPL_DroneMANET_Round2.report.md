# AIPL_DroneMANET_Round2

> drone-hil の現行 MANET 層 (reactive_AODV + range_pruning + hop_count + link_break_detect + on_demand 近傍探索 + sos_priority + partition 時 drop) を seed に、山間部災害避難 UAV スウォーム (M-006) を実機 Xinu+Raspberry-Pi WiFi メッシュ上で運用するという固有条件 — 頻繁なネットワーク分断・UAV の高モビリティ・限られた RAM/CPU/WiFi・SOS フレームの低遅延要求・バッテリ制約 — の下で報われるルーティング設計を MAP-Elites で探索する。各個体は 7 軸の遺伝子 (routing_protocol/buffering_strategy/link_metric/topology_control/mobility_handling/neighbor_discovery/qos_priority) で、reviewer が各評価シナリオへの suitability を 0..1 で採点する。cell_axes=routing_protocol でプロトコル族ごとのベスト設計を archive する。

## 1. 発見された進化軌跡 (best champion lineage)

系譜長: 5 世代分

| step | id | gen | operator | paradigm | type_safety | concurrency_model |
|------|----|-----|----------|----------|-------------|-------------------|
| 0 | `I0009` | 0 | `seed` | ? | ? | ? |
| 1 | `I0013` | 1 | `crossover:axis_uniform_crossover` | ? | ? | ? |
| 2 | `I0022` | 10 | `crossover:axis_uniform_crossover` | ? | ? | ? |
| 3 | `I0028` | 16 | `mutation:axis_resample` | ? | ? | ? |
| 4 | `I0030` | 18 | `mutation:llm_proposal` | ? | ? | ? |

## 2. 進化方向ベクトル (signed total movement, normalized)

- `link_metric`: -1.00
- `buffering_strategy`: +0.00
- `topology_control`: +0.00
- `mobility_handling`: +0.00
- `qos_priority`: +0.00

**Lineage 内で新しく現れた (axis, value) ペア**:
- `neighbor_discovery = adaptive_rate_hello`
- `link_metric = etx_quality`
- `resource_awareness = None`
- `neighbor_discovery = on_demand`
- `routing_protocol = bundle_forwarding`

## 3. Pareto フロンティア — 未充填セル (top 5 promising gaps)

| descriptor | 隣接セル最高 composite | 距離 | コヒーレント |
|-----------|------------------------|------|--------------|

## 4. ランキング（シナリオ別）

### Scenario: conservative
_重み: trend_alignment=0.45, cross_task_generality=0.2, implementability=0.15, evolvability=0.1, frontier_coverage=0.05, novelty=0.05_

| rank | id | paradigm | composite | Pareto層 | win-rate |
|------|----|----------|-----------|----------|----------|
| 1 | `I0001` | ? | 0.505 | 1 | 100% |
| 2 | `I0030` | ? | 0.459 | 1 | 25% |
| 3 | `I0028` | ? | 0.458 | 1 | 38% |

### Scenario: innovative
_重み: novelty=0.35, frontier_coverage=0.3, evolvability=0.15, trend_alignment=0.05, cross_task_generality=0.1, implementability=0.05_

| rank | id | paradigm | composite | Pareto層 | win-rate |
|------|----|----------|-----------|----------|----------|
| 1 | `I0002` | ? | 0.728 | 1 | 38% |
| 2 | `I0028` | ? | 0.692 | 1 | 62% |
| 3 | `I0027` | ? | 0.686 | 1 | 88% |

### Scenario: general_purpose
_重み: cross_task_generality=0.4, implementability=0.2, trend_alignment=0.15, evolvability=0.1, frontier_coverage=0.1, novelty=0.05_

| rank | id | paradigm | composite | Pareto層 | win-rate |
|------|----|----------|-----------|----------|----------|
| 1 | `I0002` | ? | 0.556 | 1 | 50% |
| 2 | `I0003` | ? | 0.544 | 1 | 38% |
| 3 | `I0030` | ? | 0.539 | 1 | 38% |

## 5. 上位候補の詳細

### I0001  (conservative の1位)
- 遺伝子: `routing_protocol=reactive_AODV, buffering_strategy=drop_on_partition, link_metric=hop_count, topology_control=clustering, mobility_handling=link_break_detect, neighbor_discovery=on_demand, qos_priority=sos_priority`
- セル: `routing_protocol=reactive_AODV`
- composite (run-内): 0.701
- 最近傍既存パラダイム: **assembler**
- meta-fitness: trend_alignment=0.50, frontier_coverage=0.28, novelty=1.00, evolvability=0.06, cross_task_generality=0.60, implementability=0.60
- タスク別スコア: PartitionTolerance=0.70, HighMobilityResilience=0.73, SwarmScalability=0.46, EmbeddedFeasibility=0.53, SOSLatency=0.60, EnergyEfficiency=0.40, AODVCompatibility=0.77

### I0002  (innovative の1位)
- 遺伝子: `routing_protocol=proactive_OLSR, buffering_strategy=drop_on_partition, link_metric=etx_quality, topology_control=backbone_cds, mobility_handling=link_break_detect, neighbor_discovery=periodic_hello, qos_priority=sos_priority`
- セル: `routing_protocol=proactive_OLSR`
- composite (run-内): 0.672
- 最近傍既存パラダイム: **assembler**
- meta-fitness: trend_alignment=0.15, frontier_coverage=0.45, novelty=1.00, evolvability=1.00, cross_task_generality=0.55, implementability=0.60
- タスク別スコア: PartitionTolerance=0.53, HighMobilityResilience=0.70, SwarmScalability=0.56, EmbeddedFeasibility=0.53, SOSLatency=0.73, EnergyEfficiency=0.36, AODVCompatibility=0.40

## 5b. Phase 9 — 動的に発見された軸 / 値

**新規 axis (LLM が提案):**
- `resource_awareness` (許容値: low_power, limited_resource, optimized_resource)
- `congestion_awareness` (許容値: low, medium, high)

**既存 axis に追加された新値:**
- `routing_protocol`: bundle_forwarding

## 6. 留保 (uncertainty)

シナリオ間で順位が入れ替わる候補は、外的条件次第でいずれの方向にも有力です。単一の正解はなく、本レポートは meta-fitness 重み選択への依存を保持したまま提示しています。
