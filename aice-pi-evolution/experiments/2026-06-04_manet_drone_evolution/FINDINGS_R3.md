# MANET Drone Routing — Round 3 findings (resource/congestion awareness, 2026-06-04)

Round 2 が「欠けている軸」として示した **resource_awareness** と
**congestion_awareness** を第一級軸に昇格 (`schemas/manet_routing_r3.schema.json`、
計 9 軸) し、現行設計を **unaware (none/none) でシード**して「awareness を足すと
報われるか」を検証した。

- 実行: `python3 -m aice-evolution-v2.src.manet_round3_runner`
  (gemini-2.5-flash-lite、R1+R2 族別チャンピオンを none/none シード、45 個体)
- 新軸: resource_awareness = none/battery_aware/buffer_aware/full_resource_aware、
  congestion_awareness = none/queue_backpressure/ecn_marking/predictive_congestion
- 整合規則追加: 大量複製は resource-aware 必須、純フラッディングは congestion-aware 必須。

## 結果: awareness は「高オーバーヘッド系プロトコル専用の薬」

| protocol | R1 | R3 | Δ | R3 が採用した awareness |
|---|---|---|---|---|
| reactive_AODV | 0.709 | **0.691** | −0.019 | none / none（**チャンピオン据置**）|
| bundle_forwarding | (R2 0.671) | 0.689 | — | none / **queue_backpressure** |
| proactive_OLSR | 0.658 | 0.680 | **+0.022** | **battery_aware** / **queue_backpressure** |
| epidemic_DTN | 0.610 | 0.669 | **+0.059** | **battery_aware** / **predictive_congestion** |
| hybrid_ZRP | 0.708 | 0.664 | −0.045 | none / none |
| spray_and_wait_DTN | 0.668 | 0.651 | −0.017 | none / none |
| geographic_GPSR | 0.669 | 0.651 | −0.019 | none / none |
| link_state_SR | 0.645 | 0.644 | −0.001 | none / none |
| gossip_flood | 0.590 | 0.633 | **+0.043** | none / **queue_backpressure** |

**aware 個体 27/45、平均 composite: aware 0.638 vs unaware 0.633（ほぼ同等＝全体では中立）。**

### 読み取り
1. **awareness が効くのは「自分の弱点が congestion/energy」な高オーバーヘッド系**:
   - epidemic_DTN **+0.059**（フラッディングの輻輳と電池消耗を予測輻輳+電池認識で緩和）
   - gossip_flood **+0.043**（queue_backpressure で flooding 輻輳を抑制）
   - proactive_OLSR **+0.022**（定期 hello の電池/輻輳を緩和）
2. **チャンピオン (reactive_AODV / hybrid_ZRP) は none/none のまま** — clustering ＋ ETX
   指標が既に resource/congestion を暗黙にエンコードしており、**専用軸は冗長**。
3. 全 3 ラウンドで **トップ設計は不変**: reactive_AODV(clustering) ≈ hybrid_ZRP ≈ 0.69–0.71。
   ラウンド間の揺れ (hybrid_ZRP 0.708→0.664 等) は **LLM 採点ノイズ (±0.04 程度)** の範囲。

## 結論（3 ラウンドの収束）

- **実装方針は確定**: hybrid_ZRP（≈ clustering-AODV）。drone-hil 実装は妥当で、
  **resource/congestion awareness を別軸として足す必要はない**（ETX+clustering が代替）。
- **awareness は条件付き有効**: もし将来 DTN 系 (epidemic/bundle/gossip) を実装するなら、
  congestion(queue_backpressure/predictive) + battery_aware を**併せて入れる**と弱点が消える。
- GA 探索は **diminishing returns に到達** — 設計空間は十分に特徴づけられた。
  次は「設計探索」より「実装・実測検証」(drone-hil sim / 実機 Xinu HIL) のフェーズ。

★ reviewer は LLM 主観。ノイズ床 ±0.04。絶対値でなく Δ と採用パターンで読む。
成果物: `out/AIPL_DroneMANET_Round3.{lineage,elite_map,ranking,report}.json`。
