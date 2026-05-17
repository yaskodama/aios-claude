# Phase E-α — AIPL 表層文法に `where` 句を追加

**日付:** 2026-05-17
**前段:** [Phase D REPORT](./PHASE_D_REPORT.md)
**関連ファイル:**
- `src/python-aipl/grammar.lark` (+25 行: `type_refined` + `refinement` sub-grammar)
- `src/python-aipl/aipl_parser.py` (+60 行: 12 個の transformer)
- `src/python-aipl/aipl_inference.py` (+30 行: `refined_decls` field, `_check_refined_decls`, param 表示時 binder 復元)
- `samples/feature_c_refinement/sample{1,2,3}.aipl` (新規 .aipl 版)

---

## 1. 目的

Phase D 終了時点で、Feature C (Refinement Types + Z3) のサンプルは AIPL 表層文法に `where` 句が無いため Python API (`_parse_annotation` + `_z3_check`) を直接叩いて書くしかなかった。Phase E-α では `.aipl` ソースに `Int where <pred>` を直接書けるよう grammar と parser を拡張する。

## 2. 設計

### 2.1 grammar 拡張

`?type_term` に refinement バリアントを追加:

```lark
?type_term: ... 既存 ...
          | type_term "where" refinement                  -> type_refined

?refinement: ref_or
ref_or:  ref_and  ("or"  ref_and)*
ref_and: ref_not  ("and" ref_not)*
?ref_not: "not" ref_not                                   -> ref_not
        | ref_cmp
ref_cmp: ref_sum  (ref_cmp_op ref_sum)*
!ref_cmp_op: "==" | "!=" | "<=" | ">=" | "<" | ">"
ref_sum: ref_mul  (ref_add_op ref_mul)*
!ref_add_op: "+" | "-"
ref_mul: ref_unary (ref_mul_op ref_unary)*
!ref_mul_op: "*" | "/"
?ref_unary: "-" ref_unary                                 -> ref_neg
          | ref_atom
?ref_atom: INT  -> ref_int
         | NAME -> ref_var
         | "(" refinement ")" -> ref_paren
```

**設計判断**: AIPL の一般 `expr` を再利用するのではなく、`refinement_*` 専用 sub-grammar を新設。理由は 3 つ:

1. **キーワード局所化**: `and`/`or`/`not` を一般 `expr` で受理すると後方互換破壊が大きい。refinement 内だけで使うので影響は最小。
2. **predicate stringifier の単純化**: 各 sub-rule の transformer が直接 Python 構文 string を返す → 既存 `aipl_inference._parse_annotation` が再パース不要で受け取れる。
3. **Z3 backend 不変**: predicate 文字列形式の interface (Python AST → Z3 変換) は Phase C 時点と同一。

NAME 排除リストに `where|and|or|not` を追加 (識別子として既存 .aipl コード/サンプルでの使用ゼロを確認済み)。

### 2.2 parser transformer

`aipl_parser.py` に 12 個の transformer を追加。各 rule が文字列を返し、`type_refined` で `"<base> where <pred>"` を生成。これにより既存の `_parse_annotation(ann: str, ...)` が手を加えずに受け取れる。

### 2.3 inference 側

`_parse_annotation` が TRefined を返すたび、新フィールド `infer.refined_decls` に登録。inference 終了時に `_check_refined_decls(infer.refined_decls)` で各 predicate を Z3 satisfiability で個別チェック → 真の充足解が存在しない (vacuously false) ものを refinement issue として報告。

### 2.4 param 表示時の binder 復元

`unify(TVar, TRefined)` は line 235 で先に TVar → TRefined を bind するが、Pass 0 で caller が argument 型を流し込んだ後 (TVar が concrete TCon に bound 済み) に refinement 注釈が来ると、line 261 の "drop refinement for unification" rule で refinement が捨てられて表示から消える。Phase E-α では `_infer_method` で:

```python
refined_ann_by_pos[i] = TRefined(ann_t.base, p, ann_t.pred_src, ann_t.pred_ast)
```

を保持し、`final_params` 構築時に元の param 名で binder を付け直して再注入する。これで caller の有無に関係なく `n : {n: Int | n >= 0}` のように表示される。

## 3. サンプル実行手順

> `PY=/opt/homebrew/bin/python3` / `AIPL=src/python-aipl/aipl_main.py` を仮定。

### 3.1 SAT (5 method, 0 issue)

```sh
$PY $AIPL samples/feature_c_refinement/sample1_satisfiable.aipl --infer
```

期待出力 (抜粋):

```
=== Sat.needs_nonneg ===
  params:
    k : {k: Int | k >= 0}
  return : Int
...
=== Sat.needs_complex ===
  params:
    x : {x: Int | x >= 0 and x <= 100 and x != 50}
  return : Int

[infer] 5 method(s), 0 unify issue(s), 0 refinement issue(s)
```

### 3.2 UNSAT (4 method, 4 issue)

