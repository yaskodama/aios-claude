# AIPL v2 Distributed — I0003 MVP 実装結果

**日付:** 2026-05-18
**前段:** [IMPL_DESIGN.md](./IMPL_DESIGN.md) (雛型: I0003, balanced シナリオ Run 2 勝者)
**実装範囲:** I-1〜I-4 (env_var_routing / structured_log / token_budget / checkpoint_and_resume)

---

## 1. 完成物

| ファイル | 用途 | LOC |
|---|---|---:|
| `src/python-aipl/aipl_dist.py` | I-1〜I-4 4 piece の全実装 (新規・既存無改変) | **310** |
| `IMPL_I0003_MVP/tests/test_aipl_dist.py` | 15 個の単体テスト | 235 |
| `IMPL_I0003_MVP/samples/env_var_routing.aipl` | I-1 デモ (.aipl) | 23 |
| `IMPL_I0003_MVP/samples/structured_log_demo.py` | I-2 デモ (Python script) | 28 |
| `IMPL_I0003_MVP/samples/token_budget_demo.py` | I-3 デモ (Python script) | 36 |
| `IMPL_I0003_MVP/samples/checkpoint_demo.py` | I-4 デモ (Python script) | 36 |
| `IMPL_I0003_MVP/IMPL_DESIGN.md` | 設計 | (design only) |
| `IMPL_I0003_MVP/IMPL_RUN_REPORT.md` | this file | — |

**コード正味増分: 310 行** (設計上限 ~400 LOC 内)。

## 2. 検証結果

### 2.1 単体テスト

```
$ python3 IMPL_I0003_MVP/tests/test_aipl_dist.py
  PASS  disabled returns safe defaults
  PASS  route parse basic
  PASS  route parse with garbage
  PASS  route enabled lookup
  PASS  route disabled returns None
  PASS  log event writes NDJSON
  PASS  log event silent when no file
  PASS  budget gate None when unconfigured
  PASS  budget gate admits within limit
  PASS  budget gate blocks then unblocks
  PASS  call_ai_with_budget passthrough when disabled
  PASS  call_ai_with_budget records when gated
  PASS  checkpoint save+restore roundtrip
  PASS  checkpoint list states
  PASS  checkpoint restore missing

15/15 passing
```

### 2.2 既存サンプル回帰 (mock provider, 標準テスト env)

| Suite | 件数 | PASS | FAIL |
|---|---:|---:|---:|
| `src/python-aipl/samples/*.aipl` | 33 | **33** | 0 |
| `samples/feature_*/*.aipl` | 21 | **21** | 0 |
| **合計** | **54** | **54** | **0** |

**aipl_dist 起因の回帰ゼロを確認**。既存ファイルに 1 行も触っていないので想定通り。

### 2.3 4 サンプル実演ログ

#### I-1 env_var_routing — `.aipl` で動作

```
$ python3 src/python-aipl/aipl_main.py IMPL_I0003_MVP/samples/env_var_routing.aipl
Greeter says hi to Alice
Bench running

$ AIPL_DIST_ENABLE=1 AIPL_ROUTE="Greeter:fast,Bench:slow" \\
    python3 src/python-aipl/aipl_main.py IMPL_I0003_MVP/samples/env_var_routing.aipl
Greeter says hi to Alice
Bench running
```

両ケースで AIPL ソース無変更で同じ挙動 (MVP は parse + 報告のみ、placement 切替は I0036 拡張時)。

#### I-2 structured_log — NDJSON 1 行ずつ append

```
$ AIPL_DIST_ENABLE=1 AIPL_DIST_LOG_FILE=/tmp/log.ndjson \\
    python3 IMPL_I0003_MVP/samples/structured_log_demo.py
is_enabled() = True
log_event('startup', who='alice') -> True
log_event('work', task=1, ms=42) -> True
log_event('shutdown') -> True

$ cat /tmp/log.ndjson
{"ts": 1779033299.418338, "event": "startup", "who": "alice"}
{"ts": 1779033299.418614, "event": "work", "task": 1, "ms": 42}
{"ts": 1779033299.418871, "event": "shutdown"}
```

スレッドセーフ、書込み失敗は黙って False を返す (raise しない)。

#### I-3 token_budget — RPM 制限内で admit

```
$ AIPL_DIST_ENABLE=1 AIPL_DIST_RPM=3 \\
    python3 IMPL_I0003_MVP/samples/token_budget_demo.py
is_enabled() = True
AIPL_DIST_RPM = 3
gate = <aipl_dist.TokenBudgetGate object at 0x107c46120>

  call 1: reply-1  (0.00s)
  call 2: reply-2  (0.00s)
  call 3: reply-3  (0.00s)

window stats: {'rpm_used': 3, 'rpm_limit': 3, 'tpm_used': 27, 'tpm_limit': 0}
```

3 回まで即時 admit。4 回目は次の 60 秒スライド窓まで block する (テストでも検証済)。

#### I-4 checkpoint — save → restore roundtrip

```
$ AIPL_DIST_ENABLE=1 AIPL_DIST_CHECKPOINT_DIR=/tmp/ck \\
    python3 IMPL_I0003_MVP/samples/checkpoint_demo.py save
save_actor_state -> True, state = {'counter': 42, 'history': ['hello', 'world'], 'user': 'Bob'}

$ AIPL_DIST_ENABLE=1 AIPL_DIST_CHECKPOINT_DIR=/tmp/ck \\
    python3 IMPL_I0003_MVP/samples/checkpoint_demo.py restore
restore_actor_state -> {'counter': 42, 'history': ['hello', 'world'], 'user': 'Bob'}
```

