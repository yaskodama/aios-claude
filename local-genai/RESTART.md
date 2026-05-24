# RESTART — 音声 LLM アプリ群 復旧手順 (2026-05-24)

このドキュメントを読めば、 Mac 再起動後でも全アプリを 5 分で復旧できる。

---

## 📋 アプリ概要

4 個のアプリが並走している。

| | サーバ版 (Python + Ollama) | サーバレス版 (matching.site44.com) |
|---|---|---|
| 💬 チャット | `ollama_chat.py` @ :7861 | `voice-chat/` (HTML+JS) |
| 🎙️ スケジュール帳 | `schedule_app.py` @ :7862 | `voice-schedule/` (HTML+JS) |

サーバ版 = 自分の Mac だけで動く、 高品質 (gemma3:4b)。
サーバレス版 = 世界中のブラウザから動く、 軽量 (Qwen2.5-0.5B)。

---

## 🔧 サーバ版 復旧手順

### 1. Ollama daemon 起動 (まだなら)

```sh
# まず起動確認
curl -s http://127.0.0.1:11434/api/tags >/dev/null && echo "Ollama UP" || echo "Ollama DOWN"

# DOWN なら起動
nohup /opt/homebrew/opt/ollama/bin/ollama serve > /tmp/ollama_serve.log 2>&1 &
disown
sleep 2
```

### 2. モデル確認 (3 個入っているはず)

```sh
/opt/homebrew/opt/ollama/bin/ollama list
# 期待:
#   gemma3:4b      a2af6cc3eb7f    3.3 GB   ← デフォルト (最新、 2025-03)
#   llama3.2:3b    a80c4f17acd5    2.0 GB
#   gemma2:2b      8ccf136fdd52    1.6 GB
```

もし足りないものがあれば:
```sh
/opt/homebrew/opt/ollama/bin/ollama pull gemma3:4b
/opt/homebrew/opt/ollama/bin/ollama pull llama3.2:3b
/opt/homebrew/opt/ollama/bin/ollama pull gemma2:2b
```

### 3. チャット + スケジュール帳 を起動

```sh
cd /Users/kodamay/ocaml-app/abclcp-project

# チャット (port 7861)
nohup local-genai/.venv/bin/python -u local-genai/ollama_chat.py \
  > /tmp/ollama_chat.log 2>&1 &
disown

# スケジュール帳 (port 7862)
nohup local-genai/.venv/bin/python -u local-genai/schedule_app.py \
  > /tmp/schedule_app.log 2>&1 &
disown

# 確認
sleep 3
curl -s -o /dev/null -w "chat (7861): %{http_code}\n" http://127.0.0.1:7861/
curl -s -o /dev/null -w "schedule (7862): %{http_code}\n" http://127.0.0.1:7862/
```

### 4. ブラウザで開く

```sh
open http://127.0.0.1:7861/    # チャット
open http://127.0.0.1:7862/    # スケジュール帳
```

### 5. 停止コマンド (片付け)

```sh
pkill -f ollama_chat.py
pkill -f schedule_app.py
# Ollama daemon は他のアプリも使う可能性があるので普段は止めない
# 止める時: pkill -f "ollama serve"
```

---

## 🌐 サーバレス版 (matching.site44.com)

Dropbox が site44 に同期するため、 起動操作は不要。 直接ブラウザで開くだけ。

### 公開 URL

| アプリ | URL |
|---|---|
| 💬 チャット | https://matching.site44.com/voice-chat/ |
| 🎙️ スケジュール帳 | https://matching.site44.com/voice-schedule/ |

⚠️ `http://maching.site44.com/...` (typo) は別ドメインで存在しない。 `matching` 正しい綴りで。

### ソース (編集する時)

```
/Users/kodamay/Dropbox/アプリ/site44/matching.site44.com/
├── voice-chat/
│   ├── index.html
│   ├── app.js
│   └── style.css
└── voice-schedule/
    ├── index.html
    ├── app.js
    └── style.css
```

ファイル編集 → Dropbox 同期 (自動、 数十秒) → site44 反映 → ブラウザ Cmd+Shift+R で確認。

### ローカルテスト (Dropbox 同期前に試したい時)

```sh
cd "/Users/kodamay/Dropbox/アプリ/site44/matching.site44.com"
nohup python3 -m http.server 8001 > /tmp/voice_static.log 2>&1 &
disown
open http://127.0.0.1:8001/voice-chat/
open http://127.0.0.1:8001/voice-schedule/
```

---

## 🤖 使われているモデル

### サーバ版 LLM (Ollama)

| モデル | サイズ | 用途 |
|---|---:|---|
| **gemma3:4b** | 3.3 GB | デフォルト (Google 2025-03、 日本語良好) |
| llama3.2:3b | 2.0 GB | 副 (Meta 2024-09) |
| gemma2:2b | 1.6 GB | 副 (最軽量、 高速) |

### サーバ版 STT (Python in-process)

| | |
|---|---|
| エンジン | faster-whisper |
| モデル | `small` (~480MB int8) |
| キャッシュ | `~/.cache/huggingface/hub/models--Systran--faster-whisper-small/` |

### サーバレス版 LLM (ブラウザ Transformers.js)

| モデル | dtype | DL | 用途 |
|---|---|---:|---|
| **Qwen2.5-0.5B-Instruct** | int8 | 488 MB | デフォルト (全ブラウザ対応) |
| SmolLM2-360M | int8 | 348 MB | 超軽量、 英語向け |
| Qwen2.5-0.5B-Instruct | q4f16 | 460 MB | Chrome 121+ のみ |
| Qwen2.5-1.5B-Instruct | q4f16 | 1.2 GB | 高品質、 WebGPU 推奨 |

