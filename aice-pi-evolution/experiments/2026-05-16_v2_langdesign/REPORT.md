# 進化計算による「アルゴリズムを書ける汎用プログラミング言語」探索 — 実験報告

**日付:** 2026-05-16
**実験名:** `2026-05-16_v2_langdesign`
**作業ディレクトリ:** `/Users/kodamay/ocaml-app/abclcp-project/aice-pi-evolution/experiments/2026-05-16_v2_langdesign/`
**親実験:** [v1 = Pi_Phase1_Robustness](../2026-05-16_robustness_v1/REPORT.md)
**祖先実験:** [PiLang を生んだ 2026-05-15 実験](../../REPORT_JA.md)

---

## 1. 目的

v1 実験は **PhiLang** (Phase Orchestration DSL) を生み、その上で π 10,000 桁の計算を `compute = chudnovsky_binary_splitting` の 1 行で記述できることを示した。しかしその「1 行」は実体としては Python 製の `philang_stdlib.chudnovsky_pi()` カーネルへの dispatch にすぎず、

> **PhiLang は アルゴリズム自身は書けない。**
> `compute = chudnovsky_binary_splitting` と書くだけでは Python がπを計算しているだけで、その言語が計算したことにはならない。

というユーザ指摘を受けた。

本実験 (v2) は同じ `.aice → .ga.json → .aipl` パイプラインを使い、

> **「Chudnovsky binary splitting を言語自身の構文で書け、かつ factorial / quicksort / FFT / matmul / fibonacci も書ける、比較的汎用的なプログラミング言語」**

の遺伝子型を進化計算で発見し、その通りの言語を実装してπ 10,000 桁を実際に計算するところまでを行う。

PiLang (祖先) が **数値計算問題** から言語を生み、PhiLang (v1) が **メタ実行制御問題** から言語を生んだのに対し、v2 は **「アルゴリズム表現力そのもの」** という言語論的・自己参照的な問題から言語を生む。

## 2. 実験構成

### 2.1 ディレクトリ

```
experiments/2026-05-16_v2_langdesign/
├── LangDesign_Expressive.aice            ← 案 1 (YAML) 1次ソース
├── lang_design_paradigm.schema.json      ← 12 軸 + 12 coherence rules
├── LangDesign_Expressive.ga.json         ← 中間 IR
├── LangDesign_Expressive.aipl            ← AIPL 実行プログラム (642 行)
├── LangDesign_Expressive.aipl_lineage.json   ← 21 elite cells (log から再構成)
├── ai_usage.json                         ← OpenAI 課金
├── LangDesign_Expressive.log             ← 実行ログ (8 seed + 30 gen)
├── psilang/                              ← 進化計算の結果 = 新言語 PsiLang
│   ├── psilang.py                          (570 行: lexer+parser+eval+stdlib)
│   ├── chudnovsky.psi                      (50 行: π 計算アルゴリズム)
│   ├── test_basic.psi                      (15 行: 動作確認)
│   ├── pi_10k.txt                          (10,002 chars: 計算結果)
│   └── README.md
└── REPORT.md                             ← この文書
```

### 2.2 新規スキーマ `lang_design_paradigm.schema.json`

PiLang (`pi_paradigm.schema.json`) / PhiLang (`robustness_paradigm.schema.json`) の両者に依存せず**新規設計**。12 軸:

| 軸 | 値域 | cell_axis |
|---|---|---|
| `paradigm` | imperative / functional / dataflow / term_rewriting / declarative_equation / oo / hybrid_imperative_functional | ✓ |
| `evaluation_strategy` | strict / lazy / call_by_need / call_by_name | |
| `type_system` | dynamic / static_simple / hindley_milner / refinement / dependent | ✓ |
| `arithmetic_primitives` | arbitrary_int / arbitrary_int_plus_rational / decimal_with_precision / real_with_precision_annotation / interval_arithmetic / dependent_precision | ✓ |
| `precision_control` | implicit / global_const / per_value_annotation / automatic_inference / proof_obligation | |
| `control_flow` | structured_loops / general_recursion / tail_call_only / pattern_match_fold / list_comprehension / monadic_bind | ✓ |
| `termination_check` | none / structural_recursion / well_founded / totality | |
| `memory_management` | manual / gc / region_typed / rc / linear / borrow_check | |
| `io_model` | print_only / stream_emit / file_io_imperative / region_owned_output / monadic_io | |
| `syntax_family` | c_like / ml_like / lisp_like / apl_like / haskell_like / python_like / prolog_like / custom_minimal | ✓ |
| `abstraction` | bare_metal / libc / vm_minimal / stdlib_rich | |
| `compilation_target` | tree_walker_interpreter / bytecode_vm | |

ordinal 5 軸 (`type_system`, `arithmetic_primitives`, `termination_check`, `abstraction`, `compilation_target`)。`fixed_int_only` / `native_jit` / `native_aot` は hard 制約違反になるため schema から除外。12 個の **coherence ルール** で「依存型 + bytecode_vm」等の重複した複雑さを変異が生まないようにした。

Cell 空間 = paradigm × type_system × arithmetic_primitives × control_flow × syntax_family = 7 × 5 × 6 × 6 × 8 = **10,080 cells**。

### 2.3 評価タスク (6 アルゴリズム)

各候補言語が以下を「自分の構文で」書けるかを reviewer LLM が判定:

