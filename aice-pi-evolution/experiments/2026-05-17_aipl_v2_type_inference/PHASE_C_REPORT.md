# Phase C — aipl_inference.py 実装 (Constraint-based HM + Z3 Refinement)

**日付:** 2026-05-17
**作業ファイル:** `src/python-aipl/aipl_inference.py` (870 行 新規)
**親実験:** [AIPL v2 (2) Type Inference REPORT](./REPORT.md)
**Phase C 該当の v2 (2) Top 1 genome:**
- `inference_algorithm = constraint_based_global`
- `type_system_strength = bidirectional_w_refinement`
- `subtyping = gradual`
- `implementation_strategy = external_zarith_solver` → **実装は z3-solver** (Z3 4.16, `pip install z3-solver`)

---

## 1. 実装したもの

| 機能 | 状態 |
|---|---|
| TypeVar / TCon / TArrow / TTuple / TRecord / TRefined の型表現 | ✓ |
| Robinson 単一化 (occurs check, gradual `Dyn` 含む) | ✓ |
| HM 多相 (Scheme + instantiate + generalise) | ✓ |
| AST から制約収集 (Var/Binop/Call/If/While/Let/Match) | ✓ (核となる expr/stmt 全部) |
| Refinement 注釈 parse (`Int where k >= 0`) | ✓ |
| **Z3 backend** — `where` 述語の充足性検査 | ✓ (Python `ast.BoolOp/Compare/BinOp/UnaryOp` → z3.And/Or/Not 変換) |
| Bidirectional check/synthesize の対 | ◯ 部分的 (constrain で代用) |
| Method 単位の推論 (`incremental_per_method` from v2 (2) top 5/5) | ✓ |
| 全プログラム推論 (`constraint_based_global`) | ◯ 部分的 (method 横断は未) |
| 既存 `aipl_typeck.py` との統合 | ◯ 並列起動 (`infer_program` を別途呼び出し) |

## 2. テスト結果

### 2.1 Z3 refinement 検査 (8 ケース全 PASS)

```
✓ Int where k >= 0                                  satisfiable=True
✓ Int where k >= 5 and k <= 3                       satisfiable=False
✓ Int where sign == 1 or sign == -1                 satisfiable=True
✓ Int where m > a and m < b                         satisfiable=True
✓ Int where n_terms >= 2                            satisfiable=True
✓ Int where x >= 0 and x <= 100 and x != 50         satisfiable=True
✓ Int where x > 0 and x < 0                         satisfiable=False
✓ Int where not (x == 0)                            satisfiable=True
```

→ `k >= 5 and k <= 3` のような**充足不能な refinement** を Z3 が unsat と判定。
→ `not`, chained compare, 範囲制約すべて OK。

### 2.2 AIPL プログラムでの HM 推論

`test_inference.aipl` で 3 メソッド・引数 4 つ・ローカル変数 5 つを **注釈ゼロ** で推論:

```
--- Math.fact ---
  param n : Int

--- Math.add_rat ---
  param a : Rat        ← rat_add の引数型から逆推論
  param b : Rat
  local sum : Rat

--- Math.pi_term ---
  param k : Int        ← `k == 0` の比較から推論
  local sign : Int     ← if/else の両枝が 1 / -1 で統一
  local num : Int      ← sign * int_fact(...) の積で Int
  local den : Int      ← int_pow(...) で Int
  local r : Rat        ← rat(Int, Int) の戻り値で Rat
```

**3 method, 0 issues** で完了。Hindley-Milner の本質的な性質 (関数のシグネチャから引数型を逆推論) が動作。

## 3. 実装規模

| 構成 | LOC |
|---|---:|
| `aipl_inference.py` 全体 | **870** |
|  - 型表現 + Subst + apply/free_vars | 110 |
|  - Unify (Robinson) | 90 |
|  - Inference monad + Env + Scheme | 100 |
|  - Builtin env (Int/Bool/Rat/Real ops) | 70 |
|  - Expression inference | 80 |
|  - Statement inference | 70 |
|  - Method-level driver + InferenceResult | 90 |
|  - Refinement parsing + Z3 backend (AST→Z3) | 130 |
|  - その他 (CLI, helpers) | 130 |
| Phase C 全体追加 | **+870** |

