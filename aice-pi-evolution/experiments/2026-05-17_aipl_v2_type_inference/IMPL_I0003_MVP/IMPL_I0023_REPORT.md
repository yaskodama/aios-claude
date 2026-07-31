# AIPL v2 Distributed — I0023 hang-resilience MVP (quarantine_and_skip)

**日付:** 2026-05-18
**前段:** [IMPL_INTEGRATION_REPORT.md](./IMPL_INTEGRATION_REPORT.md) (I0003 MVP + I-5/I-6/I-7 統合)
**雛型:** Run 2 hang_resilience_first シナリオ勝者 I0023 (win-rate 83%)
**動機:** PsiLang v3 trial #1 で OpenAI SDK silent hang により 35/38 個体喪失 — 1 actor の停滞を全体に波及させない設計

---

## 1. 雛型 I0023 の遺伝子と MVP 達成度

| 遺伝子軸 | I0023 値 | MVP 達成 |
|---|---|---|
| scheduler_model | cost_weighted_routing | 既存 `aipl_ai` の cost 推定で代替可、未統合 |
| failover_policy | **multi_model_fallback** | **既存** `ABCL_AI_FALLBACK_MODELS` で達成 (アクション不要) |
| actor_placement | cluster_with_scheduler | I-6 (route_for) で部分カバー、true placement は I0036 |
| actor_addressing | actor_id_with_resolver | I0003 MVP で既存 `aipl_remote.set_actor_lookup` 代替済 |
| lineage_replication | append_only_distributed_log | I-2 NDJSON ログで近似カバー |
| **supervisor_strategy** | **quarantine_and_skip** | ✅ **新規実装** (本 phase) |
| message_serialization | in_memory_pyobj | 単一プロセス前提のため不要 |
| opt_in_annotation_style | env_var_routing | I-1 で実装済 |
| observability_layer | opentelemetry_traces | I-2 NDJSON で代替 |
| ai_provider_abstraction | cost_aware_provider_router | 既存で代替可 |
| rebalancing_trigger | never | 静的設計、不要 |

**真に新規実装が必要だったのは `quarantine_and_skip` の 1 軸のみ**。

## 2. 実装

### 2.1 aipl_dist.py への追加 (+95 LOC)

| 関数 | 役割 |
|---|---|
| `quarantine_actor(name, ttl=None)` | actor を TTL 秒間 quarantine に登録 |
| `is_quarantined(name)` | 現在 quarantine 中か (期限切れは pruning 込み) |
| `clear_quarantine(name)` | 手動解除 |
| `quarantine_status()` | dict[name → expires_at] snapshot |
| `quarantine_ttl()` | `AIPL_DIST_QUARANTINE_TTL` (default 60s) |

すべて `is_enabled() == False` で no-op。スレッドセーフ (`_QUARANTINE_LOCK`)。

### 2.2 既存ファイルへの hook (+15 LOC)

| ファイル | hook |
|---|---|
| `aipl_interp.dispatch` | 冒頭で `is_quarantined(actor.name)` → True なら method 呼出を skip、reply_future に None set |
| `aipl_runtime.Actor._run` (except 内) | 既存の error 表示直後に `quarantine_actor(self.name)` を auto-fire |

両 hook とも `try/except` ラップで `aipl_dist` import 失敗を吸収、`AIPL_DIST_ENABLE` unset で完全 no-op。

## 3. 検証

### 3.1 単体テスト

`tests/test_aipl_dist.py` に 4 個追加 (合計 19 個):

```
PASS  quarantine disabled returns False
PASS  quarantine marks and clears
PASS  quarantine expires after TTL
PASS  quarantine custom ttl override

19/19 passing
```

### 3.2 quarantine_demo.aipl で end-to-end 検証

```aipl
class Flaky { method boom() { var x = 1/0; reply(x); } }
class Driver {
  method run() {
    var f = new Flaky();
    var a = now f.boom();     // 1st: fails -> quarantine fires
    var b = now f.boom();     // 2nd-4th: skipped silently
    var c = now f.boom();
    var d = now f.boom();
    println("done");
    reply(0);
  }
}
var dr = new Driver(); var rc = now dr.run();
```

実行 (`AIPL_DIST_ENABLE=1 AIPL_DIST_QUARANTINE_TTL=2 AIPL_DIST_LOG_FILE=/tmp/qlog.ndjson`):

```
stderr: [actor f.boom] error: division by zero    ← 1 回だけ
stdout: done                                       ← Driver は最後まで完走
```

NDJSON log (`/tmp/qlog.ndjson`):

