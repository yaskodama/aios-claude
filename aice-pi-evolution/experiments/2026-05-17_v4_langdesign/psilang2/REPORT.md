# PsiLang2 — v4 top 1 genome の実装と評価

**日付:** 2026-05-17
**作業ディレクトリ:** `aice-pi-evolution/experiments/2026-05-17_v4_langdesign/psilang2/`
**親実験:** [v4 LangDesign_Expressive](../REPORT.md)
**結論:** v4 進化計算が選んだ top 1 genome (refinement 型を含む) を **23 行の preprocessor 追加だけ**で実装し、π 10,000 桁を **v2 PsiLang と SHA256 完全一致** で計算できることを確認。

---

## 1. 目的

v4 進化計算 (`2026-05-17_v4_langdesign`) の top 1 個体:

| id | score | paradigm | type_system | arithmetic | control_flow | syntax_family |
|---|---:|---|---|---|---|---|
| I35 | 0.639 | hybrid_imperative_functional | **refinement** | arbitrary_int_plus_rational | pattern_match_fold | ml_like |

を**実際に動くインタプリタ**として実装し、その上で **Chudnovsky binary-splitting** によって π 10,000 桁を計算する。v2 PsiLang との差分は **`refinement` 型システム** ただ一点なので、v2 を継承して refinement の構文だけ通せばよい。

## 2. 実装 — PsiLang2 = PsiLang + 23 行 preprocessor

`psilang2.py` は v2 の `psilang.py` (650 行) を**完全コピー**し、`tokenize()` の冒頭に **refinement 剥がし preprocessor** を追加しただけ:

```python
_WHERE_RE = re.compile(
    r'\bwhere\b'                                # the keyword
    r'(?:==|!=|<=|>=|[^,)\n=])*?'               # body: comparison ops atomic, or non-stop char
    r'(?=,|\)|=(?!=)|\bin\b|\n)',               # stop before , ) bare-= in newline
    re.DOTALL,
)

def _strip_refinement(src: str) -> str:
    """Remove `where <predicate>` clauses (v4 refinement annotations).
    Comment-aware: skips lines starting with '#'."""
    out = []
    for line in src.splitlines(keepends=True):
        if line.lstrip().startswith("#"):
            out.append(line)
        else:
            out.append(_WHERE_RE.sub('', line))
    return "".join(out)
```

合計 23 行 (`_WHERE_RE` 定義 5 行 + `_strip_refinement` 11 行 + `tokenize()` 内 1 行呼び出し + 説明コメント)。型注釈の本体は parse されずに捨てられる — **v2 と同じ「型は documentation」立場を refinement にも適用**しただけ。

## 3. プログラム — `chudnovsky.psi` (50 行)

v4 top 1 genome の全ての特性を活用した実装:

```psi
# ─── k-th Chudnovsky term ─────────────────────────────────────────
fn term(k: Int where k >= 0) -> Rat =
  let sign: Int where sign == 1 or sign == -1 =
    if k mod 2 == 0 then 1 else -1 in
  let num: Int = sign * int_fact(6 * k) * (545140134 * k + 13591409) in
  let den: Int where den > 0 =
    int_fact(3 * k) * int_pow(int_fact(k), 3) * int_pow(640320, 3 * k) in
  rat(num, den)

# ─── Binary splitting on the half-open interval [a, b) ────────────
fn bsplit(a: Int where a >= 0, b: Int where b > a) -> Rat =
  if b - a == 1 then term(a)
  else
    let m: Int where m > a and m < b = (a + b) / 2 in
    let left:  Rat = bsplit(a, m) in
    let right: Rat = bsplit(m, b) in
    rat_add(left, right)

# ─── π = 426880·√10005 / S  with full refinement contract ────────
fn chudnovsky_pi(n_digits: Int where n_digits > 0)
                  -> Real where digits == n_digits =
  let n_terms: Int where n_terms >= 2 = n_digits / 14 + 2 in
  let prec:    Int where prec > n_digits = n_digits + 20 in
  let _bump = set_precision(prec) in
  let s_rat:  Rat = bsplit(0, n_terms) in
  let s_real: Real where digits == prec = real_from_rat(s_rat, prec) in
  let c:      Real where digits == prec =
    real_mul(real_from_int(426880),
              real_sqrt(real_from_int(10005), prec)) in
  real_div(c, s_real)

# ─── Entry point ──────────────────────────────────────────────────
let pi:  Real where digits == 10000 = chudnovsky_pi(10000) in
let str: Str  where length == 10002 = real_to_string(pi, 10000) in
emit(str)
```

