# AIPL — Next Session Resume (2026-05-14)

最新コミット `bef02a9` (origin/main と同期済み).

```
bef02a9 JS-B/JS-N parser: eliminate the 10 AWAIT shift/reduce conflicts
ea7c11a AIPL: 71/71 sample smoke pass + final LR(1) cleanup
4474cfb parser + abclc examples: typed-parameter syntax + cleaner precedence rules
521f8fe AIPL: OCaml feature catch-up + C-codegen LLVM/OpenMP + signed remote
```

## Restart prompt to paste into Claude

```
docs/AIPL_NEXT_SESSION.md と docs/AIPL_Runtime_Feature_Matrix.{md,pdf} を
読み込んで現状を把握して下さい。さらに docs/AIPL_Design_and_Implementation.pdf
と docs/AICE_Meta_Research.pdf に研究論文が二本、
docs/AIPL_User_Manual.pdf にユーザマニュアルがあります。

AIPL は 7 ランタイム + 9 codegen バックエンド + WebSocket + remote
actors (HMAC) + 研究論文 2 本 + ユーザマニュアルの言語プロジェクトです。
今セッション (2026-05-14 まで) で OCaml ランタイムは Python と
ほぼ機能パリティに到達し、3 つのジェネレータ式パーサすべて
(ocamlyacc / Lark LALR / jison) が conflict-free になりました。

最初に走らせるべきは:
  dune build && bash abclc/_smoke_test.sh | tail -3
期待出力: total: 71  pass: 71  fail: 0
```

---

## 1. 全テストの現状 (再起動後にここが緑なら基準点に戻れる)

| Smoke スクリプト | 結果 |
|---|:-:|
| `dune build` | exit 0 |
| `bash abclc/_smoke_test.sh` | **71/71 PASS** |
| `bash src/test_remote_actor.sh` | **9/9 PASS** (plain + HMAC) |
| `bash src/test_c_llvm_openmp.sh` | **4/4 PASS** |
| `cd src/browser-abcl && bash _smoke_test.sh` | syntax 7/7, parse 4/4, typecheck 4/4 |
| `cd src/node-aipl-server && bash _smoke_test.sh` | 10/10 |

---

## 2. パーサのコンフリクト状況 (全て 0)

| ファイル | ツール | 利用ランタイム | s/r | r/r |
|---|---|---|:-:|:-:|
| `src/parser.mly` | ocamlyacc | OCaml + JS-O + C codegen (9 backends) | **0** | **0** |
| `src/python-aipl/grammar.lark` | Lark LALR | Py-A + Py-I | **0** | **0** |
| `src/browser-abcl/src/parser/grammar.jison` | jison | JS-B + JS-N | **0** | **0** |

dangling-else は `%nonassoc IFX < %nonassoc ELSE` + `%prec IFX` で明示的に解消されており、yacc/jison 警告 0 件。AWAIT は `%nonassoc UAWAIT` + `AWAIT expr %prec UAWAIT` で binop との shift/reduce を回避。

手書き再帰下降のため LR 系コンフリクト概念がない: `aice-evolution-v2/src/aice_parser.py` (`.aice` DSL), `aipl-self-host/level-c/parser.abcl` (AIPL セルフホスト).

---

## 3. 7 ランタイム × 主要機能 (確定値)

| 機能 | Py-A | Py-I | OCaml | JS-O | JS-B | JS-N | C |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| method injection | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| now / future / await | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `become` | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| `select` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| top-level functions | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| dynamic compile | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| worker pool | ✅ | ✅ | ✅ | ✅ | 🟡 | 🟡 | ❌ |
| text file I/O | ✅ | ✅ | ✅ | ✅ | ✅¹ | ✅¹ | ❌ |
| image I/O | ✅² | ✅² | ✅³ | ✅³ | ✅¹³ | ✅¹³ | ❌ |
| type inference | 🟡 trace | ✅ HM | ✅ HM | ✅ HM | ✅ flow | ✅ flow | ✅ HM+spec |
| type annotations | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ |
| records / tuples | ✅ / ✅ | ✅ / ✅ | ✅ / ✅ | ✅ / ✅ | ❌ | ❌ | 🟡 type only |
| arrays (var x[N][M]) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 🟡 |
| generics on functions | ❌ | ✅ Forall | ✅ Forall | ✅ | ❌ | ❌ | ❌ |
| remote actors (HTTP) | ✅ | ✅ | ✅ | ✅ | ❌ | 🟡 srv | ✅ |
| HMAC-signed remote | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| WebSocket | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| AI integration (ai_call) | ✅ | ✅ | ✅ | ✅ | ✅ mock | ✅ mock | ✅ |

¹ Node fs 注入経由 (browser では throw)  ² Pillow (PNG/JPEG/...)  ³ PPM P6 (純実装、no deps)

---

## 4. 今セッションで追加した OCaml 機能 (新規)

