# AIPL_v2_Distributed

> AIPL ランタイム層 (aipl_ai.py, aipl_runtime.py, aipl_remote) を進化計算で拡張し、分散・負荷分散・フェイルオーバを実現する設計を発見する。既存 AIPL プログラム (PsiLang2, evolve block, samples/feature_a-g 21 件, src/python-aipl/samples 33 件) は無変更で動くこと必須。

## 1. 発見された進化軌跡 (best champion lineage)

系譜長: 4 世代分

| step | id | gen | operator | paradigm | type_safety | concurrency_model |
|------|----|-----|----------|----------|-------------|-------------------|
| 0 | `I0006` | 0 | `seed` | ? | ? | ? |
| 1 | `I0011` | 3 | `mutation:axis_resample` | ? | ? | ? |
| 2 | `I0013` | 5 | `mutation:axis_resample` | ? | ? | ? |
| 3 | `I0033` | 25 | `mutation:axis_resample` | ? | ? | ? |

## 2. 進化方向ベクトル (signed total movement, normalized)

- `supervisor_strategy`: +1.00
- `actor_placement`: +0.00
- `failover_policy`: +0.00
- `lineage_replication`: +0.00

**Lineage 内で新しく現れた (axis, value) ペア**:
- `supervisor_strategy = quarantine_and_skip`
- `ai_provider_abstraction = tier_aware_router`
- `supervisor_strategy = checkpoint_and_resume`

## 3. Pareto フロンティア — 未充填セル (top 5 promising gaps)

| descriptor | 隣接セル最高 composite | 距離 | コヒーレント |
|-----------|------------------------|------|--------------|
| scheduler_model=single_priority_gate, failover_policy=none, actor_placement=local_thread_pool, supervisor_strategy=checkpoint_and_resume, opt_in_annotation_style=env_var_routing | 0.67 | 1 | yes |
| scheduler_model=single_priority_gate, failover_policy=same_provider_retry, actor_placement=local_thread_pool, supervisor_strategy=checkpoint_and_resume, opt_in_annotation_style=env_var_routing | 0.67 | 1 | yes |
| scheduler_model=single_priority_gate, failover_policy=multi_provider_fallback, actor_placement=local_thread_pool, supervisor_strategy=checkpoint_and_resume, opt_in_annotation_style=env_var_routing | 0.67 | 1 | yes |
| scheduler_model=single_priority_gate, failover_policy=multi_model_fallback, actor_placement=single_process, supervisor_strategy=checkpoint_and_resume, opt_in_annotation_style=env_var_routing | 0.67 | 1 | yes |
| scheduler_model=single_priority_gate, failover_policy=multi_model_fallback, actor_placement=local_thread_pool, supervisor_strategy=restart_actor, opt_in_annotation_style=env_var_routing | 0.67 | 1 | yes |

## 4. ランキング（シナリオ別）

### Scenario: balanced
_重み: silent_hang_resilience=0.2, throughput_per_dollar=0.2, backward_compat_score=0.2, failover_correctness=0.15, real_world_precedent=0.1, low_runtime_added_loc=0.1, low_latency_overhead=0.05_

| rank | id | paradigm | composite | Pareto層 | win-rate |
|------|----|----------|-----------|----------|----------|
| 1 | `I0003` | ? | 0.000 | 1 | 83% |
| 2 | `I0010` | ? | 0.000 | 1 | 75% |
| 3 | `I0036` | ? | 0.000 | 1 | 75% |
| 4 | `I0016` | ? | 0.000 | 1 | 67% |
| 5 | `I0013` | ? | 0.000 | 1 | 67% |

### Scenario: hang_resilience_first
_重み: silent_hang_resilience=0.45, throughput_per_dollar=0.1, backward_compat_score=0.15, failover_correctness=0.2, real_world_precedent=0.05, low_runtime_added_loc=0.05, low_latency_overhead=0.0_

| rank | id | paradigm | composite | Pareto層 | win-rate |
|------|----|----------|-----------|----------|----------|
| 1 | `I0023` | ? | 0.000 | 1 | 83% |
| 2 | `I0010` | ? | 0.000 | 1 | 79% |
| 3 | `I0003` | ? | 0.000 | 1 | 75% |
| 4 | `I0016` | ? | 0.000 | 1 | 75% |
| 5 | `I0038` | ? | 0.000 | 1 | 75% |

### Scenario: throughput_first
_重み: silent_hang_resilience=0.1, throughput_per_dollar=0.45, backward_compat_score=0.15, failover_correctness=0.05, real_world_precedent=0.1, low_runtime_added_loc=0.1, low_latency_overhead=0.05_

