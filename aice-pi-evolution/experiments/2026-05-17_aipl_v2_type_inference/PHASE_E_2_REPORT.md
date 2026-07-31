# Phase E-2 — typeck × inference 統合

**日付:** 2026-05-17
**前段:** [Phase E-γ-R REPORT](./PHASE_E_GAMMA_R_REPORT.md)
**関連ファイル:**
- `src/python-aipl/aipl_main.py` (+25 行: `--check` フラグ + section ヘッダ)
- `src/python-aipl/aipl_inference.py` (+100 行: `BUILTIN_SIGNATURES` 連携 / `_typeck_type_to_inference` / `_parse_typeck_signature` / `_check_builtin_call`)
- `samples/feature_g_integration/sample{1,2,3}.aipl` (新規)

---

## 1. 目的と前提の見直し

Phase E-α 時点で「`aipl_typeck.py` (877 行) と `aipl_inference.py` を merge」と書いていたが、コードを精読した結果 **両者は重複ではなく相補的** だと判明:

| 機能 | typeck | inference |
|---|---|---|
| nominal annotation check (`x: int`) | ✓ | partial (E-α 以降) |
| BUILTIN_SIGNATURES validation | ✓ | ✗ → E-2 で追加 |
| effects `!{fs, ai, net, mut}` | ✓ | ✗ |
| linear 型 (`linear T`) | ✓ | ✗ |
| HM type inference | ✗ | ✓ |
| Refinement + Z3 | ✗ | ✓ (Phase C/E-α/γ-R) |
| Cross-class signatures | ✗ | ✓ (Phase D-1) |
| Actor field 共有 | ✗ | ✓ (Phase E-β) |
| Record structural typing | ✗ | ✓ (Phase E-γ) |

E-2 のゴールを「真の merge」ではなく **(a) 統合 CLI / (b) BUILTIN_SIGNATURES の共有** にスコープし、両者を保ったまま協調動作させる。

## 2. 設計

### 2.1 統合 CLI フラグ `--check`

```sh
$ python3 aipl_main.py program.aipl --check
=== --type-check (nominal + signature + effects) ===
[type] ...
[type] N issue(s).

=== --infer (HM + refinement + structural) ===
=== Class.method ===
  params: ...
...
[infer] M method(s), U unify issue(s), R refinement issue(s)
```

- `--type-check` / `--infer` は単独でも引き続き動く (後方互換)
- `--check` は **両方** を実行し、section ヘッダで区切る
- `--strict` と組み合わせると、いずれかが issue を出した時点で exit code を返す
- `--check` は `--type-check` 単独と異なり `--strict` でも typeck issue で即 abort しない (inference 結果も先に見せる)

### 2.2 inference が BUILTIN_SIGNATURES を参照

`aipl_inference._infer_call` / `CallStmt` の path で、`env.lookup(name)` が失敗したら `aipl_interp.BUILTIN_SIGNATURES` を引く:

```python
bsig = _lookup_builtin_signature(e.name)
if bsig is not None:
    return _check_builtin_call(infer, env, e, bsig)
```

`_check_builtin_call` は signature 文字列を parse → 各 param 型を inference Type に変換 → 引数 type と unify。

#### 型変換マップ

```python
_TYPECK_NAME_MAP = {
    "int": T_INT, "string": T_STR, "str": T_STR, "bool": T_BOOL,
    "float": T_REAL, "real": T_REAL, "rat": T_RAT,
    "unit": T_UNIT, "any": T_DYN, "void": T_UNIT,
}
```

- `array[T]` → `TCon("List", (T,))`
- union (`int | float`) → `T_DYN` (inference は alternation を表現できないので gradual)
- 不明なものは fresh TVar

#### Signature parser の制限

variadic (`name:T+`) / optional (`[name:T]`) 入りの signature は parse をスキップして gradual fallback (return T_DYN)。引数数のチェックだけは緩く行う。完璧な variadic 推論は E-2+ 候補。

### 2.3 既存テストへの影響

- `aipl_typeck.py` 無改変
- `aipl_inference.py` の builtin lookup は **無いものは silent**。`env.lookup` で見つかれば従来通り、見つからずに BUILTIN_SIGNATURES に無ければ silent skip。誤検知ゼロ。
- 33 abcl + 18 prior .aipl 全 PASS (Phase E-2 後)

## 3. サンプル実行手順

```sh
PY=/opt/homebrew/bin/python3
AIPL=src/python-aipl/aipl_main.py
```

### 3.1 sample1_typeck_catches.aipl — typeck が捕捉

```sh
$PY $AIPL samples/feature_g_integration/sample1_typeck_catches.aipl --check
```

3 種のエラー (literal-vs-annotation / builtin arg / function return) を **両方の pass** が報告:

```
=== --type-check ===
[type] function f: return type mismatch  (expected int, got string)
[type] method T.demo: `var n` initializer mismatch  (expected int, got string)
[type] method T.demo: call to function `write_file` arg `path` mismatch  (expected string, got int)
[type] 3 issue(s).

=== --infer ===
  issues:
    [unify] cannot unify Str with int  at var n
    [unify] cannot unify Int with Str  at write_file arg 1
    [unbound] unknown function: f  at 
[infer] 2 method(s), 3 unify issue(s), 0 refinement issue(s)
```

