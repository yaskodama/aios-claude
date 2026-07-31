# OCaml AIPL — Python 同等化ロードマップ

**作成日:** 2026-05-18
**目的:** OCaml ランタイム (Python (annotated) と並ぶフラッグシップ実装) に
Phase C-E2 型推論と AIPL v2 Distributed (`aipl_dist`) を移植し、機能を
Python と同等にする。

---

## 1. 現状ギャップ (`docs/AIPL_Runtime_Feature_Matrix.md` より)

OCaml は既に HM 推論 (`src/infer.ml`, 689 LOC) と actor + remote actor +
HMAC + AI integration を持つ。**Py-A 限定の 18 機能** を移植する必要あり。

### Phase C-E2 (9 機能, ~1200-1700 LOC OCaml)

| ID | 機能 | OCaml で何が要るか |
|---|---|---|
| CE-1 | constraint-based HM + Z3 refinement (Int) | infer.ml に refinement 型コンストラクタ + Z3 OCaml binding |
| CE-2 | cross-class inference | infer.ml は既に部分的に持つ、強化が必要 |
| CE-3 | `where` 句 in grammar | lexer.mll + parser.mly 拡張 (~40 行 + AST node) |
| CE-4 | actor field 共有 (method 横断) | infer.ml で class field を method 越境 unify |
| CE-5 | record structural typing | infer.ml は records を持つが structural unify が未完 |
| CE-6 | Real / Rat refinement (Z3 Real 理論) | CE-1 完了後、Z3 sort dispatch |
| CE-7 | `--check` 統合 CLI | repl_thread.ml の引数処理 |
| CE-8 | `--infer` standalone CLI | 同上 |
| CE-9 | vacuously-false detection | CE-1 の副産物 |

### aipl_dist (9 機能, ~600-800 LOC OCaml)

| ID | 機能 | OCaml での実装イメージ |
|---|---|---|
| DR-1 | env_var_routing | `aipl_dist.ml` に Hashtbl + parser |
| DR-2 | structured_log | `Yojson` + Mutex + append-only writer |
| DR-3 | token_budget_aware | `Mutex` + Queue で 60s sliding window |
| DR-4 | checkpoint_and_resume | 既存の `ABCL_NODE_STATE_FILE` を拡張 |
| DR-5 | quarantine_and_skip | `eval_thread.ml` の actor dispatch にチェック |
| DR-6 | quorum_replicate | `ai.ml` の `call_ai` を `Thread.create` で並列化 |
| DR-7 | subtree_quarantine | spawn 時の parent registry + `quarantine` 拡張 |
| DR-8 | spawn-tree tracking | actor spawn 時の hook |
| DR-9 | runtime hooks (opt-in) | 上記すべてのアクティベーション |

---

## 2. 段階計画

### Phase O-1: aipl_dist OCaml 移植 ✅ 完了 (2026-05-18)

**目的:** Python と **同じ env var 規約** で動く OCaml 版 `aipl_dist` を新規
モジュール `src/aipl_dist.ml` として実装。AIPL 言語仕様 + 既存サンプル
すべて無改変。

**達成:**
- `src/aipl_dist.ml` (~530 LOC) で DR-1 〜 DR-9 の 9 機能を OCaml で実装
- `eval_thread.ml` の `spawn_actor` / `actor_loop` 例外経路に opt-in hook (+30 行)
- `AIPL_DIST_ENABLE` unset で完全 no-op (構造的に保証)
- 既存 71 abclc サンプル 71/71 PASS
- 単体テスト 7/7 PASS (`src/test_aipl_dist.ml`)

DR-3/DR-6 の auto-wiring (Ai.call_gemini → budget_gate + quorum)、
DR-8 の TLS-based parent inference は **Phase O-1.5** で追加完了。

### Phase O-1.5: Ai.call_gemini wire + TLS parent ✅ 完了 (2026-05-18)

**達成:**
- `Aipl_dist.set_current_actor` / `get_current_actor` / `register_spawn_auto`
  追加 (per-thread `current_actor : (int, string) Hashtbl.t` で管理)