```json
{"event": "actor_spawn", "actor": "f", "cls": "Flaky"}
{"event": "actor_quarantined", "actor": "f", "ttl": 2.0, "expires": ...}
{"event": "actor_skip_quarantined", "actor": "f", "method": "boom"}
{"event": "actor_skip_quarantined", "actor": "f", "method": "boom"}
{"event": "actor_skip_quarantined", "actor": "f", "method": "boom"}
```

`actor_quarantined: 1`、`actor_skip_quarantined: 3` — 設計通り。

### 3.3 既存 sample 回帰

| Suite | PASS |
|---|---|
| `src/python-aipl/samples/*.aipl` (33 件) | **33/33** |
| `samples/feature_*/*.aipl` (21 件) | **21/21** |
| 単体テスト | **19/19** |

`AIPL_DIST_ENABLE` unset で完全 backward-compat (= 既存挙動と区別不能)。

## 4. PsiLang v3 silent hang シナリオへの効果 (仮想シミュレーション)

v3 で発生した「1 OpenAI SDK call が deadlock → 35/38 個体喪失」のシナリオで本実装が動くと:

1. 個体 #4 の評価で actor `reviewer4` の OpenAI call が hang
2. `AIPL_AI_REQUEST_TIMEOUT=60` で SDK が例外を投げる
3. `aipl_runtime.Actor._run` の except → `quarantine_actor("reviewer4", ttl=60)`
4. 後続の `now reviewer4.score(...)` 全 30 個は `actor_skip_quarantined` で即座に None reply
5. 親 actor は 30 個の None を受け取って次の reviewer に流れる
6. **35/38 喪失ではなく ~3/38 喪失** (quarantine された個体の reviewer 部分だけ欠落) で済む

実測しないと厳密な数字は出ないが、設計上は 1 actor のハングを actor 単位で隔離して全体に波及させない構造になっている。

## 5. 規模

| 部分 | LOC |
|---|---:|
| aipl_dist.py (前 phase = 331) | 331 |
| aipl_dist.py (本 phase 追加: quarantine 関数群) | +95 |
| aipl_interp.dispatch hook | +12 |
| aipl_runtime.Actor._run hook | +7 |
| unit tests (4 個追加) | +50 |
| quarantine_demo.aipl | +24 |
| IMPL_I0023_REPORT.md (this) | (doc) |
| **本 phase 純増** | **~188** |

aipl_dist.py 合計: 331 + 95 = **426 LOC**。`AIPL_DIST_ENABLE=0` での副作用は依然ゼロ。

## 6. 結論

| 項目 | 結果 |
|---|---|
| `quarantine_and_skip` supervisor を新規実装 | ✅ |
| `aipl_interp.dispatch` + `aipl_runtime.Actor._run` への opt-in hook | ✅ +19 LOC |
| 単体テスト (4 新規 + 15 既存 = 19) | ✅ 19/19 PASS |
| End-to-end .aipl サンプル (`quarantine_demo.aipl`) | ✅ 期待通り 1 fail + 3 skip + done |
| 既存 33 .aipl + 21 .aipl 回帰 | ✅ 54/54 PASS |
| I0023 11 軸中 1 軸 (quarantine) を実装、6 軸を既存機能でカバー | ✅ |

**I0023 (hang resilience) は MVP として完成**。残る軸 (multi_process placement / true cluster scheduling) は I0036 系の作業に持ち越し。

## 7. 次の自然なステップ

- **I0036 (Erlang OTP) MVP**: `quorum_replicate` + `multi_process_local` + gRPC など 5 軸の本格分散 (~1000 LOC)
- **I-7 を実 LLM call で実測**: AIActor.aipl + 実 OpenAI key + RPM=10 で rate-limit シミュレーション
- **PsiLang v3 を quarantine 付きで再走**: 実データで 35/38 喪失が改善されるか実測

---

## 参考

- 前段: [IMPL_INTEGRATION_REPORT.md](./IMPL_INTEGRATION_REPORT.md)、[IMPL_RUN_REPORT.md](./IMPL_RUN_REPORT.md)
- 設計: [IMPL_DESIGN.md](./IMPL_DESIGN.md)
- 雛型由来: [PHASE_E_DISTRIBUTED_RUN_REPORT.md §9.6](../PHASE_E_DISTRIBUTED_RUN_REPORT.md#96-run-2-のシナリオ別チャンピオン-3-種) (I0023 = hang_resilience 勝者)
- 実装: `src/python-aipl/aipl_dist.py` (331 → 426 LOC)
- hook: `src/python-aipl/aipl_interp.py`、`src/python-aipl/aipl_runtime.py`
- sample: `samples/quarantine_demo.aipl`
- tests: `tests/test_aipl_dist.py` (19 個)
