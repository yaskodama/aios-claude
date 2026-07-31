# AIPL v2 Distributed — I0036 Erlang OTP MVP (restart_subtree + quorum_replicate)

**日付:** 2026-05-18
**前段:** [IMPL_I0023_REPORT.md](./IMPL_I0023_REPORT.md) (quarantine_and_skip = hang resilience)
**雛型:** Run 2 throughput_first シナリオ勝者 I0036 (composite=0.652, win-rate 88%)

---

## 1. 雛型 I0036 の遺伝子 vs MVP 達成度

| 遺伝子軸 | I0036 値 | MVP 達成 |
|---|---|---|
| scheduler_model | single_priority_gate | 既存 `_PriorityGate` で達成済 |
| **failover_policy** | **quorum_replicate** | ✅ **新規実装** (`call_ai_quorum`) |
| **actor_placement** | **multi_process_local** | ❌ multiprocessing 必要、本 MVP スコープアウト |
| actor_addressing | pid_with_supervisor | スレッド名 `actor-<name>` で擬似 PID 化 (新規でなく既存) |
| lineage_replication | dual_node_mirror | I-2 NDJSON で部分カバー |
| **supervisor_strategy** | **restart_subtree** | ✅ **新規実装** (`quarantine_subtree`, passive 版) |
| **message_serialization** | **grpc_streaming** | ❌ multi-process と一体、スコープアウト |
| opt_in_annotation_style | env_var_routing | I-1 で実装済 |
| observability_layer | opentelemetry_traces | I-2 NDJSON で代替 |
| ai_provider_abstraction | cost_aware_provider_router | 既存で代替可 |
| rebalancing_trigger | on_quota_threshold | I-3 (token_budget) で部分カバー |

**真に新規実装: 2 軸 (restart_subtree / quorum_replicate)**。残る 2 軸 (multi_process_local / grpc_streaming) は数百 LOC のインフラ必要のためスコープアウト。

## 2. 実装

### 2.1 `aipl_dist.py` への追加 (+165 LOC、合計 426 → 591)

**IM-1: quorum_replicate** (~100 LOC)

| 関数 | 役割 |
|---|---|
| `quorum_providers()` | `AIPL_DIST_QUORUM_PROVIDERS` を parse |
| `call_ai_quorum(prompt, call_ai_fn, providers, **kw)` | 全 provider に並列投入、first-reply wins。1 つでも成功すれば成功、全部失敗時のみ raise |

ThreadPoolExecutor で並列、`done_evt` で first-reply 検出、`all_done` で全失敗 deadlock 回避 (← 初版で発見・修正したバグ)。

**IM-2: restart_subtree (passive 版 = subtree_quarantine)** (~65 LOC)

| 関数 | 役割 |
|---|---|
| `register_spawn(child, parent)` | spawn tree に親子関係を登録 |
| `descendants_of(actor)` | BFS で全子孫を取得 |
| `quarantine_subtree(actor, ttl)` | actor + 子孫を一括 quarantine、新規 quarantined のリスト返却 |

Active restart (= 再 spawn) は実装せず、passive equivalent (= 子孫 quarantine) で代替。本物の Erlang OTP `rest_for_one` の "blast-radius containment" 性質を保持。

### 2.2 既存ファイルへの hook (+11 LOC)

| ファイル | hook |
|---|---|
| `aipl_interp.spawn_actor` (前 phase に既設) | spawn parent を **スレッド名 `actor-<name>`** から取得して `register_spawn(name, parent)` を呼び出し (+5 LOC) |
| `aipl_runtime.Actor._run` (前 phase の auto-quarantine を分岐) | `AIPL_DIST_SUBTREE_QUARANTINE=1` のとき `quarantine_subtree` を呼ぶ (+6 LOC) |

非侵入性: スレッド名は既に `aipl_runtime.Actor.start` が `"actor-<name>"` で命名済 → 別途データ pipeline 不要。

## 3. 検証

### 3.1 単体テスト (15 → 19 → 27)

```
PASS  spawn tree disabled returns empty
PASS  spawn tree simple
PASS  subtree quarantine cascades
PASS  quorum providers parse
PASS  quorum disabled passes through
PASS  quorum first wins
PASS  quorum tolerates one failing provider
PASS  quorum all fail raises

27/27 passing
```

### 3.2 subtree_quarantine_demo.aipl

```
Supervisor
├── Worker A      (ok)
│   └── Helper hA (ok)
└── Worker B      (crashes!)
    └── Helper hB (cascaded -> quarantined)
```

実行 (`AIPL_DIST_ENABLE=1 AIPL_DIST_SUBTREE_QUARANTINE=1 ...`):

```
stderr: [actor wB.crash] error: division by zero    ← 1 回のみ
stdout: worker w ok                                  ← wA は live
stdout: supervisor done                              ← Supervisor 自身も live

NDJSON:
  actor_quarantined  wB
  actor_quarantined  h           (= Helper hB)
  subtree_quarantined root=wB members=["wB", "h"]
  actor_skip_quarantined wB.ok   (= wA.ok は skip されない)
```

`wB` のサブツリーが失敗で隔離、`wA` 側は無影響。Erlang OTP の supervisor tree の核心動作。

### 3.3 quorum_replicate の動作

`test_quorum_first_wins`: providers=[fast, slow] (slow は 0.2s sleep) → 結果は `fast-reply` (即座)
`test_quorum_handles_one_failing_provider`: providers=[broken, working] (broken は raise) → 結果は `from-working`
`test_quorum_all_fail_raises`: 全部 raise → `RuntimeError("quorum: all providers failed: ...")` を投げる

