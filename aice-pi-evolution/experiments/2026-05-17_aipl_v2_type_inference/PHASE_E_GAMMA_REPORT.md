# Phase E-γ — record / field-access の structural typing (E-1)

**日付:** 2026-05-17
**前段:** [Phase E-β REPORT](./PHASE_E_BETA_REPORT.md)
**関連ファイル:**
- `src/python-aipl/aipl_inference.py` (+50 行: RecordLit / FieldAccess / unify(TRecord, TRecord) / VarDecl の generalise 抑制 / global re-pass)
- `samples/feature_e_records/sample{1,2,3}.aipl` (新規)

---

## 1. 目的

Phase E-β までは `RecordLit` (`{a: 1, b: true}`) と record への `FieldAccess` (`r.a`) はすべて `T_DYN` 扱いだった (PHASE_E_REPORT.md §5 の E-1 候補)。Phase E-γ ではこれを以下の構造的型に格上げする:

- record literal: `{a: T1, b: T2, ...}` を `TRecord((a, T1), (b, T2), ...)`
- field access `r.a`: receiver の TRecord から該当 field の型を返す
- TVar receiver: `TVar → TRecord((a, η))` の constraint を伸ばす → 用法から構造を推論
- shape mismatch: 同じ param TVar に異なる field set の record を渡したら `[unify] record fields differ` を報告

## 2. 設計

### 2.1 RecordLit の推論

```python
if RecordLit and isinstance(e, RecordLit):
    ftypes = [(fname, _infer_expr(infer, env, fexpr))
              for fname, fexpr in e.fields]
    ftypes.sort(key=lambda x: x[0])
    return TRecord(tuple(ftypes))
```

field 名でソートして order independence を確保 (`{a: 1, b: 2}` と `{b: 2, a: 1}` は同じ TRecord)。

### 2.2 FieldAccess の推論

```python
sch = env.lookup(e.name)
cur = apply(subst, instantiate(infer, sch))
for attr in e.attrs:
    if isinstance(cur, TCon):       # actor class field (E-3 path)
        cur = infer.class_fields[cur.name][attr]
    elif isinstance(cur, TRecord):  # E-1: structural field lookup
        cur = dict(cur.fields)[attr]   # missing -> field issue + Dyn
    elif isinstance(cur, TVar):     # E-1: constrain TVar to record
        ft = infer.fresh()
        infer.constrain(cur, TRecord(((attr, ft),)))
        cur = ft
return apply(subst, cur)
```

TVar からの逆推論: `r.head` の access が `r : TRecord((head, η))` を要求 → caller が `{head: 7, tail: 0}` を渡すと unify で `η = Int` になり、関連 field 型が定まる。

### 2.3 unify(TRecord, TRecord)

```python
if isinstance(t1, TRecord) and isinstance(t2, TRecord):
    d1, d2 = dict(t1.fields), dict(t2.fields)
    if set(d1.keys()) != set(d2.keys()):
        raise UnifyError(f"record fields differ: ...")
    for name in sorted(d1.keys()):
        s = compose(unify(...), s)
    return s
```

**現状は exact field-set マッチのみ**。width subtyping (`{a, b}` を `{a}` パラメータに渡せる) は E-1+ 課題。

### 2.4 generalise の抑制 (致命的修正)

Phase E-β 以前は `var p = now d.makePoint(3, 4)` で:

```python
env.bind(s.name, generalise(env, apply(subst, rhs_t)))
```

を実行していた。`rhs_t` は makePoint の ret_tvar (fresh TVar、Pass 1 で TRecord に bind される予定)。`generalise` がこの TVar を量化して `Scheme((ρ,), ρ)` にし、後続の `now d.takeX(p)` で `instantiate` すると **fresh な別 TVar σ** が生まれ、p のソースである ρ との繋がりが切れる。

結果: Pass 1 で ρ = TRecord と確定しても σ は影響を受けず、`takeX` の param 型は `{a: η}` (TVar constraint だけ) のまま。

修正:

```python
env.bind(s.name, Scheme((), apply(infer.subst, rhs_t)))
```

actor の戻り値は monomorphic にし、量化しない。これで rhs_t が後で TRecord に bind されると、p の Scheme もそれに従う。AIPL の actor 系は元々 monomorphic なので意味論的にも自然。

### 2.5 Global 再走で実 unify issue を浮上

Pass 0 の issues は forward-ref のノイズを抑えるため drop していた (line 1169)。これだと Pass 0 で起きた **本物の** unify failure (record shape mismatch など) も消えてしまう。修正: Pass 2 後にもう 1 回 global を走らせ、unify / arity / field 系の issue だけ残す。

