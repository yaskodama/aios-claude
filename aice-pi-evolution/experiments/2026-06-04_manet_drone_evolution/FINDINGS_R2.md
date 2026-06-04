# MANET Drone Routing — Round 2 findings (open-axes discovery, 2026-06-04)

Round 1 ([FINDINGS.md](./FINDINGS.md)) explored a curated 8-protocol space and
判定 hybrid_ZRP / clustering-AODV をチャンピオンに。Round 2 は **open_axes 進化**:
LLM proposer が **新しい routing_protocol 値**と**全く新しい設計軸**を提案できる。

- 実行: `python3 -m aice-evolution-v2.src.manet_round2_runner`
  (gemini-2.5-flash-lite、Round 1 の族別チャンピオンをシード、42 個体)
- ★ proposer は元々プログラミング言語設計用なので **MANET 文脈に monkeypatch**
  (災害救助 MANET 研究者 persona + routing 文脈プロンプト)。
- ★ `llm_proposal` は `SPECULATIVE_VALUES` に**ある軸しか**新値提案しない仕様
  だったので、MANET 7 軸をそのゲートに登録して新値提案を有効化。

## 結果

**チャンピオンは Round 1 と不変** — open-axes でも誰も超えられず:
| composite | protocol |
|---|---|
| 0.704 | hybrid_ZRP |
| 0.701 | reactive_AODV (clustering) |
| 0.685 | geographic_GPSR |
| 0.672 | proactive_OLSR |
| **0.671** | **bundle_forwarding ← NEW (LLM 発見)** |
| 0.668 | link_state_SR |
| 0.666 | spray_and_wait_DTN |
| 0.655 | epidemic_DTN |
| 0.644 | gossip_flood |

### 発見1: 新プロトコル `bundle_forwarding`（DTN Bundle Protocol / BPv7 相当）
genome: `store_carry_forward + etx_quality + clustering + trajectory_aware + on_demand + sos_priority`、composite **0.671**。
- 強み: EnergyEfficiency 0.70・全タスク 0.56–0.70 と均衡。
- 弱み: **AODVCompatibility 0.27**（純 DTN ゆえ既存 RREQ 可視化と乖離）。
- 位置づけ: epidemic/gossip DTN より上、spray_and_wait と同等。分断が支配的な
  運用なら候補になるが、**hybrid_ZRP/AODV は超えない** → Round 1 の結論を補強。

### 発見2: 新しい設計軸が 2 つ創発（curated 7 軸に欠けていた次元）
- **`resource_awareness`**（値例 `optimized_resource`）— 残電力/CPU/バッファを
  ルーティング判断に織り込む軸。
- **`congestion_awareness`**（値例 `medium`）— 輻輳を避ける軸。`congestion=medium`
  は hybrid_ZRP(0.701) に乗っており有望。
- ただし両軸とも **探索が浅い（各 1 個体）** — 終盤に追加され伝播せず。
  → **Round 3 ではこの 2 軸を第一級軸として schema に入れて再探索**する価値あり。

## 結論

1. **設計判断は確定的**: 8 族 + LLM 発見プロトコルを通じて
   **hybrid_ZRP（≈ clustering-AODV）が依然最良**。実装方針 (drone-hil の ZRP) は妥当。
2. **次の探索シグナル**: GA が「resource/congestion awareness」という**欠けている軸**
   を指している。Round 3 = manet schema に `resource_awareness` / `congestion_awareness`
   を追加して再探索（hybrid_ZRP にこれらを足すと伸びるか）。
3. `bundle_forwarding` は分断支配シナリオ用のバックアップ設計として記録。

★ 注意: reviewer は LLM 主観スコア、新軸は探索が浅い。絶対値でなく相対傾向で読む。
成果物: `out/AIPL_DroneMANET_Round2.{lineage,elite_map,ranking,report}.json`。