## 4. 実行結果

### 4.1 走らせる

```bash
$ /usr/bin/python3 psilang2.py chudnovsky.psi > pi_10k_v4.txt
$ wc -c pi_10k_v4.txt
   10003 pi_10k_v4.txt
```

### 4.2 数値検証

| 指標 | 値 |
|---|---|
| 実行時間 | **3.05 秒** (Apple M2) |
| 出力長 | 10,003 chars (= `"3."` + 10,000 桁 + 改行) |
| 先頭 102 桁の既知 π との一致 | ✓ |
| Feynman 点 (`999999` の最初の出現位置) | **762** (well-known 値と一致) |
| 1000 桁目 | `9` (OEIS A000796 と一致) |
| **SHA256** | **`d44e2dba39a378de3f41dace85394c8a02130e8442a61e91f3a8dd8e406f61e6`** |
| v2 PsiLang `chudnovsky.psi` 出力との bitwise 一致 | **✓** (同じ SHA256) |
| v2 PsiLang `machin.psi` 等 4 通り出力との一致 | **✓** (全 5 ファイルが同一ハッシュ) |

## 5. v2 vs v4 PsiLang のソース差分

```diff
- # PsiLang (v2 top 5 consensus, static_simple type system)
- fn term(k) =                                              ← 型注釈なし
-   let sign = if k mod 2 == 0 then 1 else -1 in
-   let num  = sign * int_fact(6 * k) * ...
-   let den  = int_fact(3 * k) * ...
-   rat(num, den)

+ # PsiLang2 (v4 top 1, refinement type system)
+ fn term(k: Int where k >= 0) -> Rat =                     ← 型 + 契約
+   let sign: Int where sign == 1 or sign == -1 =           ← 値域も明示
+     if k mod 2 == 0 then 1 else -1 in
+   let num: Int = sign * int_fact(6 * k) * ...
+   let den: Int where den > 0 =                            ← 不変量明示
+     int_fact(3 * k) * ...
+   rat(num, den)
```

アルゴリズム本体は**完全に同じ**。違うのは **型注釈の表現力**だけ:

| 注釈 | 何を主張するか |
|---|---|
| `Int where k >= 0` | 引数は非負整数 (組合せ展開の項番号) |
| `Int where sign == 1 or sign == -1` | sign は ±1 (Chudnovsky 公式の交代符号) |
| `Int where m > a and m < b` | 二分割中点が区間内にある |
| `Int where n_terms >= 2` | 級数は少なくとも 2 項以上 |
| `Real where digits == n_digits` | 戻り値の Real は指定桁数の精度を持つ |

これらは **Chudnovsky bsplit の数学的契約をソース上に書き下したもの**。論文と実装が 1 対 1 に対応する。

## 6. 評価

### 6.1 進化計算 → 言語実装 のパス

| 段階 | 結果 |
|---|---|
| v4 進化計算が示した top 1 genome | ✓ 5 軸の組合せが取得済 |
| その genome を実装するインタプリタ | ✓ v2 PsiLang + 23 行 preprocessor |
| その言語で π 10,000 桁を書く | ✓ `chudnovsky.psi` (50 行) |
| 同じ問題を v2 PsiLang と同等に解く | ✓ SHA256 一致 |

→ 進化計算が選んだ言語仕様 → インタプリタ実装 → アルゴリズム記述 → 数値検証、というループが **v4 でも完結**。

### 6.2 refinement 注釈の現実的価値

| 観点 | 状態 |
|---|---|
| 注釈の **parse** | ✓ preprocessor で受理 (現在は捨てる) |
| 注釈の **実行時検査** | ✗ documentation only |
| 注釈の **静的検査** (v5 計画) | ✗ 未実装 |
| 命題証明 (SMT) (v5+ 計画) | ✗ 未実装 |

現状の refinement は **「読む人 (人間 / 将来の型検査器 / LLM) に対する仕様書」** として機能する段階。v2 が `static_simple` 注釈を「人間用ドキュメント」と扱ったのと同じ立場を refinement にも適用しただけ。

### 6.3 v4 vs v2 — 言語が伝える情報量

