# MANET Drone Routing — Round 1 findings (2026-06-04)

GA 進化パイプライン (`aice → ga.json → MAP-Elites`) で、`~/projects/drone-hil`
の MANET ルーティング層の **設計空間** を探索した結果。

- gene schema: `aice-evolution-v2/schemas/manet_routing.schema.json` (7 軸)
- 設計記述: `AIPL_DroneMANET_Round1.aice`
- 実行: `python3 -m aice-evolution-v2.src.manet_round1_runner`
  (gemini-2.5-flash-lite reviewer ×3、全 8 プロトコル族をシード注入)
- 個体数 40 / 全 8 セル充填 / reviewer: MANET研究者・Xinu実機エンジニア・災害対応オペレータ

## プロトコル族別チャンピオン (composite)

| composite | protocol | 特徴遺伝子 | 強い軸 |
|---|---|---|---|
| **0.709** | reactive_AODV (進化版) | drop + hop_count + **clustering** | AODVCompat 0.77 |
| **0.708** | hybrid_ZRP | custody + etx + clustering + periodic_hello | Partition/Swarm/Embed/SOS 全て 0.70-0.73 (最バランス) |
| 0.669 | geographic_GPSR | scf + energy_aware + trajectory_aware | HighMobility |
| 0.668 | spray_and_wait_DTN | scf + energy_aware + beaconless | Energy 0.73 |
| 0.658 | proactive_OLSR | etx + backbone_cds + periodic_hello | — |
| 0.645 | link_state_SR | custody + etx + clustering | — |
| 0.610 | epidemic_DTN | scf + rtt + backbone_cds | (embedded で減点) |
| 0.590 | gossip_flood | scf + energy_aware | (最弱) |

## タスク次元リーダー

- PartitionTolerance / SwarmScalability / EmbeddedFeasibility / SOSLatency → **hybrid_ZRP** (0.70-0.73)
- HighMobilityResilience → geographic_GPSR
- EnergyEfficiency → spray_and_wait_DTN (energy_aware + beaconless)
- AODVCompatibility → reactive_AODV

## ★ 最重要: ベースライン (現行 drone-hil) vs 進化版 reactive_AODV

現行実装 `reactive_AODV + drop + hop_count + range_pruning + link_break + on_demand + sos`
(composite 0.678) から、進化が見つけた唯一の差は **1 軸だけ**:

```
topology_control:  range_pruning  ->  clustering   (composite 0.678 -> 0.709)
```

per-task デルタ:
- PartitionTolerance  0.56 → 0.73  (**+0.17**)
- SwarmScalability    0.43 → 0.53  (+0.10)
- SOSLatency          0.53 → 0.63  (+0.10)
- AODVCompatibility   0.73 → 0.77  (+0.04, 既存 RREQ/RREP 可視化と互換のまま)
- EnergyEfficiency    0.40 → 0.37  (-0.03, わずかに悪化)

→ **既存 AODV 可視化・実機ブリッジを壊さずに、レンジ枝刈りをクラスタリング
(cluster-head / CDS バックボーン) へ替えるだけで分断耐性・スケール性・SOS 遅延が
改善する**、という低コスト高レバレッジの進化方向。

## trend vector (現行からどちらへ進化すると報われるか)

```
link_metric        +0.52   hop_count -> etx_quality / energy_aware (賢いリンク指標)
buffering_strategy +0.17   drop -> store_carry_forward (軽い DTN 化)
mobility_handling  +0.17   link_break_detect -> predictive_mobility
topology_control   +0.13   range_pruning -> clustering
```

## scenario ランキング (meta-fitness: trend/novelty/generality)

conservative / innovative / general_purpose の **3 シナリオ全てで #1 = spray_and_wait_DTN
(I0009)** — novelty/energy/trend 整合が高い「探索的ベット」。raw composite では
中位だが、現行から最も遠い設計として meta-fitness が高評価。

## 推奨 (次に実装すべき方向)

1. **即効・低コスト (AODV 互換維持)**: drone-hil sim の MANET 層で
   `range_pruning → clustering` を実装。リレー R1/R2/R3 を cluster-head 化し
   RREQ フラッディングをクラスタ内にスコープ。既存 RREQ/RREP 可視化はそのまま。
2. **次世代ベット (要書き換え)**: **hybrid_ZRP** — ゾーン内 proactive + ゾーン間
   reactive、custody_transfer バッファ、ETX 指標、clustering。全タスク最バランス。
   trend vector とも一致。
3. **探索的**: spray_and_wait_DTN (省電力 + 分断耐性、ただし embedded/AODV互換は弱)。

## 実装状況 (2026-06-04)

→ **hybrid_ZRP を `~/projects/drone-hil/index.html` に実装済**（推奨2の次世代ベット）。
右上 `Routing: ZRP/AODV` トグルで AODV ベースラインと比較可能。ゾーン内 proactive
(IARP) ＋ ゾーン間 bordercast (IERP)、ETX 指標、custody_transfer バッファを実装。
検証 `/tmp/_ppt/_zrp.mjs` で 5/5 assertion green（intra-zone 0-query / bordercast
scoped query / custody hold→deliver / 両モード runtime error 無し）。

## ★ 注意 (結果の信頼性)

reviewer は LLM (gemini-2.5-flash-lite) の主観スコアであり、**実シミュレーション
測定ではない**。対照テストで差別化と妥当性 (DTN=partition高/embedded低 等) は確認済だが、
絶対値は目安。真の検証は候補設計を sim/HIL に実装して配送率・遅延を実測すること。
特に AODV+clustering の +0.17 は機構的に妥当だが、要実測。