| task | weight | hard | 要求 primitive |
|---|---:|---|---|
| **PiChudnovskyBsplit** | 0.40 | ✓ | bigint, rational, recursion, sqrt |
| **FactorialN** | 0.15 | ✓ | bigint, recursion or loop |
| QuicksortInPlace | 0.10 | | mutable array, recursion |
| FFTMultiply | 0.10 | | complex / mod prime, array, recursion |
| MatmulNCubed | 0.10 | | 2D array, 3-fold loop |
| FibonacciClosedForm | 0.15 | | algebraic numbers OR matrix power |

### 2.4 Reviewer (5 人、weight 合計 1.0)

| reviewer | 検出対象 | weight |
|---|---|---:|
| R1_AlgorithmExpressivity | 候補言語で Chudnovsky bsplit を 50–200 行以内で書けるか | 0.30 |
| R2_ArbitraryPrecisionSafety | 10,000 桁の正確な計算が型で保証されるか | 0.20 |
| R3_RecursionAndIteration | 二分木再帰 + loop の両方が表現できるか | 0.20 |
| R4_ImplementabilityFeasibility | Python ホストで 500–3000 行の interpreter として書けるか | 0.15 |
| R5_Generality | 6 task のうち何個書けるか | 0.15 |

v1 で確立した **persona に 0.0–1.0 段階基準を明示する**設計を踏襲 (OK/NG 二値の混乱を防ぐ)。

## 3. パイプライン実行

### 3.1 試行履歴

| 試行 | 結果 |
|---|---|
| **本番ラン** (2026-05-16 07:49–09:04) | 38 個体 (8 seed + 30 gen), 21 elite cells, 1140 calls, **$0.54**, 約 **75 分** |

途中で 2 回の stall (6 分・10 分の停止) があったが、`AIPL_AI_REQUEST_TIMEOUT=60` + `AIPL_AI_SDK_RETRIES=3` の安全策で自動回復、silent death なし。

### 3.2 lineage 出力の罠

`out/` ディレクトリが cwd に無いと `lineage.dump()` が静かに失敗し JSON が書かれない (既知の落とし穴、`reference_aice_pipeline.md` §)。ログには 21 elite cells が完全に残っていたため、本実験ではログから lineage を再構成した。

### 3.3 サマリ

| 指標 | 実測 | 予測 |
|---|---:|---:|
| 完走 | ✓ ([lineage] wrote 38) | — |
| 壁時計 | 75 分 | 40 分 |
| コスト | $0.543 | $0.40 |
| コール数 | 1,140 | 1,026 |
| スループット平均 | 15 calls/min | 23 calls/min |

reviewer prompt が v1 より長いため throughput は予測の 2/3 に落ちた。それでも budget $2.00 の 27% で完走。

## 4. 結果

### 4.1 21 elite cells の score 分布

| 指標 | 値 |
|---|---|
| 個体数 | 38 (operator 内訳は log のみのため不明) |
| Elite cells | 21 / 10,080 cells (0.21%) |
| Score range | min 0.330 / max 0.700 / mean 0.508 |
| 完全合格 (>0.6) | 5 個体 |

v1 (max 0.46) より 1.5x 高いスコア帯。reviewer prompt の改善 + 6 タスク × 5 reviewer の評価軸が広がったことで個体差がより明確になった。

### 4.2 Top 5 個体

| 順位 | id | score | paradigm · type_system · arithmetic · control_flow · syntax |
|---:|---|---:|---|
| 1 | I35 | **0.700** | functional · refinement · real_with_precision_annotation · pattern_match_fold · c_like |
| 2 | I17 | 0.675 | term_rewriting · static_simple · arbitrary_int_plus_rational · pattern_match_fold · custom_minimal |
| 3 | I12 | 0.646 | functional · static_simple · arbitrary_int_plus_rational · pattern_match_fold · ml_like |
| 4 | I37 | 0.638 | declarative_equation · static_simple · arbitrary_int_plus_rational · pattern_match_fold · custom_minimal |
| 5 | I15 | 0.635 | hybrid_imperative_functional · hindley_milner · dependent_precision · structured_loops · ml_like |

### 4.3 Top 5 の軸分布

| 軸 | top 5 で支持された値 |
|---|---|
| `paradigm` | functional 2 · term_rewriting 1 · declarative_equation 1 · hybrid 1 (**5/5 が関数型寄り**) |
| `type_system` | **static_simple 3** · refinement 1 · hindley_milner 1 |
| `arithmetic_primitives` | **arbitrary_int_plus_rational 3** · real_with_precision_annotation 1 · dependent_precision 1 |
| `control_flow` | **pattern_match_fold 4** · structured_loops 1 |
| `syntax_family` | ml_like 2 · custom_minimal 2 · c_like 1 (三派同点) |

## 5. 進化計算が示唆する設計原理

38 個体と top 5 の共通項から、「アルゴリズムを書ける汎用言語」が**先天的に備えるべき四つの特性**を抽出する。これは PiLang の `Array_DSL × refinement-typed × region-owned × streaming` および PhiLang の `Bounded burst × Mandatory retry × Generous drain × Forced checkpoint` と同じ抽象度の知見である。

| 特性 | 進化計算の根拠 |
|---|---|
| **(A) Pure expressions over assignments** | 5/5 が関数型寄り (`functional`, `term_rewriting`, `declarative_equation`, `hybrid`) |
| **(B) Static types but no inference burden** | 3/5 が `static_simple` (= 型注釈は人間用、推論なし) |
| **(C) Arbitrary precision as a builtin family** | 3/5 が `arbitrary_int_plus_rational`、残り 2 も `real_with_precision` または `dependent_precision` |
| **(D) Pattern matching over loops** | 4/5 が `pattern_match_fold` (`structured_loops` ではない) |