|  | v2 PsiLang | v4 PsiLang2 |
|---|---|---|
| 型システム宣言 | static_simple | **refinement** |
| 型注釈の構文 | `: Int` のみ | `: Int where <predicate>` |
| アルゴリズム本体 | 同一 | 同一 |
| 出力 SHA256 | `d44e2dba39a378…` | **`d44e2dba39a378…`** ✓ |
| インタプリタ実装サイズ | 650 行 | 650 + 23 行 (preprocessor) |
| 「言語が伝える情報量」 | low (型のみ) | **high (型 + 不変量 + 契約)** |

進化計算は v2 から v4 への遷移で **「型注釈を refinement に格上げ」** という設計判断を独立に発見した。これは静的型付き関数型言語の歴史 (ML → Coq / Liquid Haskell / F\* / Idris) と方向性が一致する。

### 6.4 v4 進化計算結果との整合性確認

v4 top 1 (I35, score 0.639) の 5 軸 ↔ PsiLang2 での実現:

| 軸 | 値 | PsiLang2 での実現 |
|---|---|---|
| `paradigm` | hybrid_imperative_functional | `emit` (副作用) と `let`/`fn` (純粋式) の共存 |
| `type_system` | **refinement** | **`where` 句による predicate** ← v4 で新規 |
| `arithmetic_primitives` | arbitrary_int_plus_rational | `Int` / `Rat` builtin |
| `control_flow` | pattern_match_fold | `match … with \| pat -> e end` + 一般再帰 |
| `syntax_family` | ml_like | `let x: T where P = e in body` の ML 系構文 |

→ **v4 top 1 は v2 PsiLang の上位互換** (refinement type 注釈追加のみ)、同じ Python interpreter で実行可能 ということが実証できた。

## 7. 限界と次のステップ

### 7.1 現在の限界

- **refinement 注釈は実行時に検査されない**: `Int where k >= 0` と書いても、`term(-1)` を呼んでもクラッシュしない。Python の `int` がそれを許す。
- **`where` 内部の表現力**: 現在は `and`/`or`/比較演算子の組合せ。否定 `not`、function 呼び出し、絶対値 `|x|`、多項式関係などは preprocessor が剥がすだけで意味解析しない。
- **コード上の Bug は注釈に頼れない**: `k >= 0` と書いてあっても、書き間違いで負数が紛れたら検出されない。

### 7.2 v5 候補 (PsiLang2 → PsiLang3)

| 機能 | 期待効果 |
|---|---|
| (1) refinement runtime checker | `fn term(k: Int where k >= 0)` の呼び出しで `assert k >= 0` を入れる |
| (2) gradual refinement type checker (静的) | コンパイル時に `k >= 0 ⇒ 6*k - 5 < 6*k - 3` を導出 |
| (3) SMT (Z3) 連携 | 「契約が満たされる」を自動証明、満たされない呼び出しを静的に拒否 |
| (4) 命題自動証明 | `chudnovsky_pi(n) → Real where digits == n` をプログラム全体に渡って検証 |

これらは v4 ranks 上では「もっと良い言語にする」設計判断であり、v4 進化計算自身は `(1)〜(2)` までを `refinement_type` 軸の選好で示唆していた。

## 8. まとめ

| 項目 | 結果 |
|---|---|
| v4 top 1 genome の同定 | ✓ I35 = hybrid_imp_func + refinement + bigint+rat + pattern_match + ml_like |
| インタプリタ実装 | **PsiLang2 = PsiLang + 23 行 preprocessor** |
| π 10,000 桁プログラム | ✓ `chudnovsky.psi` (50 行) |
| 実行時間 | 3.05 秒 (v2 と同等) |
| 出力検証 | **v2 PsiLang と SHA256 完全一致** |
| 「進化計算→実装→検証」ループの完結 | ✓ |
| refinement 注釈の現実価値 | △ documentation only (v5 で本気の検査器を実装する道筋) |

v4 (進化計算) と PsiLang2 (実装) は組で「**型注釈を refinement に進化させる**」という設計選択の**実証ペア**になっている。アルゴリズム実行能力は v2 と同じだが、**ソースコードが伝える情報量** は明確に増えている — その情報を活用する検査器が v5 で書ける、というのが本実験のもう 1 つの含意。

---

## 参考

- [v4 LangDesign 進化計算 REPORT](../REPORT.md)
- [v2 PsiLang (祖先)](../../2026-05-16_v2_langdesign/REPORT.md)
- [v2 PsiLang interpreter (基盤)](../../2026-05-16_v2_langdesign/psilang/README.md)