```python
issues_before_repass = len(infer.issues)
for decl ... GlobalStmt: _infer_stmt(infer, env, decl.stmt)
repass = infer.issues[issues_before_repass:]
infer.issues = infer.issues[:issues_before_repass] + [
    i for i in repass if i.kind in ("unify", "arity", "field")
]
```

forward-ref 由来の `unbound` は引き続き drop される。

## 3. サンプル実行手順

```sh
PY=/opt/homebrew/bin/python3
AIPL=src/python-aipl/aipl_main.py
```

### 3.1 sample1_basic.aipl

```sh
$PY $AIPL samples/feature_e_records/sample1_basic.aipl --infer
```

期待出力:

```
=== Geometry.makePoint ===
  return : {a: Int, b: Int}
=== Geometry.dx ===
  params:
    p : {a: Int, b: Int}
    q : {a: Int, b: Int}
  return : Int
...
[infer] 3 method(s), 0 unify issue(s), 0 refinement issue(s)
```

record literal の型が precise に表示され、`dx(p, q)` の両 param が `{a:Int, b:Int}` に推論される。

### 3.2 sample2_inferred_from_use.aipl

```sh
$PY $AIPL samples/feature_e_records/sample2_inferred_from_use.aipl --infer
```

`Reader.first(r)` は内部で `r.head` しか触らない。caller が `{head: 7, tail: 100}` を渡すと、param 型が **caller の record で全 field 込みの shape** に確定する:

```
=== Reader.first ===
  params:
    r : {head: Int, tail: Int}
  return : Int
```

### 3.3 sample3_conflict.aipl

```sh
$PY $AIPL samples/feature_e_records/sample3_conflict.aipl --infer
```

同じ `process(r)` に `{key:Int, val:Int}` と `{key:Int, label:Bool}` を続けて渡す → 2 回目の constrain が unify 失敗:

```
=== Engine.process ===
  params:
    r : {key: Int, val: Int}
  ...
  issues:
    [unify] record fields differ: ['key', 'label'] vs ['key', 'val']  at Engine.process arg

[infer] 1 method(s), 1 unify issue(s), 0 refinement issue(s)
```

shape mismatch を場所付きで報告。

### 3.4 全 15 sample (回帰)

| Suite | PASS |
|---|---|
| `src/python-aipl/samples/*.aipl` (33 件) | 33/33 |
| `feature_a_hm/` (3 件) | 3/3 |
| `feature_b_crossclass/` (3 件) | 3/3 |
| `feature_c_refinement/` (3 件) | 3/3 (refinement issue は期待通り) |
| `feature_d_actorfields/` (3 件) | 3/3 (sample3 の unify issue は期待通り) |
| `feature_e_records/` (3 件) | 3/3 (sample3 の unify issue は期待通り) |

## 4. 制限事項

- **Width subtyping 未対応**: `{a:Int, b:Int}` を `{a}` を期待する param に渡せない。strict にしたのは shape 不一致を早期に検出するため。緩めるのは E-1+ 課題。
- **Row polymorphism 未対応**: 「`a` フィールドを持つあらゆる record」のような型は表現できない。今は具体的な field set ベース。
- **let-polymorphism の弱化**: generalise を VarDecl で抑制したため、グローバル let-binding は polymorphic にならない。AIPL の actor monomorphic 性に合わせた選択 (PsiLang2 / function decl は影響を受けない)。
- **nested field assign**: `obj.a.b = v` は深さ 2 以上で Dyn のまま (Phase E-β からの継承).

## 5. 規模

| 部分 | LOC |
|---|---:|
| aipl_inference.py (RecordLit + FieldAccess + unify + generalise 抑制 + repass) | +50 |
| sample 3 件 | +60 |
| **合計** | **+110** |

## 6. 結論

| 項目 | 結果 |
|---|---|
| record literal の型推論 | ✓ `TRecord((a:T, b:U))` 形式で表示 |
| FieldAccess の構造的解決 | ✓ TVar からの逆推論を含む |
| record shape mismatch 検出 | ✓ `unify` issue で位置付き報告 |
| 既存 33 abcl + 12 aipl sample | ✓ 全 PASS |

Phase D-1 (method 越境) → E-α (refinement) → E-β (field 共有) → E-γ (record structural) で、**actor / class / record / refinement を全部跨いだ統合的な型推論系**が AIPL Python 版に出揃った。

---

## 参考

- [Phase C REPORT](./PHASE_C_REPORT.md)
- [Phase D REPORT](./PHASE_D_REPORT.md)
- [Phase E-α REPORT](./PHASE_E_REPORT.md)
- [Phase E-β REPORT](./PHASE_E_BETA_REPORT.md)
- `src/python-aipl/aipl_inference.py` 〜1150 行