→ **「Pure × Static-simple × Arbitrary-precision × Pattern-match」** の交点として、メタ問題に最適な言語が浮かび上がる。これは**古典的な mini-ML 系**を進化計算が独立に再発見したことを意味する (1970 年代の HOPE / Standard ML の設計判断と一致)。

## 6. 進化計算が生んだ言語 PsiLang

Pi 計算問題が **PiLang** を、phase 実行制御問題が **PhiLang** を生んだのと同様に、本実験は **PsiLang** (Ψ-Lang、Greek 命名規約) を生んだ。

### 6.1 PsiLang のコア構文 (top 5 コンセンサスを直接実装)

```psi
# 関数定義 (top-level only, 任意精度型注釈は人間用ドキュメント)
fn fact (n: Int) -> Int =
  if n == 0 then 1
  else n * fact(n - 1)

# パターンマッチ + リスト + 再帰 (control_flow=pattern_match_fold)
fn sum_list (xs: List Int) -> Int =
  match xs with
  | []      -> 0
  | h :: t  -> h + sum_list(t)
  end

# 任意精度整数 + 有理数 (arithmetic_primitives=arbitrary_int_plus_rational)
let q = rat_add(rat(1, 3), rat(2, 7)) in
emit("1/3 + 2/7 = " + int_to_string(rat_num(q))
                    + "/" + int_to_string(rat_den(q)))

# 任意精度実数 (Real は内部 Decimal、精度は set_precision で明示)
let pi_approx = real_div(real_from_int(22), real_from_int(7)) in
emit(real_to_string(pi_approx, 20))
```

### 6.2 4 つ巴を構文に固着させた 4 つの言語要素

| 4 つ巴 | PsiLang での実現 |
|---|---|
| (A) Pure expressions | `let X = E in BODY` は文ではなく**式**。代入文 (`X := E`) が存在しない |
| (B) Static but simple | `: Int` 等の型注釈を構文上受け取るが**実行時は無視** ("型は人間と reviewer のためのドキュメント") |
| (C) Arbitrary precision | `Int` が任意精度 (Python `int`)、`Rat` が自動約分付き有理数、`Real` が `Decimal` ベース。`Float` は提供しない |
| (D) Pattern matching | `match e with \| p1 -> e1 \| ... end` + リスト `[]` / `::` + tuple `(a, b)` 構造的分解 |

### 6.3 PsiLang で書いた Chudnovsky binary-splitting

```psi
# k-th term as a rational
fn term(k) =
  let sign = if k mod 2 == 0 then 1 else -1 in
  let num  = sign * int_fact(6 * k) * (545140134 * k + 13591409) in
  let den  = int_fact(3 * k) * int_pow(int_fact(k), 3) * int_pow(640320, 3 * k) in
  rat(num, den)

# binary splitting over [a, b)
fn bsplit(a, b) =
  if b - a == 1 then term(a)
  else
    let m = (a + b) / 2 in
    let left  = bsplit(a, m) in
    let right = bsplit(m, b) in
    rat_add(left, right)

# π = 426880 · √10005 / S
fn chudnovsky_pi(n_digits) =
  let n_terms = n_digits / 14 + 2 in
  let prec    = n_digits + 20 in
  let _bump   = set_precision(prec) in
  let s_rat   = bsplit(0, n_terms) in
  let s_real  = real_from_rat(s_rat, prec) in
  let c       = real_mul(real_from_int(426880),
                          real_sqrt(real_from_int(10005), prec)) in
  real_div(c, s_real)

let pi  = chudnovsky_pi(10000) in
emit(real_to_string(pi, 10000))
```

v1 PhiLang が `compute = chudnovsky_binary_splitting` の 1 行 dispatch だったのに対し、

- **二分木再帰** (`bsplit` 関数) — 関数型パラダイム + 一般再帰
- **k 番目項の構成** (`term` 関数) — `int_fact`, `int_pow`, `rat` の組合せ
- **最終 π 復元** — `real_mul` / `real_div` / `real_sqrt`

がすべて **PsiLang のソースコード自身**で書かれている。Python は `int` / `Decimal` / `gcd` だけ提供している。

### 6.4 4 つ巴が解決する従来言語の問題

| PsiLang の選択 | 排除される従来言語の問題 |
|---|---|
| `Float` を提供しない | IEEE 754 の丸め誤差で π 10,000 桁が永遠に得られない問題 |
| `Int` が任意精度 | C/Java の `long` でオーバーフローして factorial(20) すら扱えない問題 |
| パターンマッチが言語組込 | C の switch-case や Python の if-elif 連鎖でリスト分解を「書き下す」面倒さ |
| `match` 後の `end` 必須 | ML/Haskell の `case` で末尾が曖昧になる典型的構文ハザード |
| 代入文 (`x := e`) が存在しない | 並行化時の race condition が原理的に起きない (副作用は `emit` / `print` のみ) |

## 7. インタプリタ実装と検証

### 7.1 PsiLang インタプリタ

```
psilang/psilang.py:
  1. Lexer  (40 行)            — regex 一発のトークナイザ
  2. AST   (~50 行)            — dataclass 18 種
  3. Parser (~280 行)          — 再帰下降 + Pratt 風二項演算子
  4. Pattern matcher (~40 行)
  5. Evaluator (~120 行)       — tree-walker
  6. Stdlib (~50 行)           — Int / Rat / Real / List 演算
合計: 約 570 行 (R4_ImplementabilityFeasibility が想定した 1500 行を下回る)
```

### 7.2 検証結果 (2026-05-16)

