# Phase E-γ-R — Real / Rat refinement (Z3 Real theory)

**日付:** 2026-05-17
**前段:** [Phase E-γ REPORT (records)](./PHASE_E_GAMMA_REPORT.md)
**関連ファイル:**
- `src/python-aipl/grammar.lark` (+1 行: `ref_atom` に FLOAT)
- `src/python-aipl/aipl_parser.py` (+3 行: `ref_float` transformer)
- `src/python-aipl/aipl_inference.py` (+15 行: `_z3_check` の sort dispatch)
- `samples/feature_f_realrat/sample{1,2,3}.aipl` (新規)

---

## 1. 目的

Phase E-α で `where` 句が AIPL 表層に入って以降、refinement の Z3 backend は **Int 限定** だった (`_z3_check` 先頭で `if rt.base != T_INT: return True, "non-Int refinement deferred to runtime"`)。つまり以下のような Real refinement は構文だけ受理して内容検査されなかった:

```aipl
method foo(x: Real where x > 0.0 and x < 1.0) -> Real { ... }
```

Phase E-γ-R では Z3 の Real 理論を使って Real / Rat の predicate を実体検査する。`Rat` も Z3 上は Real (Z3 の Real は有理数体) として扱う。

## 2. 設計

### 2.1 grammar に FLOAT を追加

```lark
?ref_atom: FLOAT  -> ref_float
         | INT    -> ref_int
         | NAME   -> ref_var
         | "(" refinement ")" -> ref_paren
```

FLOAT は AIPL の既存トークン (`/[0-9]+\.[0-9]*|\.[0-9]+/`) を流用。`ref_float` transformer は単に文字列化して渡す (Python AST がそのまま float リテラルとして食える)。

### 2.2 `_z3_check` を sort 分岐に

```python
if rt.base == T_INT:           mk_var = z3.Int
elif rt.base in (T_REAL, T_RAT): mk_var = z3.Real
elif rt.base == T_BOOL:         mk_var = z3.Bool
else:                            return True, "non-numeric ... deferred"

free = {binder: mk_var(binder)}
for tok in free names in predicate:
    free[tok] = mk_var(tok)       # 全自由変数を binder と同 sort
```

free 変数の sort も binder に揃える。`m > a and m < b` のような predicate で `a`, `b` が文字通り「m と同種の値」になる。

### 2.3 `_ast_to_z3` は無改変

Python AST → Z3 への翻訳ロジック (BoolOp / Compare / BinOp / Constant) は既に float リテラルを `z3.RealVal` に変換していたため、無改変で Real 文脈にもそのまま使える。**Z3 backend は元から多態だった** ことが幸いした。

## 3. サンプル実行手順

```sh
PY=/opt/homebrew/bin/python3
AIPL=src/python-aipl/aipl_main.py
```

### 3.1 sample1_real_sat.aipl — 5 SAT 全成功

```sh
$PY $AIPL samples/feature_f_realrat/sample1_real_sat.aipl --infer
```

5 method (`unit_open`, `nonneg`, `positive_below`, `offset_window`, `monotone`) が全部 satisfiable。`offset_window` は自由変数 `a` 入り、`monotone` は `p == 2.0 * q + 1.0` の線形等式。期待:

```
[infer] 5 method(s), 0 unify issue(s), 0 refinement issue(s)
```

### 3.2 sample2_real_unsat.aipl — 4 UNSAT 全検出

```sh
$PY $AIPL samples/feature_f_realrat/sample2_real_unsat.aipl --infer
```

`gt1_lt05` (`x>1.0 and x<0.5`)、`strict_open_zero` (`y>0.0 and y<0.0`)、`bigger_than_self` (`z>z+1.0`)、`bool_eq_int` (`w==1.0 and w==2.0`) — どれも実数上で不可能。期待:

```
  refinement issues:
    refinement is vacuously false: {_: Real | x > 1.0 and x < 0.5}  (predicate is unsatisfiable)
    refinement is vacuously false: {_: Real | y > 0.0 and y < 0.0}  (predicate is unsatisfiable)
    refinement is vacuously false: {_: Real | z > z + 1.0}  (predicate is unsatisfiable)
    refinement is vacuously false: {_: Real | w == 1.0 and w == 2.0}  (predicate is unsatisfiable)

[infer] 4 method(s), 0 unify issue(s), 4 refinement issue(s)
```