v2 (2) Top 4 (R4 reviewer 0.7 評価 = `+1000 行`) の予想内に収まる。

## 4. v2 (2) 進化計算結果との整合性

| v2 (2) Top 1〜5 軸 | 採用値 | 実装での実現 |
|---|---|---|
| inference_algorithm | constraint_based_global (top 1) / bidirectional (top 2-5) | 制約収集 + Robinson 単一化 |
| inference_scope | **incremental_per_method 4/5** | `infer_method(class, m)` が単位 |
| type_system_strength | HM 2 / bidirectional_w_refinement 1 | HM core + 別レイヤで refinement |
| subtyping | structural 2 / gradual 1 | `T_DYN` で gradual 採用 |
| default_inference_target | **principal_type_from_use 3/5** | unify が「使われ方」から決定 |
| annotation_requirement | optional_with_fallback_dyn 2 / optional_strict 2 | 注釈ない場合 fresh TVar、推論失敗時は Dyn |
| error_message_style | **ocaml_style_with_path 3/5** | InferenceIssue に kind/msg/location |
| implementation_strategy | external_zarith_solver 1 | **z3-solver** (Zarith は OCaml 専用なので Z3 を採用、精神は同じ) |

→ Top 5 の合意点すべてを実装に反映。

## 5. 限界と次のステップ

### 5.1 現状の限界

- **method 間の型は伝播しない**: `now math.fact(10)` で `fact` の戻り値型は fresh TVar のまま (class 越えの推論が未)
- **structural subtyping は浅い**: TRecord 同士の互換性チェックが未
- **bidirectional の completion**: `check(e, T) / synthesize(e)` の対関数化が未 (現状は constrain で代用)
- **Real / Rat の refinement**: 現在 `Int where ...` だけ Z3 でチェック。Real/Rat は documentation 扱い
- **ジェネリック関数の自動 generalise**: `let-polymorphism` の自動展開を一部のみ実装

### 5.2 次の段階 (Phase D 候補)

| 候補 | 期待効果 |
|---|---|
| Phase D-1: class 横断推論 | `now obj.method(...)` の戻り値を class 内の method 定義から推論 |
| Phase D-2: bidirectional の完全化 | `check / synthesize` を文法 driven に分離 |
| Phase D-3: PsiLang2 chudnovsky.psi の `where` 句を実体検査 | PsiLang2 の parser を AIPL inference の Refinement に接続 |
| Phase D-4: aipl_main.py に `--infer` flag | `--type-check` と並列に動作させる |

### 5.3 PsiLang2 chudnovsky.psi への適用 (Future)

現状 PsiLang2 の `.psi` ファイルは AIPL parser ではなく独自 parser (`psilang2.py` 内) を持つ。
将来的にはこの inference module を PsiLang2 にも適用できるが、その場合は PsiLang2 の AST を AIPL inference が読める形にブリッジする必要がある (Phase D-3)。

## 6. 結論

| 項目 | 結果 |
|---|---|
| 進化計算 (v2 (2)) → 実装の経路 | ✓ Top 1〜5 の合意設計を 870 行で実装 |
| HM 推論動作 | ✓ AIPL プログラムで引数・ローカルを注釈ゼロで推論 |
| Z3 refinement 検査 | ✓ Int 制約 8/8 ケース PASS、充足不能を unsat と判定 |
| 既存 `aipl_typeck.py` への影響 | なし (並列モジュール) |
| 後方互換 | ✓ 既存 .aipl は無変更で動作 |

Phase C は **進化計算 (v2 (2)) が示唆した型推論設計を、870 行で実装し、Z3 4.16 連携で refinement 充足性まで動作させる** ことに成功。次の Phase D で class 横断推論と PsiLang2 連携を追加する道筋ができた。

---

## 参考

- [v2 (2) Type Inference 進化計算 REPORT](./REPORT.md)
- [v2 (1) Evolve Block 進化計算 REPORT](../2026-05-17_aipl_v2_evolve_block/REPORT.md)
- 実装: `src/python-aipl/aipl_inference.py` (870 行)
- Z3 4.16 (`pip install --user --break-system-packages z3-solver`)