- `eval_thread.ml` の `actor_loop` で dispatch 時に TLS set/unset
- `ai.ml` を `call_gemini` (wrapper) + `call_gemini_core` (body) に分割
- wrapper で `Aipl_dist.quorum_providers ()` 検出時に `call_ai_quorum`
  へファンアウト、それ以外は core を呼ぶ
- core に `Aipl_dist.token_budget_gate ()` の acquire を opt-in 挿入
- 単体テスト 8/8 PASS (TLS test 追加)、71 abclc 全 PASS

### Phase O-2: Phase C-E2 OCaml 移植 (複数セッション)

依存関係順に分割:

#### O-2.a (1 session, easy): `where` 句 grammar (CE-3) ✅ 完了 (2026-05-18)

実装結果:
- `lexer.mll` に `where`/`and`/`or`/`not` の 4 キーワードを追加
- `parser.mly` に WHERE/AND_KW/OR_KW/NOT_KW トークン宣言 +
  `type_expr WHERE refine_or` 規則 + `refine_{or,and,not,cmp,sum,mul,unary,atom}`
  の 7 段 sub-grammar (Python 側の refinement と 1:1)
- `ast.ml` に `TyERefined of type_expr * refine_pred` と
  `refine_pred` 型 (RpInt / RpFloat / RpVar / RpUnary / RpBinop / RpParen) 追加
- `infer.ml` の `ty_of_type_expr_with_tbl` で `TyERefined (base, _)` を
  base にlower (predicate AST は捨てる; Z3 接続は O-2.b)
- `abclc/WhereClause.aipl` で parse + script execution 確認
- 既存 71 abclc サンプル 71/71 PASS
- `aipl_dist` smoke 8/8 PASS

実測 LOC: 約 80 行 (推定 100-200 内).

#### O-2.b (1 session, medium): Z3 backend + Int refinement (CE-1, CE-9) ✅ 完了 (2026-05-18)

実装結果:
- z3 4.15.2 CLI を `opam install z3` 経由で利用 (OCaml bindings ではなく
  SMT-LIB 2 + `z3 -in -t:5000` で stdin/stdout 経由、依存最小化)
- `src/refinement.ml` (~165 LOC) を新規作成:
  - `Ast.refine_pred` → SMT-LIB 2 への renderer (`render_pred`)
  - 自由変数収集 + `(declare-const v Int)` 自動生成 (`collect_vars`,
    `render_smt`)
  - `find_z3 ()` で `command -v z3` 検出 + キャッシュ
  - `run_z3_check` で 1-shot 実行 (PATH に z3 が無い場合は `None`)
  - `check_pred : base:ty -> binder:string -> refine_pred -> check_result`
    で `Satisfiable | Unsatisfiable | Deferred string` を返す
  - `is_vacuously_false` 便利関数
  - `string_of_pred` で diagnostic message 生成
- `src/infer.ml` の `ty_of_type_expr_with_tbl` に `TyERefined` 用 hook を
  追加 (env `AIPL_REFINE_CHECK=1` で発火、stderr に `[refine warning]
  vacuously-false refinement: ...` を出力、Z3 不在時 silent fallback)
- 単体テスト 6 個追加 (test_aipl_dist 内: SAT/UNSAT/OR+NOT/free-vars/
  non-Int defer/string_of_pred) → 14/14 PASS
- `abclc/WhereVacuous.aipl` サンプル + driver `src/test_refine_check.ml`
- 既存 72 abclc サンプル全 PASS

実測 LOC: 約 250 行 (推定 300-500 内).

⚠️ 現状の限界:
- 警告は `Typecheck.run` 経由でしか発火しない (`repl_thread.exe -f` の
  ランタイム実行パスでは型検査は走らない). `/api/typecheck` endpoint と
  `web_gateway.ml` 経由で観測可能.
- 警告のみ (エラー化なし). `--strict` 相当の機能は CLI 統合 (O-2.f) で.

#### O-2.c (1 session, medium): Real / Rat refinement (CE-6) ✅ 完了 (2026-05-18)