| 機能 | サンプル | 主要ファイル |
|---|---|---|
| records / tuples | `abclc/Records.abcl`, `Tuples.abcl` | ast.ml + types.ml + parser.mly + eval_thread.ml + infer.ml |
| dynamic compile | `abclc/Dynamic.abcl`, `DynamicWorkerPool.abcl` | repl_thread.ml (`add_prim "compile"` + extended `spawn`) |
| top-level functions | `abclc/Functions.abcl` | ast.ml (`function_decl`, `Return_value` 例外), eval_thread.ml |
| generics | `abclc/Generics.abcl` | infer.ml (`tvar_table`, `is_tvar_name`) |
| type annotations | `abclc/TypedDemo.abcl` | ast.ml (`type_expr`, `TypedVarDecl`, `var_annotations`), infer.ml `ty_of_type_expr` |
| method injection | `abclc/MethodPatch.abcl` | eval_thread.ml (`parse_methods_from_source`, `add_methods_to_class`/`...to_actor`) |
| sized arrays | `abclc/Arrays.abcl` | ast.ml (`ArraySized`), parser.mly (`dim_list`) |
| text file I/O | `abclc/FileIO.abcl` | repl_thread.ml (`read_file`/`write_file`/`append_file`/`file_exists`) |
| image I/O (PPM P6) | `abclc/ImageIO.abcl` | eval_thread.ml (`VImage`), repl_thread.ml (`image_*` 6 builtins) |
| remote actor 強化 + HMAC | `abclc/RemoteServer.abcl`, `RemoteClient.abcl` | **`src/hmac_sha256.ml` (新規, 173 LOC pure OCaml SHA-256/HMAC)**, remote_client.ml 例外処理、web_gateway.ml の openssl → 純 OCaml |

---

## 5. C codegen の新ターゲット

| フラグ | 出力 | スモーク |
|---|---|---|
| `aipl2c --llvm` | C + `__attribute__((hot/cold))` + `clang -emit-llvm` 用ヘッダ | Hello/counter × LLVM PASS |
| `aipl2c --openmp` | C + `<omp.h>` + `#pragma omp parallel for` spawn loop + `#pragma omp atomic` カウンタ | Hello/counter × OpenMP PASS (gcc-15 -fopenmp 利用) |

総 backend 数: **default (pthread)** / **LLVM** / **OpenMP** / **SDL2 (--gui)** / **Xinu** / **Python** / **Pony** / **Erlang** / **Go** / **Prolog** = **10 種** (LLVM/OpenMP を別カウントすれば).

---

## 6. JS-B / JS-N の追加

- `src/browser-abcl/src/runtime.js` に `_fs* / _image*` メソッド (host injected fs)
- `src/browser-abcl/src/parser/grammar.jison` に sized array (`var x[N]`), `IndexExpr`, `IndexAssign`, `unescapeString`
- `src/node-aipl-server/server.mjs` で `runtime.injectFs(fs)` を自動実行 → text & image I/O が動く

---

## 7. 文書

| ファイル | 内容 |
|---|---|
| `docs/AIPL_Runtime_Feature_Matrix.{md,tex,pdf}` | 7 ランタイム × ~30 機能の最新比較表 (12 ページ) |
| `docs/AIPL_User_Manual.{tex,pdf}` | xelatex + Hiragino のユーザマニュアル (15 ページ、新規作成済み) |
| `docs/AIPL_Design_and_Implementation.{tex,pdf}` | 設計と実装の論文 (HM 推論中心) |
| `docs/AICE_Meta_Research.{tex,pdf}` | AICE Meta Pipeline (GA-driven LLM 問題解決) 論文 |
| `USER_MANUAL.md` | Markdown 版ユーザマニュアル |
| `docs/AIPL_Type_Soundness_Report.pdf` | 型健全性レポート |

---

## 8. 重要な設計判断 (再起動時に思い出すべきポイント)

### 8.1 オーバーロード解決の destructive-unify 順序依存

`pick_overload` (infer.ml) は失敗時に tvar が rollback されないため、最初に当たった候補が tvar を pin する。これを利用して **「具体的なオーバーロードを先に試す」** ようにすべく、`typing_env.ml` で `+` の polymorphic string-concat を**先に登録**し、numeric overloads を後に登録 (`add_mono`/`add_poly` は prepend するので numeric が先に試される)。

### 8.2 `var sum = 0.;` (float 初期化) が必要な理由

`await` / `now` の戻り値は静的に追えないため TAny として扱う。`var sum = 0; sum = sum + await(...)` で `sum + TAny` が `(int, float) → float` overload と当たり、`sum = TFloat` で TInt との unify 失敗。回避: `var sum = 0.;` で最初から float 化。

### 8.3 TypedVarDecl の normalize 戦略

AST の `VarDecl` は 30+ 箇所で pattern match されている。型注釈サポートのために `VarDecl` シグネチャを変えると ripple が大きいため、**`TypedVarDecl(x, T, e)` を AST に追加し、`Ast.normalize_program` でパース直後に `TypedVarDecl → VarDecl + 側ハッシュ (Ast.var_annotations)`** に展開。型検査は `Ast.lookup_var_annotation s.sloc` で取り出し、runtime / codegen は VarDecl だけを見ればよい。

### 8.4 OpenMP は actor タスク化していない (デッドロック回避)

