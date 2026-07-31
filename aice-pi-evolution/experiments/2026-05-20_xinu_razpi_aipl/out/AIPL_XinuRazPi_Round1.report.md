# AIPL_XinuRazPi_Round1

> AIPL を Embedded Xinu / Raspberry Pi 系 (arm-qemu + 実 Pi) で進化させる.Round 0 (= 既存 src/aipl2c.ml --xinu + gen_program_xinu + 3 サンプル + xinu-raz) を base に、(R) regression 修復、(P) パフォーマンス/スケジューラ、(F) AIPL 機能拡張 (Xinu C ランタイム上)、(G) GUI/I/O 拡張、(N) 分散/ネットワーク の 5 軸で進化.全 phase は (1) aipl2c の .aipl → C 翻訳 ✅ + (2) Xinu kernel build ✅ + (3) QEMU で起動成功 ✅ の 3 段ゲートを通過すること.

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
- タスク別スコア: R0_RestoreSampleTyping=0.50, R1_SmokeAutomation=0.50, P1_ActorAsXinuThread=0.50, P2_PriorityClassesAndTimeslice=0.50, P3_LockFreeMailbox=0.50, P4_SchedulingVisualizer=0.50, F1_P3DistCheckpoint=0.50, F2_LWWCellSemantics=0.50, F3_EffectAndTypeParity=0.50, F4_StringsAndArrays=0.50, G1_FramebufferPrimitives=0.50, G2_BitmapFontText=0.50, G3_MouseEventDispatch=0.50, G4_RealPiGPIO=0.50, G5_ImageBitmapLoad=0.50, N1_TCPIPStack=0.50, N2_WSBridgeToBrowser=0.50, N3_MultiPiActorCluster=0.50, N4_mDNSDiscovery=0.50, R_BackwardCompat=0.50, ImplCost=0.50

## 6. 留保 (uncertainty)

シナリオ間で順位が入れ替わる候補は、外的条件次第でいずれの方向にも有力です。単一の正解はなく、本レポートは meta-fitness 重み選択への依存を保持したまま提示しています。