**Run 1 silent hang シナリオに当てはめると**: gpt-4o-mini で hang した場合も、quorum=[openai, anthropic, gemini] が並列に走り、anthropic か gemini が応答すれば caller は止まらない。

### 3.4 既存 sample 回帰

| Suite | PASS |
|---|---|
| `src/python-aipl/samples/*.aipl` (33 件) | **33/33** |
| `samples/feature_*/*.aipl` (21 件) | **21/21** |
| 単体テスト | **27/27** |
| 既存 phase samples (env_var_routing / structured_log / quarantine / end_to_end) | 全 OK |

`AIPL_DIST_ENABLE` unset で完全 backward-compat。

## 4. PsiLang v3 シナリオへの組合せ効果

3 つの MVP を全部有効化:

```sh
export AIPL_DIST_ENABLE=1
export AIPL_DIST_QUORUM_PROVIDERS="openai,anthropic,gemini"
export AIPL_DIST_QUARANTINE_TTL=60
export AIPL_DIST_SUBTREE_QUARANTINE=1
export AIPL_DIST_CHECKPOINT_DIR=/tmp/aipl_ck
export AIPL_DIST_LOG_FILE=/tmp/run.ndjson
```

これで Run 1 で 35/38 喪失したシナリオが:
- **call-level**: OpenAI hang → anthropic/gemini が応答 → caller は continue (= IM quorum)
- **actor-level**: それでも actor が落ちたら quarantine、子孫も連鎖隔離 (= IQ + IM subtree)
- **persistent state**: actor 再 spawn 時にチェックポイント復元 (= I-4)
- **observability**: NDJSON で全イベント記録 (= I-2)

**期待効果**: 35/38 → ~1-2/38 程度の喪失で済む (設計上)。

## 5. スコープアウトした 2 軸

### multi_process_local

実装すると ~400+ LOC + Python `multiprocessing` のオーバーヘッド + 子プロセスの inter-process channel 設計。Python GIL 回避が必要なケースでのみ価値 (AIPL は I/O bound なので thread で十分なケースが大半)。

### grpc_streaming

multi_process_local と組合せる前提のため、placement なしでは意味がない。これも grpc 依存追加 + IDL 設計で ~500 LOC。

→ どちらも次の MVP iteration (たとえば I0036+) の候補。

## 6. 規模

| 部分 | LOC (delta) |
|---|---:|
| aipl_dist.py 累積 | 591 (= 331 + 95 IQ + 165 IM) |
| 既存ファイル hook 累積 | +50 (= 27 I-5/I-6/I-7 + 19 IQ + 11 IM) |
| 単体テスト | 27 個 |
| sample .aipl + .py | 8 個 |
| ドキュメント | 4 レポート |

**I0036 の本 phase 純増は ~190 LOC**。3 MVP (I0003 + I0023 + I0036) の合計純増は ~700 LOC で、当初想定 (~1500 LOC for I0036 alone) より遥かに少ない。

## 7. 結論

| 項目 | 結果 |
|---|---|
| `quorum_replicate` failover (並列 multi-provider) | ✅ 新規実装 |
| `restart_subtree` (passive subtree_quarantine) | ✅ 新規実装、Erlang OTP セマンティクス |
| spawn parent tracking via thread name (非侵入) | ✅ |
| 単体テスト (4 新規 + 8 新規 + 15 既存 = 27) | ✅ 27/27 PASS |
| End-to-end .aipl sample (`subtree_quarantine_demo.aipl`) | ✅ wA live + wB 子孫隔離 |
| 既存 33 + 21 sample 回帰 | ✅ 54/54 PASS |
| I0036 11 軸中 2 軸を新規実装、6 軸を既存機能でカバー、2 軸スコープアウト | ✅ |

**AIPL v2 Distributed 探索 → 3 MVP 実装まで完走**。実装規模:
- 設計探索: 24 min × 2 run = 48 min (LLM コスト ~$1-3)
- I0003 (balanced) MVP: 358 LOC
- I0023 (hang resilience) MVP: 164 LOC
- I0036 (Erlang OTP) MVP: 187 LOC
- **合計実装: ~710 LOC、既存 54 sample 完全回帰**

## 8. 次の自然なステップ

- **PsiLang v3 を Distributed 全部有効で再走**: 35/38 喪失が実測でどこまで改善するか
- **multi_process_local の本格実装**: ~400 LOC で I0036 を完成形に
- **3 MVP 統合の総合 demo**: 1 .aipl で 4 + 1 + 2 = 7 機能発火

---

## 参考

- 前段: [IMPL_I0023_REPORT.md](./IMPL_I0023_REPORT.md)、[IMPL_INTEGRATION_REPORT.md](./IMPL_INTEGRATION_REPORT.md)、[IMPL_RUN_REPORT.md](./IMPL_RUN_REPORT.md)、[IMPL_DESIGN.md](./IMPL_DESIGN.md)
- 雛型由来: [PHASE_E_DISTRIBUTED_RUN_REPORT.md §9.6](../PHASE_E_DISTRIBUTED_RUN_REPORT.md#96-run-2-のシナリオ別チャンピオン-3-種) (I0036 = throughput 勝者)
- 実装: `src/python-aipl/aipl_dist.py` (331 → 591 LOC, +260 LOC across 2 phase)
- hook: `src/python-aipl/aipl_interp.py`、`src/python-aipl/aipl_runtime.py`
- sample: `samples/subtree_quarantine_demo.aipl`
- tests: `tests/test_aipl_dist.py` (27 個)