`#pragma omp task` で actor_main を起動する案は **デッドロックする** (`taskwait` が actor_main の永久ループを待ち、watchdog はその後ろにあるため global_shutdown が来ない)。安全策として per-actor は **pthread のまま**、OpenMP は spawn loop の並列化 + 原子カウンタに限定。

### 8.5 LR(1) クリーン化のキー

`parser.mly` の優先順位スタック (低 → 高):
```
%nonassoc IFX             /* if-else より低い */
%nonassoc ELSE
%left EQ NEQ
%left LT GT LE GE
%left PLUS MINUS
%left TIMES DIV
%left DOT LBRACK          /* postfix access — 最高に近い */
%nonassoc UAWAIT          /* AWAIT prefix — 最高 */
```
+ `IF (...) stmt %prec IFX` と `AWAIT expr %prec UAWAIT` のタグ。JS-B の jison も `%nonassoc UAWAIT` 追加で同じ解決。

### 8.6 remote actor のエラー伝搬

`remote_client.ml` の `with_connection` ヘルパで Unix.Unix_error を全部 `Error msg` に包む:
- `remote_send` (fire-and-forget): 失敗時 stderr に出力、actor 続行
- `remote_call` (now / future): 失敗時 `"<remote-error: ...>"` を返す (呼び出し元アクターが死なない)

### 8.7 HMAC-SHA256 純 OCaml 実装

`src/hmac_sha256.ml` — 外部依存ゼロ (cryptokit/digestif/sha 不要)。RFC 6234 (SHA-256) と RFC 4231 (HMAC) のテストベクタで検証済み。`web_gateway.ml` の旧 `openssl dgst` subprocess を置換 (リクエスト毎の fork が消えた)。

---

## 9. ビルド前提

| 必要 | 説明 |
|---|---|
| OCaml + dune + ocamlyacc + ocamllex | OCaml 側 |
| tsdl | SDL2 binding (gui_ide.exe 用) |
| Node.js + npm + jison | JS-B 側のパーサ再生成 |
| Python 3 + lark | Py-A / Py-I (`pip install --user --break-system-packages lark`) |
| `gcc-15` (`/opt/homebrew/bin/gcc-15`) | OpenMP codegen 検証 (Apple Clang は libomp を別途入れる必要) |
| `clang` (LLVM tool chain) | LLVM codegen 検証 |
| `xelatex` + Hiragino フォント | 論文 / マニュアル PDF 再ビルド (`docs/build_pdf.sh`) |

---

## 10. サンプル一覧 (今セッション新規追加)

```
abclc/Arrays.abcl              abclc/MethodPatch.abcl       abclc/RemoteClient.abcl
abclc/Dynamic.abcl             abclc/Records.abcl           abclc/RemoteServer.abcl
abclc/DynamicWorkerPool.abcl   abclc/Tuples.abcl            abclc/_jso_server.abcl
abclc/FileIO.abcl              abclc/TypedDemo.abcl
abclc/Functions.abcl
abclc/Generics.abcl
abclc/ImageIO.abcl

src/browser-abcl/arrays.abcl    src/browser-abcl/file_io.abcl    src/browser-abcl/image_io.abcl
```

---

## 11. 残タスク候補 (次セッションの選択肢)

優先度の目安付き。

1. ✏️ **C codegen で records / tuples を実装** (現状 🟡 "type only") — value 表現と struct emit が必要
2. ✏️ **C codegen で arrays multi-dim を完全対応** (現状 🟡)
3. ✏️ **JS-B / JS-N に method injection / dynamic compile** (残る ❌) — parser 拡張 + runtime
4. ✏️ **JS-B / JS-N に HMAC-signed remote** — Node の crypto モジュールを使う簡単な実装
5. ✏️ **OCaml の image I/O を PNG 対応** — 現状 PPM のみ; `digestif` か miniz/zlib ベースの PNG エンコーダが必要
6. ✏️ **AIPL self-host tower** — `aipl-self-host/level-c/parser.abcl` の現状確認、level-d 試作
7. ✏️ **Phase 11+ effect / linear / owned / transient を OCaml 側に移植** — 現状 abclc/Phase1*.abcl はサンプルのみ
8. 📄 **C codegen 9 backend の論文化** — `aipl2c --pony --erlang --go --prolog --llvm --openmp` の比較研究
9. 🔧 **OCaml の `var pad[R][C] = -1` を許可** — unary minus が parser.mly に無い (pre-existing)

---

## 12. 再開時のヘルスチェック

```bash
cd /Users/kodamay/ocaml-app/abclcp-project

# Step 1: ビルド
dune build && echo "✓ build OK"

# Step 2: パーサのコンフリクト数
ocamlyacc -v src/parser.mly 2>&1 | tail -1  # 期待: 空 (0 conflict)

# Step 3: フルスモーク
bash abclc/_smoke_test.sh 2>&1 | tail -3
# 期待: total: 71  pass: 71  fail: 0

bash src/test_remote_actor.sh 2>&1 | tail -3
# 期待: pass: 9  fail: 0

bash src/test_c_llvm_openmp.sh 2>&1 | tail -3
# 期待: total: 4  pass: 4  fail: 0
```

すべて緑なら基準点に戻れています。
