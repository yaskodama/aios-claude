# NEXT_SESSION — 分散ダイニング (Mac + 実機 Xinu Pi3) + Py-I ダッシュボード

2026-05-27 時点のハンドオフ。再起動／再開時はこの文書を最初に読む。

## 全体像
実機 Raspberry Pi 3 上の Embedded Xinu と Mac の Py-I (Python AIPL インタプリタ) で
**5 人の哲学者問題を分散実行**する。Mac 側にはブラウザ・ダッシュボード
(現在のプログラム / 起動中アクター / 状態 / コンソール / リング可視化) があり、
プログラムの開始・中断・再開・終了・切替ができる。

## リポジトリ / ブランチ / HEAD
- **Xinu (実機 Pi3)**: `/Users/kodamay/projects/xinu-raz/xinu`, branch `arm-rpi3-port`,
  HEAD `62b13d9` (suicide + reset + 50-meal)。remote `yaskodama/xinu-rpi`。
- **Mac (Py-I 等)**: `/Users/kodamay/ocaml-app/abclcp-project`, branch `main`,
  HEAD `ef3caff` (有限バッファデモ + 速度スライダー)。remote `yaskodama/aios-claude`。
- ★`src/python-aipl/aipl_ai.py` は**未コミットのまま温存**(ユーザ指示)。モデル default の
  env override。触らない・コミットしない。

## 言語ルール (ユーザ指示)
チャットのやり取りは**日本語**、プログラムの予約語・文字列(UI/コンソール/print)は**英語**。

## Xinu 側 (実機 Pi3, arm-rpi3)
- ネットワーク: 静的 IP **192.168.3.50/24**, gw .3.1。RPC over TCP **5555**, webactor HTTP **8080**。
- **起動時は dining アクター 0** (空起動)。`webactor_autostart` (apps/webactor.c) が:
  ETH0 UP 待ち → `netUp(192.168.3.50)` → `abcl_rt_init()` (runtime のみ) → `abcl_rpc_tcp_start(5555)`。
  (aipl_main も webactor_start も呼ばない → 最初の SPAWN Fork が確定で id 0)。
- **RPC opcode** (apps/abcl_xinu_rpc.c, TCP line プロトコル, single-client 持続接続):
  `PING` / `RESET` / `SEND <id> <m> [args]` / `QUERY <id> <field>` / `LIST` /
  `SPAWN <Class> [args, ref:N=V_OBJ]` / `LOAD <name> <len>\n<body>` / `COMPILE <name>` / `RUN <name>`。
- **アクター runtime** (apps/abcl_program.c, 生成コード+手編集): CLASS_Fork/Philosopher/WebReceiver。
  `abcl_actor_suicide(id)` (dead=1→consumer ループ break→スレッド終了)、`abcl_rt_reset()`
  (全アクター協調停止+semaphore 解放+n_objects=0)、Philosopher は **50 食で suicide**、
  英語ナレーション (`abcl_phil_say`: thinking/took a fork/eating/put down forks)。
  ★Pi3 注意: LDREX/STREX 不可 → mailbox は disable()/restore() 版 (`_XINU_PLATFORM_ARM_RPI3_`)。
- **HDMI ウィンドウ** (apps/gwm.c): info / **AIPL console (print)** (左中) / **AIPL actors (live)** (右,
  ID/CLASS/ST(act/idle/new/dead)/RECV/PROC/PEND/thread) / soft keyboard (下, y470)。
- **ビルド & 焼き**:
  ```sh
  cd /Users/kodamay/projects/xinu-raz/xinu/compile
  make PLATFORM=arm-rpi3            # -> xinu.boot (現状 ~285940 B = RESET 対応版)
  # SD/USB を Mac に挿す → /Volumes/XINU/kernel.img に cp + sync + eject → Pi で電源入れ直し
  cp xinu.boot /Volumes/XINU/kernel.img && sync && diskutil eject /Volumes/XINU
  ```
- 動作確認: `python3` socket で 192.168.3.50:5555 に `PING`→`OK pong=1`, `LIST`→`OK n_actors=0`。