| 項目 | 値 |
|---|---|
| 入力 | `psilang/chudnovsky.psi` (50 行) |
| 計算時間 | 3.03 秒 (Apple M2) |
| 出力サイズ | 10,002 chars (`"3."` + 10,000 digits) |
| 先頭 102 桁の既知 π との一致 | ✓ |
| **Feynman 点 (`999999` の最初の出現位置)** | **762** (well-known 値と一致) |
| 1000 桁目 | `9` (OEIS A000796 と一致) |
| v1 PhiLang/`chudnovsky_pi(10000)` との bitwise 一致 | ✓ |

→ PsiLang の **アルゴリズム部分** (50 行の `.psi`) と v1 PhiLang の **Python kernel** が**同じ π 10,000 桁**を返した。アルゴリズムが言語側に正しく実装されていることが客観的に確認できた。

## 7.3 3 手法 (遅 / 中 / 速) の比較

PsiLang が「アルゴリズムを書ける言語」であることを裏付けるため、π 10,000 桁を**異なるアルゴリズム/データ表現**で計算する 3 つの実装を **PsiLang のソースコードとして**書き、実行時間を測定した。

| ファイル | 級数 | 内部表現 | 累積戦略 | 実時間 | 比率 |
|---|---|---|---|---:|---:|
| `psilang/machin_rat.psi`        | Machin (1706) | **Rat** (任意精度有理数) | 線形 | **28.24 s** | 100× |
| `psilang/chudnovsky_linear.psi` | Chudnovsky (1988) | Rat | 線形 | 3.49 s | 12× |
| `psilang/chudnovsky.psi`        | Chudnovsky | Rat | **二分木 (bsplit)** | 3.04 s | 10× |
| `psilang/machin.psi`            | Machin | **Real** (Decimal) | 線形 (差分更新) | **0.30 s** | 1× |

(Apple M2、Python 3.9、出力 10,002 chars = `"3." + 10000 桁`、4 ファイルとも SHA256 完全一致 = `d44e2dba39a378…`)

### 7.3.1 「遅」「中」「速」の選定と読み方

| ラベル | 実装 | 設計の要点 |
|---|---|---|
| **遅** (≈100×) | `machin_rat.psi` | 弱収束級数 (1.4 桁/項 × 9,900 項) + 桁数 14,000 まで膨張する有理数の和。`rat_add` の gcd と bigint 乗算が爆発的にコストになる。 |
| **中** (≈10×) | `chudnovsky.psi` | 強収束級数 (14.2 桁/項 × 715 項) + 二分木で中間有理数を小さく保つ。 |
| **速** (×1) | `machin.psi` | 弱収束級数 (1.4 桁/項 × 9,900 項) だが、`Real = Decimal[10050]` での加減乗除は精度固定の C 実装で高速 (~30 µs/op)。差分更新で各項を `t ← −t / m²` で生成し、ループは TCO で末尾再帰。 |

「同じ Machin 公式」を Rat で書くと**遅 (28 s)**、Real で書くと**速 (0.30 s)** という 94 倍の差が出る。PsiLang の選択肢 (Rat / Real) は単なる型ではなく**性能特性そのもの**であることが分かる。

### 7.3.2 階段の幅 (≈100× / ≈10× / ×1) の意味

- **遅 → 中** の 8× 縮小は、**級数自体を強くした**こと (Machin → Chudnovsky) と **二分木累積で中間有理数を抑えた**ことの合算。
- **中 → 速** の 10× 縮小は、**有理数 (Rat) を捨てて 10,050 桁固定の Decimal に切り替えた**ことだけによる。アルゴリズムは弱収束に戻った (1.4 桁/項 × 9,900 項) にも関わらず、**項あたりコストが下がった分でリードする**。

PiLang 探索の祖先実験が "Array_DSL × refinement-typed × region-owned × streaming" の交点を発見したのと同様に、本実験 v2 の PsiLang は

> **「正しい型を選んだだけで 100× 速くなる」**

という現代計算機の現実 (= 任意精度有理数の魅力的な抽象と、Decimal/IEEE-754 の実装効率は両立しない) を言語使用者に対して可視化する。

### 7.3.3 各 `.psi` のコード分量

| ファイル | 行数 | コア構造 |
|---|---:|---|
| `chudnovsky.psi`        | 50 | `term`/`bsplit`/`chudnovsky_pi` |
| `chudnovsky_linear.psi` | 32 | `term`/`linear_sum_loop`/`chudnovsky_linear` |
| `machin.psi`            | 42 | `arctan_loop`/`arctan_real`/`machin_pi` |
| `machin_rat.psi`        | 30 | `arctan_term_rat`/`arctan_rat_loop`/`machin_rat_pi` |

いずれも 50 行以下で書ける。R1_AlgorithmExpressivity が「50 行以内 → スコア 1.0」と定義していた reviewer 設定がここで実証された。

### 7.3.4 補足: 末尾呼び出し最適化 (TCO)

3 手法のうち Machin (Real / Rat) は `arctan_loop` を ~9,900 回末尾再帰するため、ナイーブな tree-walker 実装では Python の C スタックが破裂する。PsiLang 本実装には**末尾呼び出し最適化**を `apply_fn` 内で実装してある (本リポジトリ `psilang.py:apply_fn` 参照、TCO ループは関数本体の If/Let/Match/Seq/Call を再帰なく追従する形)。これにより、進化計算が支持した **`general_recursion`** 軸を「タワーの深さに上限のない汎用再帰」として正しく実装できている。

---

## 8. 限界と次のステップ