### 3.3 sample3_rat_mixed.aipl — Rat + Real 混合 (4 SAT + 1 UNSAT)

```sh
$PY $AIPL samples/feature_f_realrat/sample3_rat_mixed.aipl --infer
```

- `rat_window` (Rat, sat), `rat_holed` (Rat, 2 サブ区間 sat)
- `real_avoid_zero` (Real, `not (x == 0.0)` sat)
- `real_one_solution` (Real, `2.0*x+1.0 == 4.0` で `x = 1.5` sat)
- `contradictory` (Real, `z>5.0 and not(z>1.0)` UNSAT)

期待:

```
[infer] 5 method(s), 0 unify issue(s), 1 refinement issue(s)
```

### 3.4 全 18 sample (回帰)

| Suite | PASS |
|---|---|
| `src/python-aipl/samples/*.abcl` (33 件) | 33/33 |
| `feature_a_hm/` (3 件) | 3/3 |
| `feature_b_crossclass/` (3 件) | 3/3 |
| `feature_c_refinement/` (3 件) | 3/3 (refinement issue 期待通り) |
| `feature_d_actorfields/` (3 件) | 3/3 |
| `feature_e_records/` (3 件) | 3/3 |
| `feature_f_realrat/` (3 件) | 3/3 (sample2 / sample3 の refinement issue 期待通り) |

## 4. 制限事項

- **Float refinement は未対応**: AIPL の `Float` 型はあるが、`Float where ...` は今のところ `_z3_check` の sort 分岐に入れていない (Z3 にネイティブな Float 理論 (FP) はあるが、IEEE754 を厳密にサポートすると複雑な制約論理になるため見送り)。代替として `Real` を使えば良い。
- **Z3 Real の境界**: `Real` は Z3 上で **数学的実数** (有理数体) で、 IEEE754 浮動小数のセマンティクスとは異なる。プログラム内の実数演算が浮動小数誤差を持つ場合、Z3 の判定と実行時挙動がずれる可能性。
- **Bool refinement** の sort dispatch は実装済みだが、サンプルでは未試験。

## 5. 規模

| 部分 | LOC |
|---|---:|
| grammar.lark (`ref_atom` に FLOAT) | +1 |
| aipl_parser.py (`ref_float` transformer) | +3 |
| aipl_inference.py (`_z3_check` sort dispatch) | +15 |
| sample 3 件 | +60 |
| **合計** | **+79** |

## 6. 結論

| 項目 | 結果 |
|---|---|
| Real refinement の Z3 検査 | ✓ SAT / UNSAT を Real 理論で判定 |
| Rat refinement の Z3 検査 | ✓ Real と同じバックエンドを再利用 |
| 自由変数の sort 整合 | ✓ binder に合わせて全て Real / Int |
| 既存 33 abcl + 15 prior aipl sample | ✓ 全 PASS |

Phase E-α で「`where` 句」、E-γ-R で「Real/Rat backend」が出揃い、AIPL の refinement type system は **Int / Real / Rat / Bool** の 4 sort で実用範囲をカバー。**Phase E-α の唯一の本質的なやり残し** が埋まった。

## 残候補

| 候補 | 評価 |
|---|---|
| E-2 既存 typeck と統合 | コードベース健全化として有意義 (877+1150 行の重複) |
| D-3 PsiLang2 連携 | 必須性は低い (Phase E-α 以降、AIPL native で代替可) |

---

## 参考

- [Phase C REPORT](./PHASE_C_REPORT.md)
- [Phase D REPORT](./PHASE_D_REPORT.md)
- [Phase E-α REPORT](./PHASE_E_REPORT.md)
- [Phase E-β REPORT](./PHASE_E_BETA_REPORT.md)
- [Phase E-γ REPORT (records)](./PHASE_E_GAMMA_REPORT.md)
- `src/python-aipl/aipl_inference.py` 〜1170 行