ブラウザ IndexedDB にキャッシュされる (~/Library/Application Support/Chromium 等)。

### サーバレス版 STT

Web Speech API (ブラウザ標準、 Chrome は Google クラウド、 Safari は Apple クラウド経由)。 ローカル動作ではないが API キー不要。

---

## 💾 データ保存先

| アプリ | 保存場所 |
|---|---|
| サーバ版スケジュール | `local-genai/schedule.json` |
| サーバレス版スケジュール | ブラウザの `localStorage["voice_schedule_events_v1"]` |
| サーバレス版チャット履歴 | ブラウザの `localStorage["voice_chat_history_v1"]` |
| Whisper モデル | `~/.cache/huggingface/hub/` |
| Ollama モデル | `~/.ollama/models/` |

---

## 🎙️ 音声コマンド (両アプリ共通)

| 種類 | キーワード例 |
|---|---|
| 追加 (デフォルト) | 「明日 14 時に山田さんとミーティング」 |
| 削除 | 「<タイトル>を削除」 「サクジョ」 「明日の予定をキャンセル」 |
| 確認 | 「はい」 「OK」 「確定」 |
| 取消 | 「いいえ」 「キャンセル」 |
| 停止 | 「ストップ」 「終了」 「やめて」 |

---

## 🔍 トラブルシュート

| 症状 | 対処 |
|---|---|
| サーバ版 ロード失敗 | `pkill -f ollama_chat.py; nohup ...` で再起動 |
| Whisper モデル DL 失敗 | `~/.cache/huggingface/` クリアして再起動 |
| サーバレス LLM ロード失敗 (Float16) | int8 モデルに切替 (自動フォールバックも有り) |
| サーバレス LLM ロード失敗 (メモリ) | 0.5B または SmolLM2-360M に切替 |
| マイクが反応しない | ブラウザの設定 → サイトの権限 → マイク を許可 |
| 文字起こしが「中食」(誤認) | 自動補正で「昼食」に変換される。 schedule_app.py の `WHISPER_HOMOPHONE_FIX` に追加可 |
| 「ストップ」と言っても録音継続 | 確認: voice-chat は完全停止、 voice-schedule は paused 状態 (▶ 再開で復帰) |
| iPhone から site44 開けるが LLM 落ちる | Safari 17+ 必須、 メモリ 4GB 以上のモデル推奨 |

---

## 📂 主要ファイル一覧

```
/Users/kodamay/ocaml-app/abclcp-project/local-genai/
├── ollama_chat.py            # サーバ版チャット
├── schedule_app.py           # サーバ版スケジュール (~1500 行)
├── schedule.json             # 予定保存ファイル
├── .venv/                    # Python venv (gradio, faster-whisper, etc.)
├── RESTART.md                # このファイル
├── NEXT_SESSION.md           # AIPL-v4 等過去履歴
└── (他、 AIPL-v4 関連の python ファイル多数)

/Users/kodamay/Dropbox/アプリ/site44/matching.site44.com/
├── voice-chat/               # サーバレス版チャット
│   ├── index.html
│   ├── app.js                # ~360 行
│   └── style.css
└── voice-schedule/           # サーバレス版スケジュール
    ├── index.html
    ├── app.js                # ~600 行
    └── style.css
```

---

## 🚀 ワンライナー復旧 (コピペ用)

Mac 再起動後にこれだけ実行すれば全部復活:

```sh
# 1. Ollama 起動 (既に動いていればスキップ)
curl -s http://127.0.0.1:11434/api/tags >/dev/null 2>&1 || \
  (nohup /opt/homebrew/opt/ollama/bin/ollama serve > /tmp/ollama_serve.log 2>&1 & disown)

sleep 2

# 2. サーバ版チャット + スケジュール起動
cd /Users/kodamay/ocaml-app/abclcp-project
nohup local-genai/.venv/bin/python -u local-genai/ollama_chat.py > /tmp/ollama_chat.log 2>&1 &
nohup local-genai/.venv/bin/python -u local-genai/schedule_app.py > /tmp/schedule_app.log 2>&1 &
disown

sleep 3
echo "サーバ版起動完了。 開きます…"
open http://127.0.0.1:7861/   # チャット
open http://127.0.0.1:7862/   # スケジュール帳

# 3. (オプション) サーバレス版をブラウザで
# open https://matching.site44.com/voice-chat/
# open https://matching.site44.com/voice-schedule/
```

---

## 📝 セッション履歴の要約 (このアプリ群を作るまで)

1. **AIPL-v4** = n-gram LM の進化計算ループ (`aipl_v4_autoloop.py`、 別系統)
2. **音声入力追加** = ollama_chat.py にマイク + faster-whisper
3. **schedule_app.py 新規作成** = 音声で予定追加 → LLM 抽出 → JSON 保存
4. **ハンズフリー化** = 無音検出で自動送信、 atomic ハンドラで取りこぼし防止
5. **音声削除** = LLM が ID 特定 → 「はい」/「いいえ」で確認
6. **チェックボックス削除** = 表から選択して一括削除
7. **カレンダー表示** = 今月+来月の HTML テーブル、 イベント色付け
8. **サーバレス版** = matching.site44.com に静的 HTML/JS デプロイ
9. **gemma3:4b 追加** = サーバ版を Google 最新モデルにアップグレード
10. **このドキュメント** = 復旧手順を文書化 (2026-05-24)

詳細は `local-genai/NEXT_SESSION.md` も参照。