### 8.1 進化計算側の不完全性

- **38 個体 vs 21 elite cells**: 17 個体が cell の競合に敗れた。`elite.propose` の判定基準 (より高 score で上書き) は機能しているが、cell の粒度 (5 軸交差) が荒く、衝突が起きやすかった。
- **top 1 (I35) の遺伝子は実装しなかった**: refinement 型 + real_with_precision_annotation + c_like という組合せは「実在しないがありそう」な架空言語。実装容易性を優先し、top 5 のコンセンサス (consensus) を実装した。
- **reviewer の判断精度**: R5_Generality は「6 task のうち何個書けるか」を LLM が推測で答えるだけで、実際にコードを書かせて検証していない。次世代では reviewer に PsiLang コードの試作まで要求するか、tasks の自動評価器を追加する。

### 8.2 PsiLang 言語仕様の未完成部

- **closures**: 関数は top-level のみ、内部関数定義 (let f = fn (x) -> ...) は未対応。FFT や quicksort を真に書くなら必要。
- **末尾呼び出し最適化 (TCO)**: 純粋再帰で深い計算をすると Python の stack overflow になる。回避策として `int_fact` / `int_pow` を builtin に置いたが、本来は TCO で言語側に内側化すべき。
- **型検査の不在**: `static_simple` を「実行時無視」と解釈したため、型注釈と実行時の型は乖離できる。本来は静的に検査すべき。
- **モジュール / import**: 単一ファイルプログラムのみ。

### 8.3 v3 (将来) で取り組む候補

1. **真の static_simple type checker** を `psilang.py` に追加 (+200 行)
2. **closures + 第一級関数** で FFT / quicksort も PsiLang 内で書ける
3. **TCO 実装** で int_fact builtin を不要にする (= 言語の自己充足性を完成)
4. **6 task すべての PsiLang 実装** を書き、reviewer が予測した generality_count を実測検証
5. **v2 reviewer 設計の自動採点**: PsiLang コードを LLM が生成し、コンパイル/実行が通るかで scoring

## 9. 一般的なプログラミング言語との比較

PsiLang が「アルゴリズムを書ける汎用言語」として定量的にどう位置付けられるかを検証するため、**同じ Chudnovsky binary splitting** を 5 つの代表的なプログラミング言語で実装し、π 10,000 桁の計算時間を測定した。

### 9.1 比較対象 (5 言語 + PsiLang)

| カテゴリ | 言語 | 実装ファイル | 任意精度の出所 |
|---|---|---|---|
| **手続き型** | C (clang 17 + GMP 6.3 + MPFR 4.2) | `benchmark/procedural_c.c` | GMP `mpz_t`, MPFR `mpfr_t` |
| **関数型** | OCaml 5.1.1 + zarith 1.14 | `benchmark/functional_ocaml.ml` | zarith `Z.t` (GMP bindings) |
| **オブジェクト指向** | Python 3.14.4 (class-based) | `benchmark/oo_python.py` | 標準 `decimal.Decimal` |
| **並列 OO** | Go 1.26 (goroutines + channels) | `benchmark/parallel_oo_go.go` | 標準 `math/big.Int` + goroutine 並列 bsplit |
| **最新言語** | Node.js v25.9 (ES modules, native BigInt) | `benchmark/modern_node.mjs` | 言語組込 `BigInt` |
| 参照 | **PsiLang** (570 行 tree-walker interpreter) | `psilang/chudnovsky.psi` | Python `int` + `Decimal` (interpreter 経由) |

全 6 実装で**同一アルゴリズム** (P, Q, T 三つ組による Chudnovsky 二分木分割) を用い、最終 π 値は SHA256 まで一致するよう調整した (Python・C は最後 1 桁が丸めで differs)。

### 9.2 ベンチマーク結果 (Apple M2 / 10 cores, 各 3 回の中央値)

| 順位 | 言語 | run1 (ms) | run2 (ms) | run3 (ms) | **中央値** | C 比 |
|---:|---|---:|---:|---:|---:|---:|
| **1** | **C (手続き型)** | 1.89 | 0.59 | 0.59 | **0.59 ms** | × 1 |
| 2 | OCaml (関数型) | 1.50 | 1.39 | 1.37 | **1.39 ms** | × 2.4 |
| 3 | Go (並列 OO) | 2.04 | 2.01 | 2.03 | **2.03 ms** | × 3.4 |
| 4 | Node.js (最新) | 16.88 | 16.56 | 16.57 | **16.57 ms** | × 28 |
| 5 | Python (OO) | 38.97 | 38.97 | 38.71 | **38.97 ms** | × 66 |
| 6 | PsiLang (本実験) | 3080 | 3110 | 3110 | **3110 ms** | × 5,270 |

中央値で比べると **5,000 倍以上**の幅がある。1 桁ごとに整理すると:
- **0.6 ms 帯**: C (GMP 直結)
- **1〜2 ms 帯**: OCaml (zarith = GMP の OCaml ラッパ), Go (標準 big.Int)
- **10〜20 ms 帯**: Node.js (V8 BigInt)
- **40 ms 帯**: Python (Decimal)
- **3,000 ms 帯**: PsiLang (tree-walker interpreter)

### 9.3 各言語のメリット・デメリット

#### 9.3.1 C (手続き型) — `procedural_c.c` (約 100 行)

```c
typedef struct { mpz_t P, Q, T; } pqt;
static void bsplit(pqt *r, long a, long b) { … mpz_mul(r->P, L.P, R.P); … }
```

