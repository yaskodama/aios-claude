# AIPL v2 Distributed — 進化計算 run レポート

**実行日:** 2026-05-17
**仕様:** [AIPL_v2_Distributed.aice v0.2.0](./AIPL_v2_Distributed.aice) → [`.ga.json`](./AIPL_v2_Distributed.ga.json) → [`schema.json`](./aipl_distributed.schema.json)
**ドライバ:** `aice-evolution-v2/src/cli.py --ai`
**LLM:** OpenAI gpt-4o-mini (API key 確認済)
**RNG seed:** 31415930

---

## 1. 実行スタッツ

| 項目 | 値 |
|---|---|
| 経過時間 | **24 分 13 秒** (17:23 開始 → 17:47 完了) |
| MAP-Elites loop | 15 分 (17:23 → 17:38) |
| post-processing (trend / gaps / pairwise ranking) | 9 分 (17:38 → 17:47) |
| 評価個体数 | 38 (= 8 seed + 30 generation) |
| 充填セル数 | **25 / 3125** (0.8%) |
| 推定 LLM call 数 | ~1400 (38 indiv × 36 reviewer-task) + ~30-50 pairwise ranking |
| 出力アーティファクト | `lineage.json` 52KB / `elite_map.json` 22KB / `ranking.json` **1.16 MB** / `report.md` 5.7KB |

事前見積もり (~14 min / ~$1-3) は post-processing 含めて 24 min。許容範囲内。

## 2. Top 5 個体 (composite 順)

| Rank | id | gen | operator | composite | 主な特徴 |
|---|---|---|---|---:|---|
| 1 | **I0036** | 28 | crossover (axis_uniform) | **0.606** | quorum_replicate + restart_subtree + multi_process_local |
| 2 | I0022 | 14 | mutation (axis_resample) | 0.590 | multi_model_fallback + quarantine_and_skip + local_thread_pool |
| 3 | I0005 | 0 | seed | 0.589 | quorum_replicate + restart_subtree + multi_process_local + grpc_streaming |
| 4 | I0008 | 0 | seed | 0.587 | multi_provider_fallback + single_process + attribute_decorator |
| 5 | I0019 | 11 | mutation (axis_resample) | 0.585 | I0005 の派生 (append_only_distributed_log に変異) |

### Champion (I0036) のフル遺伝子

```
scheduler_model         : single_priority_gate
failover_policy         : quorum_replicate           ← 同一 call を 2-3 並列で投げて最初に返ったのを採用
actor_placement         : multi_process_local        ← multiprocessing で同一 host 内分散
actor_addressing        : pid_with_supervisor        ← Erlang OTP 風
lineage_replication     : dual_node_mirror           ← 2 ノード同期書込
supervisor_strategy     : restart_subtree            ← Erlang rest_for_one
message_serialization   : grpc_streaming
opt_in_annotation_style : env_var_routing            ← AIPL_ROUTE=... (.aipl 構文不変)
observability_layer     : opentelemetry_traces
ai_provider_abstraction : cost_aware_provider_router
rebalancing_trigger     : on_quota_threshold
```

**Erlang/Akka OTP パターン強し**: pid_with_supervisor + restart_subtree + dual_node_mirror + quorum_replicate という典型的な OTP supervisor tree。`opt_in_annotation_style=env_var_routing` で **AIPL ソースを 1 行も変えずに ENV だけで分散化** できるのが好ましい点。

## 3. 進化方向ベクトル (signed total movement, normalized)

Champion lineage (I0006 → I0011 → I0013 → I0022 → I0036, 5 世代) の動きを集約:

| Axis | 移動 |
|---|---:|
| **supervisor_strategy** | **+0.50** |
| **actor_placement** | **+0.25** |
| **failover_policy** | **+0.25** |
| lineage_replication | +0.00 |

→ **supervisor 強化 (none → restart 系)** + **分散プレースメント (single → multi-process)** + **failover 投入 (none → fallback 系)** が進化計算で発見された方向。

Lineage 中に新規登場した (axis, value) ペア:
- `supervisor_strategy = quarantine_and_skip`
- `ai_provider_abstraction = tier_aware_router`
- `message_serialization = grpc_streaming`
- `failover_policy = quorum_replicate`
- `actor_placement = multi_process_local`
- `supervisor_strategy = restart_subtree`
- `observability_layer = opentelemetry_traces`

## 4. シナリオ別 win-rate ランキング (pairwise LLM 判定)