実装結果:
- `src/refinement.ml` を `smt_sort = SMT_Int | SMT_Real` パラメータ化:
  - `render_int_literal ~sort` — Int は `n`、Real は `n.0` フォーマット
  - `render_float_literal` — `%.10g` decimal、負値は `(- 3.14)`、NaN/Inf は防御的に `0.0`
  - `render_pred ~sort` — 全 sub-call に伝播、`/` は Int で `div`、Real で `/`
  - `render_smt ~sort ~binder` — `(declare-const v Int/Real)` の選択
- `check_pred` を `TFloat → SMT_Real` で dispatch (OCaml AIPL の `Rat` は
  `TFloat` で代用; Z3 の Real は有理数体なので意味的に正しい)
- `infer.ml` の hook はそのまま (base_ty 経由で自動的に Real 路に流れる)
- 単体テスト 4 個追加: Real SAT/UNSAT/mixed-int-lit/real-division → 18/18 PASS
- サンプル `abclc/WhereVacuousReal.aipl` (unit, bad_window, bad_self, half)
- 既存 abclc 72 回帰 → 73/73 PASS

実測 LOC: 約 90 行 (推定 100-200 内).

#### O-2.d (1 session, medium): Cross-class inference + actor field 共有 (CE-2, CE-4) ✅ 完了 (2026-05-18)

実装結果 (調査の結果、想定より小規模で済んだ):
- 既存 `check_decl` で actor field 共有は **既に動いていた** — class-local env で field を generalize → 各 method が同じ scheme を見る. Int/String 混在テストで type error が出ることを確認.
- バグ修正: `check_stmt` に `TypedVarDecl` ケースが欠落 → 追加. ついでに annotation 不一致を `Type_error` 化.
- 主修正: `preinfer_all_classes` で method 戻り型を **ハードコード `TUnit`** ではなく declared `-> T` (annotation 有) または fresh tvar に変更 (~10 行).
- 主修正: `infer_expr` の `Now` / `Future` ケースが **常に `TAny`** を返していた path を、`class_method_schemes` から actual return 型を取得して返すよう変更 (~30 行).
- 検証: `src/test_o2d_inference.ml` (5 test) で
  cross-class basic / actor field consistent / actor field conflict /
  method return flows back / method return type mismatch — **5/5 PASS**.
- 既存 74 abclc + 18 aipl_dist smoke 完全無回帰.

実測 LOC: 約 60 行 (推定 200-400 行と比べて大幅減).

#### O-2.e (1 session, easy): Record structural (CE-5) ✅ 完了 (2026-05-18)

実装結果 (調査の結果、unify は既に structural だった):
- `Types.unify` の `TRecord` ケースを再確認 → 既に label-sort +
  field 数一致 + per-field 再帰 unify を実装済 (Python E-γ と同等の
  width-equal structural matching).
- ところが `preinfer_all_classes` が method parameter annotation を
  無視 (fresh tvar で代用) していたため,cross-class 呼出しで
  record shape 不一致が silent だった.parameter annotation も
  尊重するよう修正 (`List.map2 ... param_types`, ~6 行).
- 検証: 既存 5 test に加えて record 5 test を追加 — basic /
  shape mismatch / count mismatch / unsorted-fields / field-type
  mismatch すべて 10/10 PASS.
- 既存 abclc 74 + aipl_dist 18 完全無回帰.
- サンプル `abclc/RecordStructural.aipl`.

実測 LOC: 約 30 行 (推定 100-200 から大幅減).
発見: O-2.e の真の修正は **parameter annotation の尊重** という
O-2.d の延長線上にある修正で、O-2.d と一体だった可能性もある.

#### O-2.f (1 session, easy): CLI 統合 (CE-7, CE-8) ✅ 完了 (2026-05-18)

実装結果:
- `repl_thread.ml` に 4 つの CLI フラグを追加:
  - `--type-check FILE` — `Typecheck.run` を呼び型エラーを表示して exit
  - `--infer FILE` — 同上 (OCaml では typecheck と inference が一体)
  - `--check FILE` — Python-style の section banner 付き出力
    (`=== --type-check ... ===` / `=== --infer ... ===`)
  - `--strict` — 単独で使い、issue 検出時に exit 3