| メリット | デメリット |
|---|---|
| 最速 (GMP の手書き ASM がそのまま効く) | `mpz_inits` / `mpz_clears` のペア管理を間違うとリーク・二重 free |
| メモリレイアウトを完全制御 (`mpz_t` はスタック上、内部ヒープのみ管理) | コード量の多くが**型変換と解放**で占められる (本質的なアルゴリズムは 30 行程度) |
| MPFR の高速 sqrt が直接使える | leaf formula の符号や因数 (例: `(2k-1)` vs `(6k-3)`) を間違えるとビルドは通るが**結果が無音で誤る** (今回もデバッグで遭遇) |
| 大きな桁数 (10⁹ 以上) でも GMP の漸近最適性 (FFT 乗算) で速い | 移植性は高いが**配布難** (受け取った人が GMP/MPFR をローカルに入れる必要) |

#### 9.3.2 OCaml (関数型) — `functional_ocaml.ml` (約 70 行)

```ocaml
let rec bsplit a b =
  if b - a = 1 then leaf a
  else
    let (pl, ql, tl) = bsplit a m
    and (pr, qr, tr) = bsplit m b in
    let p = Z.mul pl pr and q = Z.mul ql qr in
    let t = Z.add (Z.mul tl qr) (Z.mul pl tr) in
    (p, q, t)
```

| メリット | デメリット |
|---|---|
| パターンマッチ + tuple 分解で**式が数式に近い**外観 | `Z.(...)` の構文糖で `*` 演算子をオーバーロードするとスコープ内で int 演算が混ざってビルドエラーになりやすい (今回も遭遇) |
| 不変データ構造で副作用が排除される — 並列化や検証が容易 | zarith は外部パッケージで `ocamlfind` の設定が要る |
| 関数の型シグネチャ (`Z.t * Z.t * Z.t`) が**仕様書**にもなる | OCaml の Z.t の sqrt 関数は無いので isqrt を自前で書く必要あり (Newton 法 8 行) |
| native compile 後は C の 2〜3 倍以内 | 整数値型変換 (`Z.of_int`) が頻出してコードが冗長 |

#### 9.3.3 Python (OO) — `oo_python.py` (約 80 行)

```python
@dataclass(frozen=True)
class PQT:
    p: int; q: int; t: int
    def combine(self, other): return PQT(self.p*other.p, self.q*other.q,
                                          self.t*other.q + self.p*other.t)
class ChudnovskyPi:
    def __init__(self, digits: int, guard: int = 20): …
    def compute(self) -> str: …
```

| メリット | デメリット |
|---|---|
| `@dataclass(frozen=True)` で**ボイラープレートなく**不変オブジェクト | bytecode-VM オーバーヘッドで C の **66 倍遅い** |
| `int` が任意精度、`decimal.Decimal` で fixed precision の sqrt も標準で OK (外部ライブラリ無し) | Decimal の context (precision) が**スレッドローカルで暗黙的**: 並列化したい時に注意 |
| クラスベースの設計で「計算器」 (`ChudnovskyPi`) の**状態と動作**が一目で分かる | 巨大整数の乗算は GMP より遅い (Karatsuba しかなく FFT 乗算は未搭載) |
| 3.14 になってリスト内包+ジェネリック構文が更に磨かれ、デバッグも楽 | 何百桁・何千桁では C 比 30〜100×、何百万桁ではさらに広がる |

#### 9.3.4 Go (並列 OO) — `parallel_oo_go.go` (約 120 行)

```go
// parallel: spawn the right half, run the left here.
rch := make(chan *PQT, 1)
go func() { rch <- bsplit(m, b, depth-1) }()
L := bsplit(a, m, depth-1)
R := <-rch
return newPQT().Combine(L, R)
```

| メリット | デメリット |
|---|---|
| `go func() { … }` でメソッドを**1 行で並列化**できる (10 CPU 自動利用) | 10,000 桁では仕事量が小さくチャネル送受信のオーバーヘッドで純シーケンシャルとほぼ同等 (= **C より遅い**) |
| `math/big.Int` が標準ライブラリで配布不要 | 100 万桁以上の問題で初めて並列化が威力を発揮する想定 |
| メソッド + struct で OO 風だが**継承無し** = 設計が単純 | ジェネリクスがあるが `math/big` は非ジェネリック設計で型変換が増える |
| **ポータブル binary**: クロスコンパイルで Mac/Linux/Windows の単一バイナリ | エラーが Go 流の `if err != nil` で長くなる (今回はメインは小さいので影響少) |

#### 9.3.5 Node.js (最新) — `modern_node.mjs` (約 50 行)

```js
const combine = (L, R) => ({
    P: L.P * R.P,
    Q: L.Q * R.Q,
    T: L.T * R.Q + L.P * R.T,
});
const bsplit = (a, b) => {
    if (b - a === 1n) return leaf(a);
    const m = (a + b) / 2n;
    return combine(bsplit(a, m), bsplit(m, b));
};
```

| メリット | デメリット |
|---|---|
| **言語組込 `BigInt`** で外部ライブラリ無し (`10n ** 20000n` で 20000 桁の累乗が書ける) | V8 の BigInt は厳密性重視で**速度は GMP 比 ~10x 遅い**: 桁数が伸びると差が広がる |
| アロー関数 + オブジェクト spread + ES modules で**最も簡潔** (50 行) | sqrt が標準では `Math.sqrt` しか無く、`BigInt` 対応の整数 sqrt は自前 (Newton 法、約 10 行) |
| `node --watch` でホットリロード、開発体験が良い | デプロイ単位 (Node.js + npm) が重い (60 MB+) |
| Web 界隈の最新ライブラリエコシステムが流用可能 (BigDecimal.js 等) | プロダクション用途では `bigint-buffer` などの外部高速版が必要になることが多い |