## Mac 側 Py-I ダッシュボード
```sh
cd /Users/kodamay/ocaml-app/abclcp-project
python3 src/python-aipl/aipl_main.py --dashboard 8899 \
  aice-pi-evolution/experiments/2026-05-27_dining_mac_xinu/local_diners.aipl
# → http://127.0.0.1:8899/actors  (起動時は "not started"; Start で開始)
```
- ダッシュボードがプログラムのライフサイクルを管理 (main は常駐)。**未開始で起動**。
- UI: Program セレクタ + **Switch/Load** / **Start** / **Suspend** / **Resume** / **End**、
  状態 (not started/running/paused/stopped/ended)、**可視化** (canvas 760×360)、**Console** (print 出力)、
  アクター表 (thread id 付き = 各アクターは別 threading.Thread)、Current program ソース。
  - 可視化は実行中のクラスで自動切替 (`aipl_dashboard.py` の `drawViz`): Philosopher/Node/Fork →
    **リング** (哲学者を色分け + フォークを使用 2 名の中点に配置 + 保持フォーク→保持者へ緑矢印)、
    Buffer → **有限バッファ** (`drawBuffer`: 20 スロットを横一列 1 段で表示, 満=値表示,
    head=水色枠/tail=橙枠, producer 上→帯→consumer 下のフロー矢印)。
  - ★`_json_safe` は list/tuple を再帰して JSON 配列にする (Buffer の `slots` 配列を図に出すため)。
- API: `GET /api/programs|actors|program|console` , `POST /api/load|control|speed`。
- 切替対象 (実験ディレクトリ内の *.aipl を自動列挙):
  - `local_diners.aipl` — **local 5** (Pi 不要, 全 5 哲学者+5 fork 可視化, 50 食, suicide)
  - `dine_dynamic.aipl` — **3 Mac + 2 Xinu, 動的** (要 Pi)。冒頭で RESET → ソース送付(LOAD)→
    実機コンパイル(COMPILE/RUN)→ SPAWN → 50 食 + suicide。**何度でも再ラン可**。
  - `mac_diners.aipl` — **3 Mac + 2 Xinu, 静的** (要 Pi)。RESET → SPAWN (事前リンク済クラス, 動的
    コンパイルなし) → 50 食 + suicide。**何度でも再ラン可**。
  - `ring_demo.aipl` — local token ring 4 (Pi 不要, 切替テスト用)。
  - `bounded_buffer.aipl` — **有限バッファ (producer/consumer)** local (Pi 不要)。
    1 個の Buffer アクターが容量 **20** のリングを所有 (mailbox 順序 = 相互排他, 追加ロック無し)。
    Producer ×2 (各 80 個) / Consumer ×2。満杯なら `refused`→バックオフ (back-pressure)、
    空なら `empty`→待機。全 producer 完了 + drain 後に consumer へ `closed`→suicide で終了。
    ★**速度スライダー**: 可視化下に Producer/Consumer interval の 2 本のレンジバー (50–2000ms,
    左=速い)。ドラッグで `POST /api/speed {produce_ms,consume_ms}` → 実行中アクターの `delay`
    フィールドを直接書換 (再起動不要、次の 1 個目から反映)。`Buffer` アクターがいる時のみ表示。
- AIPL ビルトイン: `suicide()` (自アクター終了), `remote_call/remote_now(hub,"_",op,...)` で
  `reset/spawn/load/compile/run/ping/list` + `field`/メソッド送信。hub=`uart1://192.168.3.50:5555`。

## 再開手順 (典型)
1. Pi に SD/USB + ethernet + serial + HDMI、電源 ON。`ping 192.168.3.50` で疎通確認。
2. socket で `PING`/`LIST` (n_actors=0 のはず)。違えば一度電源入れ直し。
3. ダッシュボード起動 (上記)。ブラウザで /actors を開く。
4. Program を選んで Start。remote 版 (dine_dynamic / mac_diners) は Pi が必要。

## 既知の事項 / 注意
- ★**P2 がリモートで約半分しか食べない**のは**フェアネス問題 (バグでない)**。Xinu の即時
  コールバック取得 vs Mac のポーリングの速度差 + リング上の P2 の位置。ユーザは「このまま」でOK。
- ★**再ラン**: Xinu のアクター表はラン間でリセットされない → dine_dynamic/mac_diners は冒頭で
  `RESET` を呼ぶので再起動不要で繰り返せる。RESET 無しだと fork id がずれ MAX_OBJECTS(16) で頭打ち。
- ★**Pi が高負荷/連続テストでウェッジ**することがある (ping 無応答)。電源入れ直しで復帰。
- ★**Pi3 LAN78xx**: ping は低レートで安定。RX FIFO end (FCT_RX/TX_FIFO_END=0x17) + BCE 修正済
  (commit `725fe35`)。高レート/大フレームは弱い (詳細 [[project-xinu-rpi3-port]])。
- リモート版ダッシュボードの可視化は **Mac 側 P1/P2/P3 のみ表示** (fork/P4/P5 は Xinu 側で
  Py-I scheduler に無い)。Xinu 側も出すには RPC で QUERY して図に含める拡張が要る。
- host ツール: serial 読みは termios B115200 + `ls /dev/cu.usbserial-*` (名前が変わる)。

詳細・経緯は memory `project_dining_mac_xinu.md` / `project_xinu_rpi3_port.md` を参照。
