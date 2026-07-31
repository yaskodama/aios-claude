# AIPL_XinuRazPi_Round1_ai

> AIPL を Embedded Xinu / Raspberry Pi 系 (arm-qemu + 実 Pi) で進化させる.Round 0 (= 既存 src/aipl2c.ml --xinu + gen_program_xinu + 3 サンプル + xinu-raz) を base に、(R) regression 修復、(P) パフォーマンス/スケジューラ、(F) AIPL 機能拡張 (Xinu C ランタイム上)、(G) GUI/I/O 拡張、(N) 分散/ネットワーク の 5 軸で進化.全 phase は (1) aipl2c の .aipl → C 翻訳 ✅ + (2) Xinu kernel build ✅ + (3) QEMU で起動成功 ✅ の 3 段ゲートを通過すること.

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
- タスク別スコア: R0_RestoreSampleTyping=0.00, R1_SmokeAutomation=0.00, P1_ActorAsXinuThread=0.00, P2_PriorityClassesAndTimeslice=0.00, P3_LockFreeMailbox=0.00, P4_SchedulingVisualizer=0.00, F1_P3DistCheckpoint=0.00, F2_LWWCellSemantics=0.00, F3_EffectAndTypeParity=0.00, F4_StringsAndArrays=0.00, G1_FramebufferPrimitives=0.00, G2_BitmapFontText=0.00, G3_MouseEventDispatch=0.00, G4_RealPiGPIO=0.00, G5_ImageBitmapLoad=0.00, N1_TCPIPStack=0.00, N2_WSBridgeToBrowser=0.00, N3_MultiPiActorCluster=0.00, N4_mDNSDiscovery=0.00, R_BackwardCompat=0.00, ImplCost=0.00

### I0003  (innovative の1位)
- 遺伝子: `paradigm=C, state_representation=register_int, concurrency_model=threads_locks, type_safety=high, effect_handling=algebraic_effects, ownership_model=rc`
- セル: `paradigm=C`
- composite (run-内): 0.308
- 最近傍既存パラダイム: **Java_OOP**
- 越えている軸: state_representation: enum_state -> register_int, effect_handling: implicit -> algebraic_effects, ownership_model: gc -> rc
- meta-fitness: trend_alignment=0.31, frontier_coverage=0.50, novelty=0.60, evolvability=1.00, cross_task_generality=0.00, implementability=0.79
- タスク別スコア: R0_RestoreSampleTyping=0.00, R1_SmokeAutomation=0.00, P1_ActorAsXinuThread=0.00, P2_PriorityClassesAndTimeslice=0.00, P3_LockFreeMailbox=0.00, P4_SchedulingVisualizer=0.00, F1_P3DistCheckpoint=0.00, F2_LWWCellSemantics=0.00, F3_EffectAndTypeParity=0.00, F4_StringsAndArrays=0.00, G1_FramebufferPrimitives=0.00, G2_BitmapFontText=0.00, G3_MouseEventDispatch=0.00, G4_RealPiGPIO=0.00, G5_ImageBitmapLoad=0.00, N1_TCPIPStack=0.00, N2_WSBridgeToBrowser=0.00, N3_MultiPiActorCluster=0.00, N4_mDNSDiscovery=0.00, R_BackwardCompat=0.00, ImplCost=0.00

## 6. 留保 (uncertainty)

シナリオ間で順位が入れ替わる候補は、外的条件次第でいずれの方向にも有力です。単一の正解はなく、本レポートは meta-fitness 重み選択への依存を保持したまま提示しています。
