# RESTART — ローカル LLM サーバ群 復旧手順 (2026-05-25 時点)

Mac 再起動後、 このファイルの通りに実行すれば全サーバが戻る。
作業ディレクトリは常に `cd /Users/kodamay/ocaml-app/abclcp-project`。
Python は必ず venv の `local-genai/.venv/bin/python` を使う。

---

## 稼働するサーバ (3 つ)

| # | サーバ | ポート | 用途 | 会話できる? |
|---|---|---:|---|---|
| 1 | Ollama daemon | 11434 | gemma3:4b / llama3.2:3b / gemma2:2b をホスト | (土台) |
| 2 | `ollama_chat.py` | 7861 | **実 LLM チャット**。 Excel/CSV 読み込み + 音声入力対応 | ✅ できる |
| 3 | `aipl_v4_serve.py` | 7862 | n-gram champion 配信。 テキスト継続 / perplexity 研究 | ❌ できない (4byte 文脈) |

- **会話したいとき = 7861** (http://127.0.0.1:7861/)
- 7862 は研究用のテキスト継続器。 会話は成立しない。
- ⚠️ ポート注意: `schedule_app.py` も 7862 を使う設計。 n-gram サーバと同時起動不可。 どちらか一方。

---

## 復旧手順 (この順に)

### 1. Ollama daemon

```sh
cd /Users/kodamay/ocaml-app/abclcp-project
curl -s http://127.0.0.1:11434/api/tags >/dev/null && echo "Ollama UP" || \
  nohup ollama serve > /tmp/ollama_serve.log 2>&1 &
# 起動待ち
until curl -s http://127.0.0.1:11434/api/tags >/dev/null 2>&1; do sleep 1; done
echo "Ollama ready"
```

### 2. 実 LLM チャット (Excel 対応) — port 7861

```sh
cd /Users/kodamay/ocaml-app/abclcp-project
nohup local-genai/.venv/bin/python local-genai/ollama_chat.py > /tmp/ollama_chat.log 2>&1 &
sleep 8
curl -s -o /dev/null -w '7861: HTTP %{http_code}\n' http://127.0.0.1:7861/
open http://127.0.0.1:7861/
```

### 3. n-gram champion サーバ — port 7862 (任意)

```sh
cd /Users/kodamay/ocaml-app/abclcp-project
nohup local-genai/.venv/bin/python local-genai/aipl_v4_serve.py --port 7862 > /tmp/aipl_v4_serve.log 2>&1 &
sleep 5
curl -s http://127.0.0.1:7862/api/health
```

---

## 動作確認

```sh
# 実 LLM チャットが会話できるか (文脈保持テスト)
curl -s http://127.0.0.1:11434/api/chat -d '{"model":"gemma3:4b","messages":[{"role":"user","content":"私の好きな色は青です。"},{"role":"assistant","content":"了解しました。"},{"role":"user","content":"好きな色は何色でしたか?一言で。"}],"stream":false}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['message']['content'].strip())"
# → 「青です。」が返れば OK

# n-gram champion の perplexity (raw / fair)
curl -s -X POST http://127.0.0.1:7862/api/perplexity -H 'Content-Type: application/json' \
  -d '{"genome":"Lkcm3","corpus":"10KB"}'              # raw  ≈ 3.4764
curl -s -X POST http://127.0.0.1:7862/api/perplexity -H 'Content-Type: application/json' \
  -d '{"genome":"Lkcm3","corpus":"10KB","fair":true}' # fair ≈ 3.6042
```

---

## Excel/CSV を LLM に読ませる

1. http://127.0.0.1:7861/ を開く
2. 「📄 Excel / CSV をアップロード」欄に `.xlsx`/`.xls`/`.csv`/`.tsv` をドロップ
3. 「✅ 読み込み完了: シート名 (N行×M列)」が出たら表の中身を質問
4. モデルは **gemma3:4b** 推奨 (集計に強い)。 大きい表は先頭 40行×20列 / 8000字に truncate
5. 普通の雑談に戻すときは System prompt 欄を空にする (初期値は n-gram 進化の説明文)

---

## 停止

```sh
pkill -f ollama_chat.py      # 7861
pkill -f aipl_v4_serve.py    # 7862
pkill -f "ollama serve"      # 11434 (他が使うなら残す)
```

---

## 現在の状態メモ (2026-05-25)

- n-gram absolute champion: **`Lkcm3`** (kn_ctx_mod n=5 α=1.0 sm=6 dm=20 ms=0.82 md=0.66 mid=0.95)
  - raw geomean 5.3856 / **fair geomean 5.6545** (fair でも champion)
  - 注: raw の改善はほぼ未正規化アーティファクト。 fair (renormalize) が正しい指標。 詳細は `aipl_v4_serve.py` の `/api/perplexity {"fair":true}`
- manifest: `local-genai/out/served_genomes.json` (10 genome、 fair_* フィールド付き)
- 依存追加: `openpyxl` (Excel 読み込み用、 venv に install 済)
```sh
local-genai/.venv/bin/pip install openpyxl   # 環境を作り直したとき
```
