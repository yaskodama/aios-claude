# NEXT_SESSION — AIPL マルチランタイム・ダッシュボード群

2026-05-27 のセッション成果。再開時はこの文書を最初に読む。
AIPL の各ランタイム（Py-I / OCaml / JS-server / JS-browser / C）に「ブラウザ・ダッシュボード」を用意した。
加えて進化計算パイプライン（goal→.aice→.ga.json→.aipl）の専用ダッシュボードを新設。

## リポジトリ / ブランチ / HEAD
- `/Users/kodamay/ocaml-app/abclcp-project`, branch `main`, HEAD `817cb65`
  （= 本セッションの全ダッシュボード成果を commit & push 済み。Py-I bounded-buffer は手前の `ef3caff`）。
- remote `yaskodama/aios-claude`。
- ★`src/python-aipl/aipl_ai.py` は**未コミットのまま温存**（ユーザ指示・モデル env override）。**触らない・コミットしない**。
- 言語ルール: チャットは日本語、プログラムの予約語・UI/コンソール文字列は英語。

## 6 つのダッシュボード（起動コマンドと URL）

すべて 127.0.0.1。OCaml/C は先に `cd /Users/kodamay/ocaml-app/abclcp-project && dune build` が必要。

### 1. Py-I (Python) — port 8899
```sh
cd /Users/kodamay/ocaml-app/abclcp-project
python3 src/python-aipl/aipl_main.py --dashboard 8899 \
  aice-pi-evolution/experiments/2026-05-27_dining_mac_xinu/local_diners.abcl
# → http://127.0.0.1:8899/actors
```
- プログラム選択（local_diners / dine_dynamic / mac_diners / ring_demo / **bounded_buffer**）+ Start/Suspend/Resume/End、アクター表、コンソール、可視化。
- **bounded_buffer.abcl**（容量20・2P/2C・速度スライダー `/api/speed`）は **commit 済み (`ef3caff`)**。詳細は `aice-pi-evolution/experiments/2026-05-27_dining_mac_xinu/NEXT_SESSION.md`。

### 2. OCaml web gateway — port 8080
```sh
cd /Users/kodamay/ocaml-app/abclcp-project && dune build
{ printf 'load src/gateway_launch.abcl\ncompile\n'; sleep 1000000; } | _build/default/src/repl_thread.exe
# → http://localhost:8080/dashboard
```
- ★`repl_thread.exe -f file` の `script` は **load 相当で実行しない**。top-level（`web_listen`）を走らせるには `load`→`compile` を stdin で送る。`sleep` で stdin を開いたままにしてプロセス（web スレッド）を存続させる。
- 機能: プログラム選択（Dining Philosophers / Bounded buffer cap20+速度バー / Ping-Pong / Counter / Hello）、Load&Run / Start / Stop / **Reset**、アクター表（`/api/actors`）、コンソール（`/api/log`、キーは `next`）、**有限バッファ可視化**（コンソール出力をパースして FIFO 再構成）、**ソース表示**（`/api/source?file=`）、**速度スライダー**（`send p0.set_speed(ms)` を `/api/repl` 送信）。
- ★**C/P 矢印**: ユーザ指摘で `gateway_dashboard.js` の `flowArrow` 始終点を反転済み（**視覚確認は未取得**。元は producer→buffer→consumer の右向き）。違っていれば戻す。
- ★OCaml アクターは停止フラグ無しの `while true` ループ → 強制終了不可。`reset` は actor_table をクリアするが実行中スレッドは送信先消失で静止（有限デモは実用上クリーン）。切替前に Stop 推奨。
- 関連ファイル（**未コミット**）: `src/gateway_dashboard.html` / `src/gateway_dashboard.js` / `src/gateway_launch.abcl`、ランタイム改修 `src/web_gateway.ml`（routes: `/dashboard`, `/gateway_dashboard.js`, `/api/source`）/ `src/repl_thread.ml`（`reset`/`clear` コマンド実装）/ `src/eval_thread.ml`（`clear_actor_table` / `clear_web_logs`）。例題 `abclc/bounded_buffer20.abcl` / `abclc/PingPongDemo.abcl`。

### 3. 進化計算パイプライン — port 8700
```sh
cd /Users/kodamay/ocaml-app/abclcp-project/aice-evolution-v2
python3 evolution_dashboard.py
# → http://127.0.0.1:8700/
```
- 4 段: 目標(goal) →[変換]→ **.aice** →[変換]→ **.ga.json** →[変換]→ **.aipl**。各枠は編集可。生成物は `aice-evolution-v2/out/dashboard/` に保存。
- 変換の実体: goal→.aice は LLM (`aipl_ai.chat_ai`、AI 無し/失敗時は `examples/CompilerEvolution.aice` テンプレに目標差込でフォールバック)、.aice→.ga.json は `src/aice_parser.lower(parse(...))`、.ga.json→.aipl は `src/aipl_codegen.generate_program(spec, schema)`。
- **以前の実験例プルダウン**: `examples/*.aice`（20件）を `/api/examples` で列挙、`/api/example?name=X` で本文取得（traversal ガード付き）。
- ★既知の落とし穴（修正済み）: ボタンの fetch は `/api/<ep>`（`/<ep>` だと unknown endpoint）。
- ファイル（**未コミット**）: `aice-evolution-v2/evolution_dashboard.py`。

