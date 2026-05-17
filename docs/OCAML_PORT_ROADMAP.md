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
- `abclc/WhereClause.abcl` で parse + script execution 確認
- 既存 71 abclc サンプル 71/71 PASS
- `aipl_dist` smoke 8/8 PASS

実測 LOC: 約 80 行 (推定 100-200 内).

#### O-2.b (1 session, medium): Z3 binding + Int refinement (CE-1, CE-9)

- `opam install z3` で OCaml バインディング導入
- `src/refinement.ml` を新規作成 (Z3 Solver wrapper)
- `_z3_check_int : expr -> bool * string` を実装
- `infer.ml` の制約解決後に refinement check を呼ぶ
- declaration-time の vacuously-false 検出 (CE-9)

推定: 300-500 LOC

#### O-2.c (1 session, medium): Real / Rat refinement (CE-6)

- O-2.b の sort dispatch を Real に拡張 (z3.Real)
- Float リテラル を refinement predicate で許可 (lexer に既にあるか?)
- `Rat` 型は OCaml AIPL に既存か? → 必要なら追加

推定: 100-200 LOC

#### O-2.d (1 session, medium): Cross-class inference + actor field 共有 (CE-2, CE-4)

- OCaml `infer.ml` は class type を持つが、method の return / param TVars を
  cross-class で逆推論する path が弱い
- Python と同様に `class_sigs` を pre-pass で構築
- Actor field を `class_fields[cls][name]` で method 横断共有

推定: 200-400 LOC

#### O-2.e (1 session, easy): Record structural (CE-5)

- OCaml は records を持つが、unify は nominal
- `unify_record` を fields の集合一致 + 各 field の type 再帰 unify に変更
- `infer.ml` の `Var → TyRecord(...)` constrain を追加

推定: 100-200 LOC

#### O-2.f (1 session, easy): CLI 統合 (CE-7, CE-8)

- `repl_thread.ml` に `--infer` / `--check` フラグ追加
- 同 section ヘッダ付きで出力

推定: 50-100 LOC

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
