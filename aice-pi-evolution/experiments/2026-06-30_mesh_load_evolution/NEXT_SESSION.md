# NEXT_SESSION — soft-Xinu mesh 並列負荷分散 進化

最終更新: 2026-06-30 / branch `feat/xinu-jit-target` / 最終 commit `324a027`（push 済 origin）

## 0. このセッションでやったこと

1. **MacのXinuエミュレータ基盤を選定** — QEMU(`arm-qemu`)本物Xinuは現在ビルド破損中（§4）。
   ユーザ選択で **soft Xinu 多ノード**（Py-I アクターノード）に決定。
2. **soft Xinu メッシュ**を起動・疎通検証（`_smoke_dist.py` の 3ノード coordinator→solver→verifier ライブ通過）。
3. **並列負荷分散の進化実験**を新規作成・コミット（このディレクトリ）。
   N-Queens の列（非均等コスト）→ M ワーカーノード割当を GA で makespan 最小化、
   実メッシュでライブ並列検証。**N=10/M=4 で x3.48（naive x3.17）**。
4. **視覚UIのXinuシミュレータ** = `~/projects/aice-avm` を起動（§3）。

## 1. このディレクトリの構成

| File | 役割 |
|------|------|
| `nq_worker.tmpl.abcl` | 1メッシュノード。`worker.solve(n,k)` → N-Queens 部分木解数。`web_listen(__PORT__)` を mesh.py が書換。|
| `mesh.py` | M ノード起動/駆動（`localhost:9101..`）。`python3 mesh.py start <M>` 単体起動も可。|
| `evolve.py` | 1ノードで列コスト実測 → 列→ノード割当を GA 最小化 → naive/round-robin/greedy-LPT 比較 → **実メッシュでライブ検証** → `RESULTS.md` 出力。|
| `RESULTS.md` | 直近 run サマリ（自動生成）。|
| `_run/` | 生成された per-node abcl + ログ（gitignore 済）。|

## 2. 再起動・実行手順（soft mesh）

```bash
cd ~/ocaml-app/abclcp-project/aice-pi-evolution/experiments/2026-06-30_mesh_load_evolution
python3 evolve.py [N=11] [M=4] [GEN=60]      # メッシュ自動起動→進化→ライブ検証→自動停止
# 手動で常駐させたい場合:
python3 mesh.py start 4                       # 9101..9104 に4ノード（Ctrl-Cで停止）
```

要点（メッシュのイディオム）:
- ノード公開: AIPL `class W { method m(){...reply(v)} } var w=new W(); web_listen(PORT);`（アクター名=小文字インスタンス名）。
- Python駆動: `from aipl_remote import remote_call_sync`（`src/python-aipl` を sys.path に追加済）→
  `remote_call_sync("localhost:PORT","worker","solve",[n,k])`（`POST /api/json/call` 同期応答）。
- AIPL側リモート: `remote_now(addr,"worker","solve",n,k)`。
- 並列化: ローカルProxyアクターを `future` して各ノードを別スレッド化、`await` で集約。

## 3. 視覚UIのXinuシミュレータ（aice-avm）

```bash
cd ~/projects/aice-avm
dune build && ./_build/default/server.exe 8080      # http://localhost:8080/ にXinuデスクトップ（ブラウザ自動オープン）
./_build/default/send.exe 127.0.0.1:8080 samples/Rotate4Lines.abcl   # アクター投入
```
- SHIFT+クリックでメニュー、Actors窓で .avm 一覧、Mesh Control Center 窓あり。
- 詳細は aice-avm リポジトリ（別 repo `yaskodama/aice-avm`, branch main）と memory `project_aice_avm_xinu_merge`。

## 4. ★罠・既知の制約

- **arm-qemu(QEMU `versatilepb`/arm1176)の本物Xinuはビルド破損**（`~/projects/xinu-raz/xinu`）:
  - `include/rcu.h` の `rcu_mb()`=`dmb ish`（ARMv7命令、rpi3 Cortex-A53専用）→ ARMv6 では CP15 `mcr p15,0,r0,c7,c10,5` 要。アーキ分岐すれば直る（このセッションで一度直して動作確認→ツリーは元に戻した）。
  - 共通 `system/clkinit.c` が `IRQ_TIMER`（rpi3 `bcm2835.h` 固有）参照 → arm-qemu は pl190 VIC + sp804 タイマ構成なので未定義。要移植。
  - master/arm-rpi3-port 両ブランチとも同状態。
  - これを直すと `2026-05-21_xinu_cluster/cluster_bridge.py`（UART1 TCP ルーティング）で **QEMU多ノード本物Xinuメッシュ**が組める。
- Py-I の remote 送信は**動く**（過去 memory `feedback_aipl_pyi_quirks` の「send remote() OCaml-only」は古い）。
- N-Queens 列コストは非均等（中央列が端の ~4.5倍、N=8 で解数 4,8,16,18,18,16,8,4）。N を上げるとコスト分散が広がり GA の効果が拡大。

## 5. 次の一手（並列負荷分散の進化、続き）

- **ワークスティーリング**を進化軸に追加（遊休ノードが未処理列を pull）。現状は静的割当のみ。
- N と M を増やしてスケール検証（N=12/13、M=6/8）。
- soft ノード + 実機 Pi（rpi3/4/5）混在メッシュ（`host:port` を足すだけ）。
- 余力で arm-qemu を §4 の2点修正で復活させ、QEMU本物Xinu多ノードメッシュと soft メッシュを同一オーケストレータで比較。
