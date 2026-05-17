# Phase E-β — actor field 型推論

**日付:** 2026-05-17
**前段:** [Phase E-α REPORT](./PHASE_E_REPORT.md)
**関連ファイル:**
- `src/python-aipl/aipl_inference.py` (+60 行: `class_fields`, pre-pass, `FieldAccess`/`FieldAssign`, init-env)
- `src/python-aipl/aipl_main.py` (+15 行: class fields の表示)
- `samples/feature_d_actorfields/sample{1,2,3}.aipl` (新規)

---

## 1. 目的

Phase D-1 で method 越境推論を、Phase E-α で refinement を導入した。Phase E-β では **同一クラスの複数 method 間で field の型を共有・整合性検査**する。

Phase D 以前は `var n = 0;` の field 型は **method ごと** に initializer から再導出され、ある method が `n = "hello";` と書いて別の method が `n + 1` と読んでも検出できなかった。E-β では class field ごとに 1 つの TVar を共有し、すべての usage が同じ slot を constrain する。

## 2. 設計

### 2.1 共有 TVar (`infer.class_fields`)

```python
class_fields: Dict[str, Dict[str, Any]] = field(default_factory=dict)
```

`class_fields[ClassName][field_name] = TVar`。Pre-pass で全 class field に fresh TVar を割り当てる。

### 2.2 初期値の constrain

field 初期化式の type は、専用の `init_env` で推論する (`init_env` には同一 class の他 field も bind 済みなので forward reference が効く)。推論結果を field TVar と constrain。`type_annotation` (例: `var n: Int = 0;`) があれば併せて constrain。

### 2.3 method 内 binding 統一

`_run_method_pass` で `cls_env.bind(fname, Scheme((), ftvar))` — **fresh TVar ではなく Pre-pass で共有したものをそのまま渡す**。これにより:

- `n = initial` (Assign) → 既存の Assign 推論ロジックが `env.lookup("n")` で shared TVar を取得し、`initial` の型と constrain
- `reply(n)` (CallStmt/Var) → 同じ shared TVar が return type に流れる
- 別 method で `n + delta` → 同 TVar が Int に絞られ、すべての method に伝播

### 2.4 外部からの `obj.field` アクセス

`FieldAccess(name=obj, attrs=[f])` を Dyn でなく:

1. `env.lookup(obj)` で receiver の TCon を取得
2. `class_fields[ClassName][f]` を返す

`obj.f = v` (FieldAssign) も同様に field TVar と RHS の type を constrain。深さ 2 以上のチェイン (`obj.a.b`) は引き続き Dyn (record vs nested actor の判別が困難なため)。

### 2.5 表示

`aipl_main.py --infer` の末尾に `class fields` セクションを追加。`InferenceResult[0]._infer_state` で driver の状態を返し、CLI 側で `apply(subst, tvar)` して表示。

## 3. サンプル実行手順

```sh
PY=/opt/homebrew/bin/python3
AIPL=src/python-aipl/aipl_main.py
```

### 3.1 sample1_simple.aipl — 初期値+書き込み+読み出しの全部入り

```sh
$PY $AIPL samples/feature_d_actorfields/sample1_simple.aipl --infer
```

期待出力:

```
=== Counter.init ===
  params:
    initial : Int
  return : δ
=== Counter.bump ===
  params:
    delta : Int
  return : Int
...
=== class fields ===
  Counter:
    n : Int

[infer] 4 method(s), 0 unify issue(s), 0 refinement issue(s)
```

ポイント: `init(initial)` の `initial` も Int に推論される ← `n = initial` で `n` が Int だから。

### 3.2 sample2_inferred_from_writes.aipl — actor 3 つの連鎖で field 型確定

```sh
$PY $AIPL samples/feature_d_actorfields/sample2_inferred_from_writes.aipl --infer
```

期待出力 (抜粋):

```
=== Bridge.feed ===
  params:
    s : Source
    k : Sink
  return : Int
  locals:
    v : Int
    r : Int

=== class fields ===
  Sink:
    stored : Int
```

`Sink.stored : Int` は **どの method の initializer も Int を保証しない** にも関わらず、`Bridge.feed(s, k)` で `v = now s.value(); now k.put(v)` のチェインを通って Source → Bridge → Sink の 3 actor 越境で確定する。

### 3.3 sample3_conflict.aipl — 型衝突検出

```sh
$PY $AIPL samples/feature_d_actorfields/sample3_conflict.aipl --infer
```

期待出力 (末尾):

```
=== Mixed.writeBool ===
  params:
    b : Bool
  return : η
  issues:
    [unify] cannot unify Int with Bool  at assign to s

=== class fields ===
  Mixed:
    s : Int

[infer] 3 method(s), 1 unify issue(s), 0 refinement issue(s)
```

`s` は initializer + `asInt()` 経由で Int に絞られる。`writeBool(b: Bool)` が `s = b` でこれに違反 → `at assign to s` の場所で unify failure を報告。**Phase D 以前は完全に見逃していた typo**。

### 3.4 既存全 sample 回帰

| Suite | 結果 |
|---|---|
| `src/python-aipl/samples/*.abcl` (33 件) | 33/33 PASS |
| `samples/feature_a_hm/*.aipl` (3 件) | 全 `0 unify, 0 refinement` |
| `samples/feature_b_crossclass/*.aipl` (3 件) | 全 `0 unify, 0 refinement` |
| `samples/feature_c_refinement/*.aipl` (3 件) | 9/9 期待通り (SAT 5 / UNSAT 4 / Mixed 4+2) |

## 4. 制限事項

- 深さ 2 以上の field チェイン (`obj.a.b`) は依然 Dyn (構造的 record と actor field の区別が必要)
- 外部からの `obj.field = v` 代入は AIPL の owned 制約と相互作用しうるが、Phase E-β では型整合のみ検査 (Phase 15 の symbol_owned との統合は別 task)
- `pub` フィールドと private フィールドを CLI 表示で区別しない

## 5. 規模

| 部分 | LOC |
|---|---:|
| aipl_inference.py (`class_fields` + 3 pass extension + FieldAccess/Assign) | +60 |
| aipl_main.py (class fields 表示) | +15 |
| sample 3 件 | +90 |
| **合計** | **+165** |

## 6. 結論

| 項目 | 結果 |
|---|---|
| 同一 class 内 field の cross-method 推論 | ✓ Counter.n が initializer+init()+bump() で Int に絞られる |
| 3-actor 越境 field 推論 | ✓ Sink.stored が Source→Bridge→Sink 連鎖で Int |
| 型衝突検出 | ✓ Int field への Bool 書き込みを unify issue で報告 |
| 既存 33 + 9 sample 回帰 | ✓ 全 PASS |

Phase D-1 の「method 越境」、Phase E-α の「refinement」、Phase E-β の「field 共有」で、AIPL Python 版の型推論は **actor 全要素 (param/return/local/field) の cross-class HM + refinement** という閉じた系に到達した。

---

## 参考

- [Phase C REPORT](./PHASE_C_REPORT.md)
- [Phase D REPORT](./PHASE_D_REPORT.md)
- [Phase E-α REPORT](./PHASE_E_REPORT.md)
- `src/python-aipl/aipl_inference.py` 〜1100 行