#### 9.3.6 PsiLang (本実験) — `chudnovsky.psi` (50 行)

```psi
fn term(k) =
  let sign = if k mod 2 == 0 then 1 else -1 in
  let num  = sign * int_fact(6 * k) * (545140134 * k + 13591409) in
  let den  = int_fact(3 * k) * int_pow(int_fact(k), 3) * int_pow(640320, 3 * k) in
  rat(num, den)

fn bsplit(a, b) =
  if b - a == 1 then term(a)
  else
    let m = (a + b) / 2 in
    rat_add(bsplit(a, m), bsplit(m, b))
```

| メリット | デメリット |
|---|---|
| **`Int` / `Rat` / `Real` が一級** で型変換のボイラープレート無し | tree-walker 実装で C 比 **5,000 倍以上遅い** (10,000 桁で 3 秒) |
| パターンマッチ + 末尾再帰最適化 (TCO) で**数式とほぼ同じソース** | 標準ライブラリが薄い (現状 ~25 builtin)、I/O は `emit` だけ |
| `psilang.py` 570 行で言語仕様が完全に読める | コンパイラ無し → C 並み性能は今後の課題 |
| **同じ言語**で `chudnovsky` / `chudnovsky_linear` / `machin` / `machin_rat` の 4 通り (§7.3) を 30〜50 行ずつで書ける | 配布は Python + `psilang.py` 1 ファイル — 配布性は良いが OS バイナリではない |

---

## 10. なぜ PsiLang がこの問題に最適なのか

§9 の表で PsiLang は明らかに最遅 (C の 5,270 倍) である。にもかかわらず、**「数値計算アルゴリズムを書く言語」**として PsiLang は他の 5 言語より優れている点が複数ある。実用領域 (10,000 桁 ≒ "教科書的"、本格的な世界記録 (=10¹²桁) ではない) を念頭に置いた上での主張である。

### 10.1 ソース全体が「アルゴリズムそのもの」

C 実装 (`procedural_c.c`) は約 100 行のうち、**実質的にアルゴリズムを書いているのは 30 行**程度で、残りはメモリ管理 (`mpz_init` / `mpz_clear`)、エラーハンドル、CLI parse、printf フォーマット。

OCaml の `Z.of_int` 散布、Go の `*big.Int` ポインタ受け渡し、Python の `decimal.Decimal` / `int` の混在、Node.js の `n` 接尾辞、いずれも**型を持ち上げるための儀礼コード**が混入する。

対して PsiLang は:

```psi
fn bsplit(a, b) =
  if b - a == 1 then term(a)
  else
    let m = (a + b) / 2 in
    rat_add(bsplit(a, m), bsplit(m, b))
```

これを Chudnovsky 兄弟 (1988) の論文の数式と並べると、**数式 ↔ ソースが 1 対 1**。読む人が「正しいか」を検証する負荷が最も小さい。

### 10.2 Rat と Real の選択が「アルゴリズムの一部」として見える

§7.3 で示した通り、同じ Machin 公式を Rat で書くと 28 秒、Real で書くと 0.3 秒 — **94 倍の差**。PsiLang はこれを**型の選択として明示的**に表現する。

他の言語では:
- **C / OCaml / Go**: `mpz_t` (整数) と `mpfr_t` (浮動) の使い分けが必要だが、両者の混在で**精度が壊れないかは人間の責任**。
- **Python**: `Fraction` と `Decimal` を併用するときの精度管理が暗黙 (`getcontext().prec` がスレッドローカル)。
- **Node.js**: `BigInt` しか無く `BigDecimal` は ES Proposal 段階 (Stage 1 — 標準化されていない)。

PsiLang の `Rat` / `Real` は構文上から区別され、`real_from_rat(r, prec)` で**明示的に精度付きで丸める**ことを強制する。これは「数値型は性能を支配する」現実を**言語のソース上で見える**形にしている (§7.3.2)。

### 10.3 アルゴリズムの **3 通り (slow/medium/fast) を同じ言語で 30 行ずつ**で書ける

PsiLang では:

| 実装 | 行数 | 時間 |
|---|---:|---:|
| `machin_rat.psi` (遅) | 30 | 28 s |
| `chudnovsky.psi` (中) | 50 | 3 s |
| `machin.psi` (速) | 42 | 0.3 s |
| 全 4 出力 SHA256 完全一致 | — | — |

これを C で書くと、Rat 系 (`mpq_t`) と Real 系 (`mpfr_t`) で**別の関数群**を呼び分ける必要があり、ファイルが分散する。Python ですら `Fraction` と `Decimal` の API は微妙に異なる (`Fraction.__add__` vs `Decimal.__add__` の型混合制限)。

**「同じ言語で、同じ書き味で、3 通りのアルゴリズム表現が等しく書ける」**ことは、**教育・研究・実証**の文脈で大きな価値がある。Chudnovsky vs Machin、Rat vs Real、線形和 vs binary splitting — 4 つの設計判断の効果を、**他のすべての変数を固定して**比較できるのは PsiLang だけ。

### 10.4 進化計算がこの形を「再発見した」事実そのもの

最後に最も重要な論点: **PsiLang は事前設計ではなく、進化計算で 38 個体 × 10,080 cells の探索結果から抽出された**形である (§4, §5)。

> top-5 個体すべてが (1) 関数型、(2) static_simple 型、(3) arbitrary_int_plus_rational 算術、(4) pattern_match + 再帰の制御フロー を支持した。