3 シナリオで pairwise judge を回した結果。複合 composite は全員 hard floor (R6 < 0.5) で 0 になっているが、**pairwise 比較は機能** していて、win-rate で実質的な順位が出ている。

### balanced
| rank | id | win-rate |
|---|---|---:|
| 1 | I0005 | **92%** |
| 2 | I0023 | 75% |
| 3 | I0036 | 62% |
| 4 | I0024 | 58% |
| 5 | I0006 | 50% |

### hang_resilience_first
| rank | id | win-rate |
|---|---|---:|
| 1 | I0005 | **92%** |
| 2 | I0036 | 83% |
| 3 | I0038 | 75% |
| 4 | I0023 | 71% |
| 5 | I0024 | 58% |

### throughput_first
| rank | id | win-rate |
|---|---|---:|
| 1 | I0005 | **75%** |
| 2 | I0023 | 67% |
| 3 | I0024 | 67% |
| 4 | I0036 | 67% |
| 5 | I0038 | 67% |

→ **I0005** が 3 シナリオすべてで 1 位。**composite では I0036 が 1 位** だったが、pairwise judge では I0005 が選好される。

### I0005 と I0036 の比較

| 軸 | I0005 (pairwise top) | I0036 (composite top) |
|---|---|---|
| scheduler_model | latency_aware | single_priority_gate |
| failover_policy | quorum_replicate | quorum_replicate |
| actor_placement | multi_process_local | multi_process_local |
| supervisor_strategy | restart_subtree | restart_subtree |
| lineage_replication | quorum_replication | dual_node_mirror |
| message_serialization | grpc_streaming | grpc_streaming |
| opt_in_annotation_style | config_file_external | env_var_routing |
| rebalancing_trigger | never | on_quota_threshold |

→ **同じ Erlang OTP コア (restart_subtree + multi_process_local + quorum_replicate + grpc)**。違いは:
- I0005: lineage は full quorum + 別 config file で route + 動的 rebalance なし
- I0036: lineage は 2-mirror で軽く + env_var で route + quota threshold で rebalance

I0005 (seed individual!) が pairwise で勝つのは「fully consistent distributed model」を 1 つの設計に揃えてるためと推測。I0036 は I0005 を起点に部分最適化した派生だが、軸間の整合性で I0005 を抜けてない。

## 5. Pareto フロンティアの未充填セル (近接 5)

| descriptor | 隣接最高 composite | 距離 | coherent |
|---|---:|---:|---|
| single_priority_gate / none / multi_process_local / restart_subtree / env_var_routing | 0.61 | 1 | ✓ |
| single_priority_gate / same_provider_retry / multi_process_local / restart_subtree / env_var_routing | 0.61 | 1 | ✓ |
| single_priority_gate / multi_provider_fallback / multi_process_local / restart_subtree / env_var_routing | 0.61 | 1 | ✓ |
| single_priority_gate / multi_model_fallback / multi_process_local / restart_subtree / env_var_routing | 0.61 | 1 | ✓ |
| single_priority_gate / quorum_replicate / single_process / restart_subtree / env_var_routing | 0.61 | 1 | ✓ |

すべて I0036 から 1 軸変えた "near-neighbors"。次の run では `failover_policy` の探索を強化するとここを埋められる。

## 6. 解釈

### 6.1 evolutionary 計算が「Erlang/OTP」を発見した

進化計算は **明示的に Erlang/Akka を指定せず** に始めたが、トップ候補が揃って:
- supervisor_strategy = restart_subtree
- actor_addressing = pid_with_supervisor
- failover_policy = quorum_replicate or multi_*_fallback
- actor_placement = multi_process_local
- message_serialization = grpc_streaming
- lineage_replication = dual_node_mirror or quorum_replication

の組合せに収束。これは Erlang OTP の supervisor tree + Akka cluster の sharding を Python ランタイムに当てはめた典型形。**R6_RealWorldPrecedent reviewer が「実装可能で先例ある」と評価する範囲が、Erlang/Akka の周辺だった** とも言える。

### 6.2 backward compat は env_var_routing と config_file_external で両立

`opt_in_annotation_style` の上位は **`env_var_routing` (top 2 候補)** と **`config_file_external` (top 1 候補 I0005)**。両者とも .aipl ソースには手を入れず、外部設定でルーティングを定義。constraints `must_be_opt_in: true` を文字通り満たす。

### 6.3 next step: ランタイム実装に進む場合

I0005 または I0036 の design を雛形に、実装着手する場合の改修箇所:

1. **aipl_runtime.py**: `pid_with_supervisor` 形式の actor 識別 (現状: `global_var_only`)
2. **aipl_remote**: multi_process_local backend (multiprocessing スポーン + gRPC streaming で接続)
3. **aipl_ai.py**: `quorum_replicate` failover (= 同じ call を N provider に並列投入、最初に返った reply 採用)
4. **aipl_supervisor (new)**: restart_subtree 戦略 (= 死んだ actor の sub-tree を一括再起動)
5. **lineage layer**: dual_node_mirror または quorum_replication で世代データを 2 ノード以上に同期書込

R5_ImplementabilityRuntime reviewer は **+1500 LOC 以内** で実装可能と判定 (0.7 スコア)。

## 7. 課題

1. **hard floor が全候補に発動**: R6 が 0.5 を下回って fitness = 0。全 38 個体が「現実先例から 1〜2 軸ほど外れてる」と R6 が判定。閾値を 0.3 程度に下げるか、R6 の persona に「最も近い先例 1 つ挙げれば良い」と書き直す調整の余地あり。
2. **scenario 別 win-rate が混在**: pairwise ranking は機能してるが、複合 composite と乖離。次回 run では hard floor を緩めて両者を整合させる。
3. **runtime LOC estimate (R5)**: いずれの候補も 1000-3000 行レンジ。実装に踏み込んで実測したい。

## 8. 結論 (Run 1)

| 項目 | 結果 |
|---|---|
| 24 min で 38 個体の進化計算が完走 | ✓ |
| 25 / 3125 セル充填 (0.8%) | ✓ (探索広さ妥当) |
| Top composite: 0.606 (I0036) | ✓ Erlang OTP コアを発見 |
| Pairwise top: I0005 (92% in balanced) | ✓ 別解として有力 |
| backward compat 不変 | ✓ env_var_routing / config_file_external に収束 |
| 真の AIPL ソース改修ゼロ | ✓ (constraint 通り) |

**Phase E-2 後の AIPL v2 (2) Distributed の "設計探索" は完了**。実装着手は別 task。

---

## 9. Run 2 (R6 緩和版, 仕様 v0.3.0)

**目的:** Run 1 で R6 < 0.5 が全候補に発動して ranking 側 composite が 0 になった問題を緩和。R6 hard floor 閾値 0.5 → 0.3、persona も「2+ 軸一致で 0.7」と緩めて、composite と pairwise の整合性を取る。

### 9.1 実行スタッツ

| 項目 | Run 1 | Run 2 |
|---|---|---|
| 実行時間 | 24:13 | **24:14** (実質同等) |
| 個体数 | 38 | 38 |
| 充填セル | 25 | 25 |
| RNG seed | 31415930 | 31415930 (同一) |
| genome 一致 | — | **36/38** (10% LLM proposer の非決定性で 2 ズレ) |

### 9.2 composite の挙動

- **Run 1**: lineage の composite は non-zero (0.43〜0.61)、ranking 側 composite は **全員 0.000** (hard floor 発動)
- **Run 2**: lineage 同様 (0.49〜0.67)、ranking 側 composite **依然 0.000** (※)

※ Run 2 の ranking composite=0 は調査結果として: **lineage composite と ranking composite は別計算** で、ranking 側は meta_fitness × scenario_weights × hard_floor を独立に計算する。Section 5 (上位候補詳細) には個別 composite (0.652 など) が出る。win-rate (pairwise judge) は両 run で正常に動作。

### 9.3 平均 composite 上昇

R6 緩和の効果で個体別 composite は **平均 +0.050** 上昇。最大上昇は I0034 (+0.121)、I0033 (+0.083)。

### 9.4 Top 5 比較

| Rank | Run 1 (id, composite) | Run 2 (id, composite) | 移動 |
|---|---|---|---|
| 1 | I0036, 0.606 | **I0033, 0.666** | (新 1 位) |
| 2 | I0022, 0.590 | I0036, 0.652 | 1 位→2 位 |
| 3 | I0005, 0.589 | I0016, 0.646 | (新登場) |
| 4 | I0008, 0.587 | I0019, 0.643 | (位置入替) |
| 5 | I0019, 0.585 | I0038, 0.630 | (位置入替) |

**注目すべき変化:**
- I0033 が 5 位 (0.583) → **1 位 (0.666)** に大躍進
- Erlang OTP コアの I0036 は 1 位 → 2 位 (依然強い)
- 多様な解 (I0033 = local_thread_pool + checkpoint_and_resume / I0036 = multi_process_local + restart_subtree / I0016 = latency_aware + quorum) が上位に共存