### 4. JS (サーバーあり) — Node — port 8090
```sh
cd /Users/kodamay/ocaml-app/abclcp-project/src/node-aipl-server
node server.mjs        # node v25 + ws 導入済み
# → http://localhost:8090/
```
- OCaml gateway の Node 版（browser-abcl ランタイムを再利用）。エディタ + 例題プルダウン（**Dining Philosophers** 有限版 / Counter / Ping-Pong / Hello）+ **Run**（`/api/run`）+ Type-check（`/api/typecheck`）+ コンソール。
- ★JS ランタイムは **run-to-completion**（stdout を返して終了）。無限ループ不可 → 例題はすべて**有限**。
- 改修（**未コミット**）: `src/node-aipl-server/server.mjs` の `STATUS_HTML` を操作ダッシュボードに差し替え（元は API ドキュメントだけだった）。

### 5. JS (サーバーなし) — ブラウザ内実行 — port 8765 (静的配信のみ)
```sh
cd /Users/kodamay/ocaml-app/abclcp-project/src/browser-abcl
python3 -m http.server 8765 --bind 127.0.0.1
# → http://127.0.0.1:8765/
```
- AIPL の解析・実行を**すべてブラウザ内 JS** で行う。HTTP サーバは ES モジュール配信のみ（AIPL 実行はしない）。
- index は「Browser AIPL」: デモへのリンク（philosophers.html / bounded_buffer.html / bounded_buffer_visual.html / rotate4lines / cooperative_* / drone）+ Open Browser Console。**コード変更なし**（既存資産）。

### 6. C — port 8095
```sh
cd /Users/kodamay/ocaml-app/abclcp-project && dune build   # aipl2c.exe
python3 src/c_dashboard.py
# → http://127.0.0.1:8095/
```
- AIPL→C（`aipl2c`）→ `cc … abcl_nextgen_runtime.c -I src -pthread` → ネイティブ実行。生成 C と stdout を表示。
- **ターゲット言語セレクタ**: C / Erlang / Prolog / Go / Pony / Python / LLVM / OpenMP / Xinu。Translate=ソース表示、**Build & Run は C のみ**（他はソース表示+注記）。
- 例題（C 動作確認済み）: **Dining Philosophers**（注釈版）/ Ping-Pong / Counter / Hello。
- ★C ランタイムの注意:
  - actor 参照をフィールド/引数で渡すには**型注釈必須**（`var lo: Fork = f0;`、`method init(.., l: Fork, h: Fork)`）。無注釈だと codegen が int 化して動かない（`member reference base type 'int'`）。
  - `wait`/`sleep` は **C ランタイム未対応**（`_b_wait` undefined）→ 遅延なし・有限構成にする。
  - デフォルトのメッセージ上限が小さい → `--max-msgs N`（ダッシュは既定 4000）。
  - グローバル名 send（`send pong.ping(..)`）は注釈なしでも可。
  - 「rlang」= **Erlang** と解釈（aipl2c のターゲット名。R言語は未対応）。
- ファイル（**未コミット**）: `src/c_dashboard.py`。生成物 `out/c_dashboard/`（コミット不要）。

## 全部まとめて再起動（コピペ用）
```sh
cd /Users/kodamay/ocaml-app/abclcp-project
dune build
# 1) Py-I
python3 src/python-aipl/aipl_main.py --dashboard 8899 \
  aice-pi-evolution/experiments/2026-05-27_dining_mac_xinu/local_diners.abcl >/tmp/d_pyi.log 2>&1 &
# 2) OCaml gateway
{ printf 'load src/gateway_launch.abcl\ncompile\n'; sleep 1000000; } | _build/default/src/repl_thread.exe >/tmp/d_ocaml.log 2>&1 &
# 3) Evolution
( cd aice-evolution-v2 && python3 evolution_dashboard.py >/tmp/d_evo.log 2>&1 & )
# 4) JS Node
( cd src/node-aipl-server && node server.mjs >/tmp/d_node.log 2>&1 & )
# 5) JS browser (static)
( cd src/browser-abcl && python3 -m http.server 8765 --bind 127.0.0.1 >/tmp/d_browser.log 2>&1 & )
# 6) C
python3 src/c_dashboard.py >/tmp/d_c.log 2>&1 &
```
URL: 8899/actors · 8080/dashboard · 8700/ · 8090/ · 8765/ · 8095/
停止: `pkill -f aipl_main.py; pkill -f repl_thread.exe; pkill -f 'sleep 1000000'; pkill -f evolution_dashboard.py; pkill -f 'node server.mjs'; pkill -f 'http.server 8765'; pkill -f c_dashboard.py`

## コミット状況
- 本セッションのダッシュボード一式は `817cb65` で **commit & push 済み**
  （web_gateway/repl_thread/eval_thread.ml、gateway_dashboard.{html,js}、gateway_launch.abcl、
  c_dashboard.py、node-aipl-server/server.mjs、evolution_dashboard.py、
  bounded_buffer20.abcl、PingPongDemo.abcl、本ハンドオフ）。
- **未コミットのまま**: `src/python-aipl/aipl_ai.py`（温存・触らない）。`out/c_dashboard/` は生成物（無視）。
- 未確認事項: OCaml バッファ可視化の C/P 矢印向き（反転済みだが視覚未確認。違えば `gateway_dashboard.js` の `flowArrow` 引数順を戻す）。