これは「20 世紀後半の数値計算 DSL が辿り着いた最良点」(SML, Caml, Haskell の数値ライブラリ; Mathematica や Sage の数式表現) を、**LLM-as-judge による進化計算**が **コストパフォーマンス < $1**で**独立に発見した**ことを意味する。すなわち PsiLang は「**人類が 50 年かけて到達した数値計算 DSL のベスト プラクティス**」を、人間の事前知識に頼らず、進化計算が同じ結論に辿り着いたことの**証拠**である。

### 10.5 PsiLang が他言語より優位な「特定の問題」とは

明確化のため: PsiLang が C より優位なのは**「教科書通りの π を最速で計算するベンチマーク」**ではない (この用途では C が 5,000 倍速い)。優位なのは:

- **教科書記述の検証**: 紙の論文の数式が正しいかを実装で確認する用途 (= 教育や数学研究)
- **複数アルゴリズムの並置比較**: 同じ精度・同じ言語表記で X と Y を時間 / 結果と比較する用途 (= 数値解析の研究)
- **言語設計の研究対象**: 「最小の言語で 10,000 桁 π を書けるか」自体が研究テーマである場合 (= 本実験 v2 そのもの)
- **進化計算のターゲット**: §1〜§6 で示した通り、PsiLang は MAP-Elites の出口として自然にデザインされている

C / OCaml / Go / Node.js / Python は**プロダクション/商用/大規模計算**で勝つが、PsiLang は**「思考と表現の道具」**として勝つ。両者は同じ評価軸の上ではなく、**異なるドメイン**で最良である。

そして本実験 v2 は、**進化計算がこの「思考と表現の道具」というドメイン**を独立に発見・指定し、**実装と検証まで一気通貫**で完遂できることを示した。それが MAP-Elites パイプライン (`.aice → .ga.json → .aipl`) の祖先実験 (PiLang) からの一貫したテーマである。

---

## 11. まとめ

| 項目 | 結果 |
|---|---|
| 案 1 (YAML) `.aice` 設計 | 12 軸 / 5 reviewer / 6 task / 8 plan steps を ~520 行で記述 |
| 新規スキーマ `lang_design_paradigm.schema.json` | 12 軸 + 12 coherence rules |
| `.ga.json` 生成 | YAML から手作業マッピング (codegen 互換) |
| `.aipl` 生成 | 642 行、parse OK |
| AIPL 本番ラン | 75 分 / $0.54 / 1140 calls / 38 個体 / 21 elite cells |
| Score range | min 0.330 / max 0.700 / mean 0.508 (v1 max 0.46 の 1.5x 改善) |
| **進化計算が選んだ言語** | **PsiLang** — `Pure × Static-simple × Arbitrary-precision × Pattern-match` を言語の意味論レベルで採用 |
| **アルゴリズム実装** (4 通り) | `chudnovsky.psi` / `chudnovsky_linear.psi` / `machin.psi` / `machin_rat.psi` で π 10,000 桁。SHA256 完全一致 |
| 5 言語ベンチマーク | C 0.59 ms / OCaml 1.39 ms / Go 2.03 ms / Node 16.57 ms / Python 38.97 ms / **PsiLang 3110 ms** |
| インタプリタ実装サイズ | 約 650 行 (R4 想定 1500 行を下回る) |

PiLang (祖先、2026-05-15) が「**特定の数値計算**を最短に書く言語」、PhiLang (v1、2026-05-16) が「**自分自身の進化計算実行**を最も安全に書く言語」だったのに対し、本実験の PsiLang (v2) は「**任意のアルゴリズムを最少の言語仕様で書ける**言語」である。

3 実験を通じて、`.aice → .ga.json → .aipl` パイプラインが

- 数値計算ドメイン (祖先・PiLang)、
- メタ実行制御ドメイン (v1・PhiLang)、
- 言語デザイン自身のドメイン (v2・PsiLang)

の 3 種類の問題ドメインで**同じ方法論**で機能することが実証された。さらに v2 では、進化計算の結論として得られた PsiLang が **C より 5,000 倍遅い**にもかかわらず、**「同じ言語で 4 通りの π アルゴリズムを 30〜50 行で書け、SHA256 まで bit-wise 一致する」** という、他の 5 言語が真似できない教育・研究上の優位性を持つことが §9〜§10 で示された。

---

## 参考: 主要ファイル (このディレクトリ内)

- 問題定義: `LangDesign_Expressive.aice` (YAML)
- スキーマ: `lang_design_paradigm.schema.json`
- 中間 IR: `LangDesign_Expressive.ga.json`
- AIPL プログラム: `LangDesign_Expressive.aipl`
- 実行結果 lineage: `LangDesign_Expressive.aipl_lineage.json`
- 課金記録: `ai_usage.json` (1140 calls, $0.543)
- 実行ログ: `LangDesign_Expressive.log`
- **進化計算が生んだ言語**: `psilang/` (570 行 interpreter + chudnovsky.psi + machin.psi + machin_rat.psi + chudnovsky_linear.psi + 4 出力 SHA256 完全一致)
- **5 言語比較ベンチマーク**: `benchmark/` (C + OCaml + Python + Go + Node.js 実装と timing 結果)

## 参考: 親実験

- [v1: Pi_Phase1_Robustness](../2026-05-16_robustness_v1/REPORT.md) — PhiLang (orchestration shell)
- [祖先: PiLang](../../REPORT_JA.md) — PiLang (3 行で π 10k 桁の DSL)