- `run_static_check` 関数を新設 (~50 LOC) でファイル読込→parse→
  Infer.check_program→summary 出力→exit code。
- main 関数の冒頭で `check_mode` が立っていれば actor runtime を
  立ち上げる前に `Stdlib.exit` する分岐を追加。
- 検証: 既存 75 abclc + 18 aipl_dist + 10 O-2d/e inference テストすべて
  PASS。`--check abclc/WhereVacuous.aipl` + `AIPL_REFINE_CHECK=1`
  で 2 vacuously-false warning が stderr に出る。
- bad な type-check サンプルで `--strict` exit code 3 確認。

実測 LOC: 約 75 行 (推定 50-100 内).

\## Phase O 完全完了 (2026-05-18)

| Phase | 実 LOC | 推定 |
|---|---:|---:|
| O-1 / O-1.5 | ~720 | 700 |
| O-2.a | +80 | 100-200 |
| O-2.b | +250 | 300-500 |
| O-2.c | +90 | 100-200 |
| O-2.d | +60 | 200-400 |
| O-2.e | +30 | 100-200 |
| O-2.f | +75 | 50-100 |
| **合計** | **~1305** | **~1925** |

実 LOC は推定の **68%** で完遂。OCaml AIPL の既存基盤 (HM 推論 +
class_method_schemes + structural unify) が想定以上に充実していた
ことが主因。CE-1〜9 + DR-1〜9 の **全 18 機能** が OCaml と JS-O で
利用可能になり、Python (annotated) と完全機能同等。

---

## 3. 順序と依存

```
[Phase O-1: aipl_dist 移植] ← 独立、本セッション

[Phase O-2]
  O-2.a (where 句)
    ↓
  O-2.b (Z3 + Int refinement) ← Z3 OCaml binding を入れるところがクリティカル
    ↓
  O-2.c (Real/Rat refinement)
    ↓ (並行可能)
  O-2.d (cross-class + actor field)  ← O-2.b 不要、独立進行可
  O-2.e (record structural)          ← 同上
    ↓
  O-2.f (CLI 統合)                    ← 全部終わった後の仕上げ
```

---

## 4. 想定 LOC とセッション数

| Phase | LOC | セッション |
|---|---:|---:|
| O-1 aipl_dist | ~700 | 1 |
| O-2.a where 句 | ~150 | 0.5 |
| O-2.b Z3 + Int | ~400 | 1 |
| O-2.c Real/Rat | ~150 | 0.5 |
| O-2.d cross-class + field | ~300 | 0.5-1 |
| O-2.e record structural | ~150 | 0.5 |
| O-2.f CLI | ~75 | 0.25 |
| **合計** | **~1925** | **~4-5 セッション** |

---

## 5. 各 Phase 完了時の Feature Matrix 更新

各 Phase 完了時に `docs/AIPL_Runtime_Feature_Matrix.{md,tex,pdf}` の該当行を
更新する (Python 同等の ✅ / 部分達成の 🟡 / 未着手の ❌)。

---

## 6. 既知の制約

- **Z3 OCaml binding** (`opam install z3`) はビルド時に Z3 system library が
  必要。macOS なら `brew install z3` で対応可。`opam` パッケージ名は要確認。
- **OCaml の `where`/`and`/`or`/`not`** はキーワード予約に追加が必要。既存
  プログラムでこれらを識別子として使っていないかは Python 側で確認済 (0 件)。
- **既存 `--type-check` (`/api/typecheck` JSON endpoint)** との関係: OCaml
  の type-check endpoint は維持しつつ、新たに `--check` 内で呼ばれる構造に。

---

## 参考

- Python 側完了レポート:
  `aice-pi-evolution/experiments/2026-05-17_aipl_v2_type_inference/PHASE_*_REPORT.md`
- Python 側実装:
  `src/python-aipl/aipl_inference.py` (1255 LOC, CE-1..CE-9)
  `src/python-aipl/aipl_dist.py` (591 LOC, DR-1..DR-9)
- Feature Matrix: `docs/AIPL_Runtime_Feature_Matrix.{md,pdf}`
- User Manual: `docs/AIPL_User_Manual.pdf` (§6, §7)