```sh
$PY $AIPL samples/feature_c_refinement/sample2_unsatisfiable.aipl --infer
```

期待出力 (末尾):

```
  refinement issues:
    refinement is vacuously false: {_: Int | k >= 5 and k <= 3}  (predicate is unsatisfiable)
    refinement is vacuously false: {_: Int | x > 0 and x < 0}  (predicate is unsatisfiable)
    refinement is vacuously false: {_: Int | n >= 100 and n <= 10}  (predicate is unsatisfiable)
    refinement is vacuously false: {_: Int | k == 1 and k == 2}  (predicate is unsatisfiable)

[infer] 4 method(s), 0 unify issue(s), 4 refinement issue(s)
```

### 3.3 Mixed (6 method, 2 issue)

```sh
$PY $AIPL samples/feature_c_refinement/sample3_mixed.aipl --infer
```

期待出力 (抜粋):

```
=== Mixed.range_pred ===
  params:
    a : {a: Int | 0 <= a and a <= 100}
=== Mixed.nonzero ===
  params:
    b : {b: Int | not (b == 0)}
=== Mixed.holed ===
  params:
    c : {c: Int | (c == 0) or (c > 5 and c < 10)}
=== Mixed.solves_for_three ===
  params:
    d : {d: Int | 2 * d + 1 == 7}
...
  refinement issues:
    refinement is vacuously false: {_: Int | (x > 10) and not (x > 5)}  (predicate is unsatisfiable)
    refinement is vacuously false: {_: Int | y + 1 == y}  (predicate is unsatisfiable)

[infer] 6 method(s), 0 unify issue(s), 2 refinement issue(s)
```

### 3.4 既存 6 サンプル (回帰)

```sh
for f in samples/feature_a_hm/*.aipl samples/feature_b_crossclass/*.aipl; do
  $PY $AIPL "$f" --infer | tail -1
done
```

全 6 件で `0 unify issue(s), 0 refinement issue(s)`。

### 3.5 AIPL 全 sample (33 件) 回帰

`src/python-aipl/samples/*.abcl` 全 33 件で:
- Traceback なし
- parse error なし

PASS=33 / FAIL=0 (`and|or|not|where` キーワード化の影響なし)。

> 注: `src/python-aipl/_smoke_test.sh` は古い `abcl_main.py` を参照しているため動かない (既知の問題で Phase E と無関係)。`aipl_main.py` 直叩きで 33/33 PASS を確認した。

## 4. 制限事項

- `Int where <pred>` の `<pred>` は新 sub-grammar 内に閉じる。AIPL の一般 `expr` から `and`/`or`/`not` は使えない (`if` 条件式などには影響なし)。
- `Real`/`Rat`/`Bool` の refinement は `_z3_check` が現状 `Int` 限定 (line 871 `if rt.base != T_INT: return True, "non-Int refinement deferred to runtime"`)。Z3 の Real/Rat 理論を有効化するのは Phase E-β 候補。
- predicate 内で関数呼び出しは未対応 (`ref_atom` は INT / NAME / paren のみ)。
- `_parse_annotation` の where regex は `[^\s]+ where ...` なので、refinement の base が tuple のようにスペースを含むと取りこぼす (まれな corner case)。

## 5. 残課題 (Phase E-β 以降)

| 候補 | 期待効果 |
|---|---|
| Real/Rat 用 Z3 backend | 浮動小数領域の制約 (`Real where x > 0.0 and x < 1.0`) |
| D-3 PsiLang2 連携 | PsiLang2 chudnovsky.psi の `where` を AIPL inference に流す |
| E-1 record/field structural typing | `{a: Int, b: Bool}` の構造的部分型 |
| E-2 既存 typeck との統合 | `aipl_typeck.py` (877 行) と AST レベル merge |
| E-3 actor field 型推論 | class field の cross-method 推論 |

## 6. 規模

| 部分 | LOC |
|---|---:|
| grammar.lark 拡張 | +25 |
| aipl_parser.py transformer | +60 |
| aipl_inference.py (refined_decls + display) | +30 |
| Feature C .aipl サンプル 3 件 | +90 |
| **合計** | **+205** |

## 7. 結論

| 項目 | 結果 |
|---|---|
| AIPL surface に `where` 句 | ✓ end-to-end (`.aipl` → parser → inference → Z3) |
| SAT/UNSAT 自動判定 | ✓ declaration-time 検査 |
| 既存 33 sample 回帰 | ✓ PASS=33 / FAIL=0 |
| Feature C を .aipl で表現可能 | ✓ Python API 不要 |

Phase D 段階で Python API 経由でしか書けなかった refinement が、Phase E-α で **AIPL ソース上の first-class な type 注釈**になった。

---

## 参考

- [Phase C REPORT](./PHASE_C_REPORT.md)
- [Phase D REPORT](./PHASE_D_REPORT.md)
- `samples/feature_c_refinement/` (.aipl 版 = Phase E-α, .py 版 = Phase C/D legacy)
