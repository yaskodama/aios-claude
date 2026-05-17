# AIPL v2 Distributed — I0003 MVP × 既存ランタイム統合 (I-5/I-6/I-7)

**日付:** 2026-05-18
**前段:** [IMPL_RUN_REPORT.md](./IMPL_RUN_REPORT.md) (I0003 MVP 単体実装)
**目的:** `aipl_dist.py` (library) を AIPL ランタイムから自動呼び出しできるように接続。`AIPL_DIST_ENABLE=0` (デフォルト) では既存挙動完全維持。

---

## 1. 統合点 (3 箇所)

| ID | ファイル | 変更内容 | 行数 |
|---|---|---|---:|
| **I-5+I-6** | `src/python-aipl/aipl_interp.py` (`spawn_actor`) | 既存 `_state_snapshot` 直後に aipl_dist hook を挿入。`restore_actor_state` でフィールド上書き、`route_for` で routing tag を log、`actor_spawn` イベントも emit | **+14** |
| **I-7** | `src/python-aipl/aipl_ai.py` (`call_ai`) | 既存 `_get_concurrency_gate()` 直後に `aipl_dist.token_budget_gate()` を opt-in で挟む。RPM/TPM スライディング窓で `acquire(est_tokens)` | **+13** |
| **合計** | — | — | **+27** |

全 hook は `try/except` でラップ。`AIPL_DIST_ENABLE` unset で `aipl_dist.is_enabled() == False` → 全関数が即 None/False 返す → 既存挙動と完全同一。

## 2. 検証結果

### 2.1 既存サンプル回帰 (AIPL_DIST_ENABLE unset, mock provider)

| Suite | 件数 | PASS | FAIL |
|---|---:|---:|---:|
| `src/python-aipl/samples/*.abcl` | 33 | **33** | 0 |
| `samples/feature_*/*.aipl` (Phase A-G) | 21 | **21** | 0 |
| **合計** | **54** | **54** | **0** |

### 2.2 単体テスト

```
15/15 passing  (tests/test_aipl_dist.py)
```

### 2.3 End-to-end demo (`samples/end_to_end_demo.aipl`)

純粋な `.aipl` プログラム (aipl_dist の呼び出し記述ゼロ)。env var だけで全 4 機能が auto-fire。

**Pass 1: fresh run** (counter n=0 → bump 10):
```sh
$ AIPL_AI_PROVIDER=mock AIPL_DIST_ENABLE=1 \\
  AIPL_DIST_LOG_FILE=/tmp/log AIPL_ROUTE="counter:hot" \\
  AIPL_DIST_CHECKPOINT_DIR=/tmp/ck \\
  python3 src/python-aipl/aipl_main.py end_to_end_demo.aipl
counter result: 10
```

**checkpoint 注入** (`n=500`)、**Pass 2: 再実行**:
```sh
counter result: 510   ←  500 + 10 = 510  (checkpoint 復元が効いている)
```

**自動生成された NDJSON ログ** (Pass 2):
```json
{"event": "actor_spawn", "actor": "AI", "cls": "AI", ...}
{"event": "checkpoint_restore", "actor": "counter", "path": "/tmp/ck/counter.json", "ts_saved": ...}
{"event": "actor_routed", "actor": "counter", "cls": "Counter", "tag": "hot"}
{"event": "actor_spawn", "actor": "counter", "cls": "Counter", ...}
{"event": "actor_spawn", "actor": "reporter", "cls": "Reporter", ...}
```

→ 3 機能 (I-5 checkpoint / I-6 routing log / I-2 structured_log) が **AIPL ソース無変更** で同時発火。

## 3. backward-compat の二重ロック

| 防衛層 | 仕組み |
|---|---|
| **層 1**: aipl_dist 側 | `is_enabled()` が `AIPL_DIST_ENABLE != "1"` のとき全関数を no-op |
| **層 2**: hook 側 | `try/except` で aipl_dist の import 失敗・例外を全部黙殺 |
| **層 3**: 既存値域不変 | hook が actor.fields に書く値は type guard あり (int/float/bool/str のみ) — 既存 `_state_snapshot` と同じ規約 |

最悪 `aipl_dist.py` を物理削除しても、`try: import aipl_dist; ...` が ImportError を捕捉して既存挙動に落ちる。

## 4. 既知の制限

1. **`init()` の優先**: 既存 `_state_snapshot` 同様、checkpoint の field 復元は actor spawn 直後に行われるが、その後に `init(args)` が呼ばれると上書きされる。`init` を持たないクラスでのみ完全復元が効く。`end_to_end_demo.aipl` はこれを意図して `init` を外している。
2. **routing tag の効果**: I-6 は routing tag を **log するだけ**。実際の actor placement 切替は I0036 系の実装で。
3. **I-7 の token 見積もり**: `max(1, len(prompt)//4 + max_tokens)` の粗い見積。実 token は SDK 経由でしか取れないため、より精密な値で window を更新する path は別途必要。

## 5. 規模

| 部分 | LOC |
|---|---:|
| aipl_dist.py (前 phase) | 331 |
| aipl_interp.py (+I-5/I-6 hook) | +14 |
| aipl_ai.py (+I-7 hook) | +13 |
| end_to_end_demo.aipl | +25 |
| **既存ファイルへの total addition** | **+27** |
| **新規 LOC total (incl. samples + tests + docs)** | **〜400** |

設計上限 (~95 LOC for integration) より大幅に少ない 27 LOC で達成。

## 6. 結論

| 項目 | 結果 |
|---|---|
| I-5 checkpoint restore 自動呼び出し | ✅ `spawn_actor` に統合 |
| I-6 route_for を spawn-time に log | ✅ `actor_routed` event |
| I-7 budget gate を `call_ai` に opt-in 統合 | ✅ |
| 既存 33+21 サンプル回帰 | ✅ 54/54 PASS |
| 単体テスト 15/15 | ✅ |
| End-to-end demo (.aipl 1 ファイルで 3 機能発火) | ✅ |
| 既存ファイル変更行数 | +27 |
| `AIPL_DIST_ENABLE=0` で完全 backward-compat | ✅ 二重ロック |

**I0003 (balanced) MVP は library + runtime 統合まで完走**。`AIPL_DIST_ENABLE=1` をセットするだけで AIPL プログラム本体を変更せずに観測性・レート制御・チェックポイントを得る形になった。

## 7. 次の自然なステップ

- **I-7 を実 LLM 呼び出しで exercise**: 既存 AI サンプル (AIActor, MultiProvider) で `AIPL_DIST_RPM=N` を設定して動作確認
- **I0023 (hang resilience) MVP**: `quarantine_and_skip` supervisor + `cluster_with_scheduler` placement の雛型 (~500 LOC)
- **I0036 (Erlang OTP) MVP**: `quorum_replicate` + `restart_subtree` + `multi_process_local` + gRPC (~1000 LOC)

---

## 参考

- 前段: [IMPL_RUN_REPORT.md](./IMPL_RUN_REPORT.md)
- 設計: [IMPL_DESIGN.md](./IMPL_DESIGN.md)
- 実装: `src/python-aipl/aipl_dist.py` (331 LOC)
- hook: `src/python-aipl/aipl_interp.py` (+14)、`src/python-aipl/aipl_ai.py` (+13)
- 統合 demo: `samples/end_to_end_demo.aipl`
- 探索由来: [PHASE_E_DISTRIBUTED_RUN_REPORT.md §9.6](../PHASE_E_DISTRIBUTED_RUN_REPORT.md#96-run-2-のシナリオ別チャンピオン-3-種)