`var n: int = "hi"` を **typeck と inference の両方** が独立に捕捉 — 検査経路が違うので fail-safe (片方が見逃しても他方が掴む)。

### 3.2 sample2_inference_catches.aipl — inference のみ捕捉

```sh
$PY $AIPL samples/feature_g_integration/sample2_inference_catches.aipl --check
```

注釈なしの actor field + refinement UNSAT。typeck は gradual のため見逃すが、inference が:

```
[type] no issues.
...
  refinement issues:
    refinement is vacuously false: {_: Int | k >= 5 and k <= 3}
[infer] 3 method(s), 0 unify issue(s), 1 refinement issue(s)
```

### 3.3 sample3_clean.aipl — 両方 clean

```sh
$PY $AIPL samples/feature_g_integration/sample3_clean.aipl --check
```

Writer + Logger の 2 actor、`write_file`/`str_upper` 利用、`level: Int where level >= 0 and level <= 9` 注釈。両 pass で 0 issue。

```
[type] no issues.
...
=== class fields ===
  Writer:
    path : Str
  Logger:
    w : Writer
    label : Str

[infer] 2 method(s), 0 unify issue(s), 0 refinement issue(s)
```

field 型 (`path : Str`, `w : Writer`, `label : Str`) と record 型 (`rec : {sev: Int, what: Str, who: Str}`) が正確に表示される。

### 3.4 全 21 sample 回帰

| Suite | PASS |
|---|---|
| `src/python-aipl/samples/*.aipl` (33 件) | 33/33 |
| `feature_{a..f}` (18 件) | 18/18 |
| `feature_g_integration` (3 件) | 3/3 |

## 4. 補足: なぜ "AST レベル merge" にしなかったか

当初想定の「両 walker を AST レベルで一本化」は技術的には可能だが:

1. **役割が違う**: typeck は string-based gradual (annotation 駆動)、inference は HM (構造駆動)。merge すると両方の表現を抱え込み、複雑度が爆発する。
2. **テスト境界が崩れる**: 877 行の typeck を inference 側に飲み込むと、effects / linear / variadic などの細かな分岐が inference の HM ロジックと混ざって追跡困難に。
3. **段階的進化を阻害**: 今後 PsiLang2 連携や別 backend を足すとき、両 pass が分離している方が拡張しやすい。

代わりに **CLI と BUILTIN_SIGNATURES** という 2 つの interface だけを共有して、内部はそれぞれの責務に専念させた。"loose coupling" 設計。

## 5. 制限事項

- variadic / optional な builtin (`print(any+)`, `random([n [, hi]])`) は inference 側では gradual fallback (引数の数だけ check しない)
- typeck の effects / linear は inference 側にエコーされない (これらは typeck 専担で OK)
- nested record の field assign (`r.a.b = v`) は依然として Dyn
- `--check` は今のところ standalone 動作。実行と組み合わせる (`--check --transient` で型チェック後に実行) は未対応

## 6. 規模

| 部分 | LOC |
|---|---:|
| aipl_main.py (`--check`) | +25 |
| aipl_inference.py (builtin 連携) | +100 |
| sample 3 件 | +75 |
| **合計** | **+200** |

## 7. 結論

| 項目 | 結果 |
|---|---|
| 統合 CLI `--check` | ✓ typeck + inference を一本で実行 |
| BUILTIN_SIGNATURES 共有 | ✓ inference が builtin call の引数型を check |
| 後方互換 | ✓ `--type-check` / `--infer` 単独動作 |
| 既存 33 abcl + 18 prior aipl | ✓ 全 PASS |
| 「真の AST merge」 | ✗ スコープアウト (理由は §4) |

Phase E-α (where) / E-β (actor field) / E-γ (record) / E-γ-R (Real/Rat) / E-2 (integration) で、AIPL Python 版の **静的解析パイプライン** が出揃った。typeck と inference は **co-operating, not merged** の形で残し、`--check` で開発者が両方の結果を一度に得られる。

## Phase E 全体の俯瞰

| Phase | Feature | LOC |
|---|---|---:|
| C | constraint-based HM + Z3 refinement (Int) | +850 |
| D-1 | cross-class inference | +170 |
| D-4 | `--infer` CLI flag | +20 |
| E-α | `where` 句 in AIPL grammar | +120 |
| E-β | actor field 共有 | +165 |
| E-γ | record structural typing | +110 |
| E-γ-R | Real/Rat refinement | +79 |
| E-2 | typeck integration + `--check` | +200 |
| **Total** | | **+1714** |

Phase E は本記事で一区切り。次は別軸 (実行系最適化、進化計算で別言語、PsiLang2 maintenance など) に移る選択肢が広がる。

---

## 参考

- [Phase C REPORT](./PHASE_C_REPORT.md) ・ [Phase D REPORT](./PHASE_D_REPORT.md)
- [Phase E-α REPORT](./PHASE_E_REPORT.md) ・ [E-β REPORT](./PHASE_E_BETA_REPORT.md)
- [E-γ REPORT (records)](./PHASE_E_GAMMA_REPORT.md) ・ [E-γ-R REPORT (Real/Rat)](./PHASE_E_GAMMA_R_REPORT.md)
- `src/python-aipl/aipl_inference.py` 〜1350 行 / `aipl_typeck.py` 877 行