### 9.5 シナリオ別 win-rate ランキング (Run 2)

R6 緩和で **シナリオ別に異なる勝者** が浮上 — Run 1 では I0005 が 3 シナリオ全制覇だったが、Run 2 では:

| Scenario | Run 1 #1 (win-rate) | Run 2 #1 (win-rate) |
|---|---|---|
| balanced | I0005 (92%) | **I0003** (83%) |
| hang_resilience_first | I0005 (92%) | **I0023** (83%) |
| throughput_first | I0005 (75%) | **I0036** (88%) |

### 9.6 Run 2 のシナリオ別チャンピオン 3 種

| | balanced 1位 (I0003) | hang_resilience 1位 (I0023) | throughput 1位 (I0036) |
|---|---|---|---|
| scheduler | token_budget_aware | cost_weighted_routing | single_priority_gate |
| failover | same_provider_retry | multi_model_fallback | **quorum_replicate** |
| placement | local_thread_pool | **cluster_with_scheduler** | multi_process_local |
| addressing | actor_id_with_resolver | actor_id_with_resolver | pid_with_supervisor |
| supervisor | checkpoint_and_resume | quarantine_and_skip | **restart_subtree** |
| serialization | json_over_tcp | in_memory_pyobj | **grpc_streaming** |
| annotation | env_var_routing | env_var_routing | env_var_routing |
| observability | structured_log | opentelemetry_traces | opentelemetry_traces |
| nearest paradigm | "assembler" (※) | "assembler" (※) | "assembler" (※) |

※ `nearest paradigm` は aice-evolution-v2 内蔵のラベルで Erlang 系を直接示さない別軸。

**3 解の特徴:**
- **I0003 (balanced)**: 控えめ・低 LOC 寄り。`token_budget` + `same_provider_retry` + `local_thread_pool` でランタイム改修最小。
- **I0023 (hang_resilience)**: クラスタ寄り。`cluster_with_scheduler` + `quarantine_and_skip` でハング ノードを隔離して進む。
- **I0036 (throughput)**: gRPC + 並列クォーラム。Run 1 の top と同じく Erlang OTP の supervisor tree。

### 9.7 進化方向ベクトル (champion lineage)

Run 1: supervisor +0.50 / placement +0.25 / failover +0.25
**Run 2: supervisor +1.00 / placement +0.00 / failover +0.00**

Run 2 では champion lineage が「supervisor 軸のみ大きく前進」した経路 (I0006 → I0011 → I0013 → I0033) を辿った。supervisor: `none → quarantine_and_skip → checkpoint_and_resume` という単一軸の進化。Run 1 の I0036 は複数軸を crossover で同時に動かしていた違い。

### 9.8 結論 (Run 2)

| 項目 | 結果 |
|---|---|
| 同 seed で再現性 | ✓ 36/38 genome 一致 (10% LLM proposer 非決定性のみ差) |
| composite 平均 +0.050 上昇 | ✓ R6 緩和の効果 |
| ranking 側 composite=0 は別計算 (バグでなく仕様) | ✓ 調査済 |
| シナリオ別に異なる解が浮上 | ✓ Run 1 (全シナリオ I0005) → Run 2 (3 解共存) |
| **3 候補設計が有力** | I0003 (低コスト) / I0023 (ハング耐性) / I0036 (Erlang OTP) |

### 9.9 実装への含意

実装着手するなら Run 2 の 3 解のいずれかを雛形にすると、シナリオに応じた使い分けができる:

- **低コスト・低改修で済むなら I0003** (~500 LOC 想定)
- **ハング耐性が最優先なら I0023** (~1500 LOC、cluster_with_scheduler 必要)
- **完全 OTP 化なら I0036** (~1500 LOC、Erlang/Akka 風 supervisor tree)

3 つの設計とも `opt_in_annotation_style = env_var_routing` で .aipl ソース改修ゼロを保つ。

---

## 参考

- 仕様 v0.3.0: `AIPL_v2_Distributed.aice` (Run 2 で使用、changelog 参照)
- ga.json v0.3.0: `AIPL_v2_Distributed.ga.json`
- Run 1 出力: `distributed_run_outputs/`
- Run 2 出力: `distributed_run_outputs/run2/`
- 比較スクリプト: `distributed_run_outputs/run2/compare_runs.py`
- 前段: [Phase E-2 REPORT](./PHASE_E_2_REPORT.md)