| rank | id | paradigm | composite | Pareto層 | win-rate |
|------|----|----------|-----------|----------|----------|
| 1 | `I0036` | ? | 0.000 | 1 | 88% |
| 2 | `I0013` | ? | 0.000 | 1 | 75% |
| 3 | `I0023` | ? | 0.000 | 1 | 75% |
| 4 | `I0038` | ? | 0.000 | 1 | 71% |
| 5 | `I0003` | ? | 0.000 | 1 | 67% |

## 5. 上位候補の詳細

### I0003  (balanced の1位)
- 遺伝子: `scheduler_model=token_budget_aware, failover_policy=same_provider_retry, actor_placement=local_thread_pool, actor_addressing=actor_id_with_resolver, lineage_replication=append_only_distributed_log, supervisor_strategy=checkpoint_and_resume, message_serialization=json_over_tcp, opt_in_annotation_style=env_var_routing, observability_layer=structured_log, ai_provider_abstraction=tier_aware_router, rebalancing_trigger=never`
- セル: `scheduler_model=token_budget_aware|failover_policy=same_provider_retry|actor_placement=local_thread_pool|supervisor_strategy=checkpoint_and_resume|opt_in_annotation_style=env_var_routing`
- composite (run-内): 0.548
- 最近傍既存パラダイム: **assembler**
- meta-fitness: trend_alignment=0.75, frontier_coverage=0.56, novelty=1.00, evolvability=0.00, cross_task_generality=0.41, implementability=0.60
- タスク別スコア: SurviveSilentHang=0.39, SustainedThroughput=0.45, BackwardCompatPsiLang2=0.42, MultiProviderFailover=0.33, LineageDurability=0.45, ImplCostEstimate=0.45

### I0023  (hang_resilience_first の1位)
- 遺伝子: `scheduler_model=cost_weighted_routing, failover_policy=multi_model_fallback, actor_placement=cluster_with_scheduler, actor_addressing=actor_id_with_resolver, lineage_replication=append_only_distributed_log, supervisor_strategy=quarantine_and_skip, message_serialization=in_memory_pyobj, opt_in_annotation_style=env_var_routing, observability_layer=opentelemetry_traces, ai_provider_abstraction=cost_aware_provider_router, rebalancing_trigger=never`
- セル: `scheduler_model=cost_weighted_routing|failover_policy=multi_model_fallback|actor_placement=cluster_with_scheduler|supervisor_strategy=quarantine_and_skip|opt_in_annotation_style=env_var_routing`
- composite (run-内): 0.542
- 最近傍既存パラダイム: **assembler**
- meta-fitness: trend_alignment=0.70, frontier_coverage=0.94, novelty=1.00, evolvability=0.44, cross_task_generality=0.40, implementability=0.60
- タスク別スコア: SurviveSilentHang=0.39, SustainedThroughput=0.39, BackwardCompatPsiLang2=0.33, MultiProviderFailover=0.45, LineageDurability=0.39, ImplCostEstimate=0.45

### I0036  (throughput_first の1位)
- 遺伝子: `scheduler_model=single_priority_gate, failover_policy=quorum_replicate, actor_placement=multi_process_local, actor_addressing=pid_with_supervisor, lineage_replication=dual_node_mirror, supervisor_strategy=restart_subtree, message_serialization=grpc_streaming, opt_in_annotation_style=env_var_routing, observability_layer=opentelemetry_traces, ai_provider_abstraction=cost_aware_provider_router, rebalancing_trigger=on_quota_threshold`
- セル: `scheduler_model=single_priority_gate|failover_policy=quorum_replicate|actor_placement=multi_process_local|supervisor_strategy=restart_subtree|opt_in_annotation_style=env_var_routing`
- composite (run-内): 0.652
- 最近傍既存パラダイム: **assembler**
- meta-fitness: trend_alignment=0.62, frontier_coverage=0.56, novelty=1.00, evolvability=0.00, cross_task_generality=0.57, implementability=0.60
- タスク別スコア: SurviveSilentHang=0.62, SustainedThroughput=0.47, BackwardCompatPsiLang2=0.62, MultiProviderFailover=0.59, LineageDurability=0.57, ImplCostEstimate=0.53

## 6. 留保 (uncertainty)

シナリオ間で順位が入れ替わる候補は、外的条件次第でいずれの方向にも有力です。単一の正解はなく、本レポートは meta-fitness 重み選択への依存を保持したまま提示しています。