POSIX 原子的 (write tmp + rename)。actor 名はファイル名にサニタイズされる (`path/with..bad/chars` → `path_with__bad_chars.json`)。

## 3. backward-compat の担保

| チェック | 結果 |
|---|---|
| 既存 `src/python-aipl/*.py` の変更 | **0 行** (新規 `aipl_dist.py` 追加のみ) |
| `AIPL_DIST_ENABLE` unset での挙動 | 全 public 関数が **no-op** (テスト で検証) |
| `import aipl_dist` のみで副作用 | **ゼロ** (テストで検証) |
| 既存 33 .aipl + 21 .aipl 回帰 | **54/54 PASS** |
| 既存テスト (`tests/test_aipl_dist.py` 以外) との衝突 | なし (新規ファイルのみ) |

仕様 `must_not_change_aipl_semantics: true` / `must_be_opt_in: true` を完全準拠。

## 4. I0003 の遺伝子 vs MVP 実装

| 遺伝子軸 | I0003 値 | MVP 実装 |
|---|---|---|
| scheduler_model | token_budget_aware | ✅ I-3 (`TokenBudgetGate`) |
| failover_policy | same_provider_retry | 既存 `aipl_ai._client_max_retries` で実質達成 (MVP では追加実装不要と判定) |
| actor_placement | local_thread_pool | 既存 actor scheduling が thread pool ベース、追加実装不要と判定 |
| actor_addressing | actor_id_with_resolver | 既存 `aipl_remote.set_actor_lookup` で代替可、未統合 |
| lineage_replication | append_only_distributed_log | ✅ I-2 の `log_event` が ND-JSON append として機能 (単一 file まで) |
| supervisor_strategy | checkpoint_and_resume | ✅ I-4 (`save_actor_state` / `restore_actor_state`) |
| message_serialization | json_over_tcp | MVP では単一プロセス動作で十分、未実装 |
| **opt_in_annotation_style** | (no_annotation_runtime_only / env_var_routing) | ✅ I-1 (`route_for`, `parse_route_table`) |
| observability_layer | structured_log | ✅ I-2 (`log_event`) |
| ai_provider_abstraction | tier_aware_router | I-3 と組合せ可、`call_ai_with_budget` で wrapper パターン |
| rebalancing_trigger | never | 静的設計、MVP で十分 |

**11 軸中 5 軸 (枢要) を直接実装、3 軸を既存機能で代替**。残る 3 軸 (json_over_tcp / multi-node addressing / multi-process placement) は I0023 / I0036 系の MVP に持ち越し。

## 5. 残課題 (MVP 後)

| Phase | 内容 | 想定 LOC |
|---|---|---:|
| **I-5** | `aipl_runtime` への `restore_actor_state` 自動呼び出し統合 (init 時) | +30 |
| **I-6** | `aipl_remote.set_actor_lookup` と `route_for` を接続 | +40 |
| **I-7** | I-3 を `aipl_ai.call_ai` に opt-in でフックする統合 | +25 |
| **I-8** | I0023 雛型 (hang resilience): `quarantine_and_skip` supervisor + cluster_with_scheduler | ~500 |
| **I-9** | I0036 雛型 (throughput): `quorum_replicate` failover + `multi_process_local` + gRPC | ~1000 |

I0003 MVP はここで一旦完了。本番 production に投入する前に I-5〜I-7 (既存ランタイムへの統合) を済ませる必要あり。

## 6. 結論

| 項目 | 結果 |
|---|---|
| Run 2 で発見された I0003 設計を MVP 実装 | ✅ 310 LOC / 4 piece |
| 単体テスト 15 個 (全機能 + 境界条件) | ✅ 15/15 PASS |
| 既存 33 .aipl + 21 .aipl 回帰 | ✅ 54/54 PASS |
| 既存ファイル 1 行も無改変 | ✅ 達成 |
| sample 4 件で動作実演 | ✅ 完了 |
| 設計上限 ~400 LOC 内 | ✅ 310 LOC |

**AIPL v2 Distributed の I0003 (balanced) 設計探索 → MVP 実装まで完了**。`aipl_dist.py` を有効化するだけで:
- 観測性 (ND-JSON ログ)
- レート制御 (RPM/TPM 60 秒スライディング窓)
- アクターチェックポイント (save/restore)
- 環境変数ベースのルーティング (parse のみ、将来の placement に備える)

の 4 機能が利用できる。`AIPL_DIST_ENABLE=0` (デフォルト) で既存挙動完全維持。

---

## 参考

- 雛型ソース: [PHASE_E_DISTRIBUTED_RUN_REPORT.md §9.6](../PHASE_E_DISTRIBUTED_RUN_REPORT.md#96-run-2-のシナリオ別チャンピオン-3-種) (I0003 の balanced 1 位)
- 設計: [IMPL_DESIGN.md](./IMPL_DESIGN.md)
- ソース: `src/python-aipl/aipl_dist.py`
- テスト: `IMPL_I0003_MVP/tests/test_aipl_dist.py`
- サンプル: `IMPL_I0003_MVP/samples/`
