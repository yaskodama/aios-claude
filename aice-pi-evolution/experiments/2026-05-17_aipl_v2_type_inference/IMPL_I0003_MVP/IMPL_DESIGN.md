# AIPL v2 Distributed — I0003 MVP 実装設計

**日付:** 2026-05-18
**雛型:** Run 2 balanced シナリオ勝者 I0003 (composite=0.548, win-rate=83%)
**前段:** [Run 2 レポート](../PHASE_E_DISTRIBUTED_RUN_REPORT.md#9-run-2-r6-緩和版-仕様-v030)

---

## 1. 雛型: I0003 の遺伝子

| 軸 | 値 | 実装可否 |
|---|---|---|
| `scheduler_model` | `token_budget_aware` | ✅ MVP 対象 (I-3) |
| `failover_policy` | `same_provider_retry` | 既存に近い (調整で済む) |
| `actor_placement` | `local_thread_pool` | 既存 actor 系を活用 |
| `actor_addressing` | `actor_id_with_resolver` | 既存 `aipl_remote.set_actor_lookup` を流用 |
| `lineage_replication` | `append_only_distributed_log` | MVP では単一 file へ ND-JSON append のみ |
| `supervisor_strategy` | `checkpoint_and_resume` | ✅ MVP 対象 (I-4) |
| `message_serialization` | `json_over_tcp` | MVP では使わない (single-process 動作で十分) |
| **`opt_in_annotation_style`** | **`no_annotation_runtime_only`** (env_var_routing でも可) | ✅ MVP 対象 (I-1) |
| `observability_layer` | `structured_log` | ✅ MVP 対象 (I-2) |
| `ai_provider_abstraction` | `tier_aware_router` | I-3 と併設 |
| `rebalancing_trigger` | `never` | 静的 (動的調整なし) |

## 2. MVP スコープ

「I0003 を全部実装」は ~500 LOC 想定。MVP として **4 piece** に絞る:

| Phase | 機能 | 目的 | 想定 LOC |
|---|---|---|---:|
| **I-1** | `env_var_routing` | backward-compat の核 (.aipl 構文不変) | ~50 |
| **I-2** | `structured_log` | 観測性。debug を構造的に | ~80 |
| **I-3** | `token_budget_aware` scheduling | RPM/TPM を見た rate-limit | ~150 |
| **I-4** | `checkpoint_and_resume` | actor 死亡時の file checkpoint 復帰 | ~120 |
| **合計** | — | — | **~400** |

残り (failover, lineage_repl, actor_placement, addressing, message_serialization, rebalancing) は MVP 後の選択肢として残す。

## 3. アーキテクチャ: 既存ファイル無改変原則

- **既存 `src/python-aipl/*.py` を 1 行も変更しない**
- 新規モジュール `src/python-aipl/aipl_dist.py` (~400 LOC) に全機能を閉じ込める
- アクティベーションは **完全に env var 駆動**:
  | env var | 機能 | デフォルト |
  |---|---|---|
  | `AIPL_DIST_ENABLE` | 1 で aipl_dist 機能群を起動 | `0` (= 完全 OFF) |
  | `AIPL_DIST_LOG_FILE` | ND-JSON ログの出力先 | unset (= 無効) |
  | `AIPL_DIST_TPM` | 1 分あたり許可トークン数 | unset (= 無制限) |
  | `AIPL_DIST_RPM` | 1 分あたり許可呼び出し数 | unset (= 無制限) |
  | `AIPL_DIST_CHECKPOINT_DIR` | actor checkpoint 保存ディレクトリ | unset (= 無効) |
  | `AIPL_ROUTE` | actor 名 → ノードルーティング (未来用、MVP では parse のみ) | unset |

- `AIPL_DIST_ENABLE != 1` のときは **絶対に何もしない** (import するだけで副作用なし)
- 既存サンプル 33 .abcl + 21 .aipl は env なしで PASS する必要あり (= 既存テストの回帰なし)

## 4. ファイル配置

```
src/python-aipl/
├── aipl_dist.py            (new, ~400 LOC)
├── aipl_dist_log.py        (new, structured_log helper, ~80 LOC)  ※ aipl_dist.py に統合する可能性
├── aipl_dist_checkpoint.py (new, file-based actor state save/restore, ~120 LOC)  ※ 同上
└── (既存ファイル 全部無改変)

aice-pi-evolution/experiments/2026-05-17_aipl_v2_type_inference/IMPL_I0003_MVP/
├── IMPL_DESIGN.md           (this file)
├── IMPL_RUN_REPORT.md       (running report; updated as each phase completes)
├── samples/
│   ├── env_var_routing/     (I-1 サンプル)
│   ├── structured_log/      (I-2 サンプル)
│   ├── token_budget/        (I-3 サンプル)
│   └── checkpoint/          (I-4 サンプル)
└── tests/
    └── test_aipl_dist.py    (回帰テスト一式)
```

シンプルさを優先するなら全部 1 ファイルに、保守性を優先するなら 3 ファイルに分割。MVP は **1 ファイル `aipl_dist.py`** で始めて、肥大化したら分割する。

## 5. 各 Phase の API 設計

### I-1: env_var_routing

```python
# aipl_dist.py
def is_enabled() -> bool:
    return os.environ.get("AIPL_DIST_ENABLE", "0") == "1"

def route_for(actor_name: str) -> Optional[str]:
    """`AIPL_ROUTE=Reviewer:fast,Worker:slow` を読んで actor → tag を返す.
    MVP では tag は parse して返すだけ. 実際の placement 切替は I0036 案."""
    if not is_enabled(): return None
    table = os.environ.get("AIPL_ROUTE", "")
    if not table: return None
    for spec in table.split(","):
        if ":" in spec:
            name, tag = spec.split(":", 1)
            if name.strip() == actor_name:
                return tag.strip()
    return None
```

### I-2: structured_log

```python
def log_event(event: str, **fields) -> None:
    """ND-JSON 1 行を AIPL_DIST_LOG_FILE に append.
    AIPL_DIST_LOG_FILE が unset または AIPL_DIST_ENABLE != 1 のとき no-op."""
    if not is_enabled(): return
    path = os.environ.get("AIPL_DIST_LOG_FILE", "")
    if not path: return
    rec = {"ts": time.time(), "event": event, **fields}
    with open(path, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
```

### I-3: token_budget_aware scheduling

```python
_TOKEN_BUDGET_GATE = None    # lazy

def token_budget_gate() -> "TokenBudgetGate":
    """AIPL_DIST_TPM, AIPL_DIST_RPM を読んで 60 秒スライディング窓で gate."""
    global _TOKEN_BUDGET_GATE
    if _TOKEN_BUDGET_GATE is None:
        tpm = int(os.environ.get("AIPL_DIST_TPM", "0"))
        rpm = int(os.environ.get("AIPL_DIST_RPM", "0"))
        _TOKEN_BUDGET_GATE = TokenBudgetGate(tpm=tpm, rpm=rpm)
    return _TOKEN_BUDGET_GATE

# aipl_ai.py の call_ai を **wrapper で** 呼ぶ:
def call_ai_with_budget(prompt: str, **kw) -> str:
    if is_enabled():
        token_budget_gate().acquire(estimated_tokens=len(prompt) // 4)
    return aipl_ai.call_ai(prompt, **kw)
```

⚠️ `aipl_ai.call_ai` 自体は変更しない。利用者は `aipl_dist.call_ai_with_budget` を opt-in で使う。`AIPL_DIST_ENABLE != 1` なら no-gate で `call_ai` を素通し。

### I-4: checkpoint_and_resume

```python
def checkpoint_dir() -> Optional[str]:
    if not is_enabled(): return None
    return os.environ.get("AIPL_DIST_CHECKPOINT_DIR", "") or None

def save_actor_state(actor_name: str, state: dict) -> bool:
    d = checkpoint_dir()
    if not d: return False
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{actor_name}.json")
    with open(p, "w") as f:
        json.dump({"ts": time.time(), "state": state}, f, ensure_ascii=False)
    return True

def restore_actor_state(actor_name: str) -> Optional[dict]:
    d = checkpoint_dir()
    if not d: return None
    p = os.path.join(d, f"{actor_name}.json")
    if not os.path.exists(p): return None
    with open(p) as f:
        return json.load(f).get("state")
```

MVP では「呼んだら効く」API。AIPL ランタイムへの自動統合は別フェーズ。

## 6. 回帰テスト

| 観点 | 検証 |
|---|---|
| 既存 .abcl 33 件 | env なしで PASS |
| 既存 .aipl 21 件 | env なしで PASS |
| --check 全 PASS (= type/infer) | 影響なし |
| `AIPL_DIST_ENABLE=0` (default) | aipl_dist の import で副作用ゼロ |
| 単体テスト | 4 piece 個別 |

## 7. 完了条件

- [ ] `src/python-aipl/aipl_dist.py` 〜400 LOC
- [ ] I-1〜I-4 各々の最小サンプル (.aipl 4 件)
- [ ] tests/test_aipl_dist.py の小テスト集
- [ ] 既存 33 .abcl + 21 .aipl の回帰 100% PASS
- [ ] IMPL_RUN_REPORT.md に実装内容と LOC + 走行ログ

## 8. 含意 / 残課題

- I0023 / I0036 への拡張は本 MVP 完成後に検討
- `failover_policy = same_provider_retry` は既存 `_client_max_retries` で実質達成済 → MVP では追加実装不要
- `actor_addressing = actor_id_with_resolver` も既存 `aipl_remote.set_actor_lookup` で代替可
- 真の分散 (multi_process / multi_node) は I0023 / I0036 担当
