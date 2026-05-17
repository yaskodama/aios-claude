# AIPL v2 Distributed MVP — 24 サンプル スナップショット (8 feature × 3)

**実行日:** 2026-05-18
**段階:** I0003 + I0023 + I0036 MVP すべて適用後 (`aipl_dist.py` 591 LOC)
**全 24 サンプル: 24 / 24 PASS** (Traceback / parse error / FATAL なし)

## Feature と genome の対応

| Feature dir | 機能 | 主な env var | 由来 MVP |
|---|---|---|---|
| `i1_env_var_routing/` | actor 名 → routing tag | `AIPL_ROUTE` | I0003 (I-1) |
| `i2_structured_log/` | NDJSON 1 行 / event | `AIPL_DIST_LOG_FILE` | I0003 (I-2) |
| `i3_token_budget/` | sliding 60s RPM/TPM gate | `AIPL_DIST_RPM`/`TPM` | I0003 (I-3) |
| `i4_checkpoint/` | actor state save/restore | `AIPL_DIST_CHECKPOINT_DIR` | I0003 (I-4) |
| `iq_quarantine/` | actor 失敗時の自動隔離 | `AIPL_DIST_QUARANTINE_TTL` | I0023 (IQ) |
| `im1_quorum/` | 並列 multi-provider call | `AIPL_DIST_QUORUM_PROVIDERS` | I0036 (IM-1) |
| `im2_subtree_quarantine/` | failed actor + 子孫を一括隔離 | `AIPL_DIST_SUBTREE_QUARANTINE` | I0036 (IM-2) |
| `integration/` | 上記の組合せデモ | (複数) | I0003+IQ+IM 統合 |

## 24 サンプル一覧

| Feature | sample1 | sample2 | sample3 |
|---|---|---|---|
| **i1 routing** | basic.aipl (.aipl で actor 名 routing) | no_match.py (lookup miss path) | log_correlation.py (route + log の組合せ) |
| **i2 log** | basic.py (3 event 書込) | no_file.py (silent no-op) | multi_thread.py (10 threads × 50 events、 lost ゼロ) |
| **i3 budget** | basic.py (RPM=3 で 3 calls 通過) | blocking.py (window 満杯時の blocking) | aipl_integration.aipl (.aipl からの ai_call) |
| **i4 checkpoint** | basic.py (save+restore roundtrip) | atomic.py (5 threads × 50 save の atomic) | list_states.py (5 actor 一覧) |
| **iq quarantine** | basic.aipl (Flaky.boom 4 回、 1 fail+3 skip) | ttl_expiry.py (0.5s で TTL 切れ) | manual_clear.py (clear_quarantine 動作) |
| **im1 quorum** | first_wins.py (fast/med/slow 並列) | tolerates_one_failure.py (1 broken + 2 ok) | all_fail.py (全失敗 → RuntimeError) |
| **im2 subtree** | basic.aipl (Worker B crash → wB + Helper 隔離) | grandchildren.aipl (3 level tree) | unrelated_unaffected.aipl (並列 2 tree、1 fail) |
| **integration** | basic.aipl (counter + reporter + checkpoint 復元) | combined_logging.aipl (route + log + checkpoint) | full_resilience.aipl (全機能 simultaneously) |

## 結果サマリ

```
  i1__sample1  (2 lines)
  i1__sample2  (6 lines)
  i1__sample3  (7 lines)
  i2__sample1  (10 lines)
  i2__sample2  (10 lines)
  i2__sample3  (3 lines)
  i3__sample1  (9 lines)
  i3__sample2  (8 lines)
  i3__sample3  (1 lines)
  i4__sample1_save  (5 lines)
  i4__sample2  (2 lines)
  i4__sample3  (6 lines)
  im1__sample1  (1 lines)
  im1__sample2  (2 lines)
  im1__sample3  (1 lines)
  im2__sample1  (5 lines)
  im2__sample2  (3 lines)
  im2__sample3  (2 lines)
  int__sample1  (1 lines)
  int__sample2  (1 lines)
  int__sample3  (2 lines)
  iq__sample1  (2 lines)
  iq__sample2  (9 lines)
  iq__sample3  (6 lines)
```

詳細ログは `samples_run_outputs/*.log` (gitignored)。

## 既存テスト・サンプルへの回帰

- 単体テスト: 27 / 27 PASS
- 既存 33 .abcl: 33 / 33 PASS
- 既存 21 .aipl (Phase A-G): 21 / 21 PASS

全 24 + 81 = **105 / 105 サンプル + テスト PASS**。
