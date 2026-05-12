# 次回セッション再起動メモ + プロジェクト総括

## 再起動時に Claude に入力する文 (コピペ用)

```
local-genai/RESUME.md と local-genai/NEXT_SESSION.md を読み込んで現状を把握して下さい。

champion は二系統:
  - monolingual bpb champion = Stage-11 (1.45M params, 60MB 英語のみ, bpb 1.586, 1B tokens 訓練)
  - 多言語 (英米日本語) champion = Stage-12 (1.71M params, 99MB multilingual, bpb 1.667, MeCab + BPE-4096)

データ axis のスケーリングは確認済み (10MB → 60MB で bpb -14%、1B tokens で更に -2.8%)。
多言語化は infrastructure 確立 (MeCab + interleaved コーパス + BPE-4096) だが、 日本語比率 1% で
JP fluency は限定的。

次の選択肢:
  (a) Stage-13-jp-heavy: 日本語比率を 1% → 20% に上げて再訓練 (日本語 fluency 改善)
  (b) Stage-13-500MB: コーパス 99MB → 500MB に拡張 (英米作品追加 + 日本語増)
  (c) Stage-13-2B-tokens: Stage-12 を steps=320K に延長 (~2B tokens, ~25 時間)
  (d) AIPL-v4: Ollama (gemma2:2b) 接続で LLM-directed mutation

あなたが推奨する次の一手と理由を一言で教えて下さい。
```

---

## プロジェクト総括 (2026-05-13 終了時点)

### 出発点 (再起動直後の状態, Stage-1 〜 Stage-3)
- Stage-1 bigram: 357 params, 9.5KB, ppl 15.52
- Stage-2 LSTM: 197K params on 100KB, ppl 5.23
- Stage-3 transformer 失敗: 839K on 100KB, ppl 14.18
- 共通ベンチ未確立、最終的に "byte-level ppl" → "bits-per-byte (BPB)" に進化

### 最終到達点 (Stage-12)

**多言語 (英米日本語) champion**: Stage-12 (1.71M params, 99MB multilingual)
- BPE-4096 vocab + MeCab 日本語形態素分割
- bpb **1.667** / ppl/byte 3.176
- 訓練 12.4 時間, ~983M tokens 処理

**monolingual (英語のみ) champion**: Stage-11 (1.45M params, 60MB 英語)
- BPE-2048 vocab
- bpb **1.586** / ppl/byte 3.001
- 訓練 7.0 時間, ~983M tokens 処理 (= 1B トークン到達)

### 進化ステージ全体 (Stage-1 → Stage-12)

| stage | params | corpus | bpb / ppl/byte | 備考 |
|---|---:|---:|---:|---|
| 1 | 357 | 9.5KB | (ppl 15.52) | bigram |
| 2 | 197K | 100KB | (ppl 5.23) | LSTM |
| 4 | 1.87M | 1MB | — / 5.93 | 出発点 (overcapacity) |
| 4d-orth | 855K | 1MB | — / 5.30 | 直交 3 種正則化発見 |
| 4f-extend | 181K | 1MB | — / 5.20 | 訓練長 + 容量縮小 |
| 5-RoPE | 165K | 1MB | — / 5.12 | RoPE 採用 |
| 6d | 823K | 10MB | — / 4.19 | 容量 × データ |
| 7-deeper-extend | 1.22M | 10MB | **2.014** / 4.04 | byte-level peak |
| 8-BPE | 1.32M | 10MB | 1.915 / 3.77 | BPE-1024 |
| 9-BPE-vocab2048 | 1.45M | 10MB | 1.906 / 3.75 | BPE-2048 |
| 10-60MB | 1.45M | 60MB | 1.632 / 3.10 | データ 6x |
| **11-1B-tokens** | **1.45M** | **60MB** | **1.586 / 3.00** | **monolingual champion** |
| **12-multilingual** | **1.71M** | **99MB 多言語** | **1.667 / 3.18** | **多言語 champion (MeCab+BPE4k)** |

### 累計改善

| 指標 | 出発点 | 最終 | 改善 |
|---|---:|---:|---:|
| 1MB tail ppl | 5.93 (Stage-4) | 4.23 (Stage-7-extend) | -29% |
| 10MB tail ppl | 7.32 (OOD) | 4.04 (Stage-7-extend) | -45% |
| 10MB tail bpb | 2.014 (byte) | 1.906 (BPE) | -5% |
| 60MB bpb | 1.632 (Stage-10) | **1.586 (Stage-11)** | **-3%** |
| 多言語 bpb | — | **1.667 (Stage-12)** | 新軸 |

### 7 つの discovery (累計効果順)

| 軸 | 由来 stage | 効果 |
|---|---|---|
| 1. 10MB データ + 容量 ~1M params | Stage-6c, 6d | 1MB tail -0.47 ppl |
| 2. 直交 3 種正則化 (dropout 0.1 + ls 0.05 + wd 0.05) | Stage-4d-orth | -0.43 ppl |
| 3. 訓練 20K→40K step + 深 cosine 減衰 | Stage-7-deeper-extend | -0.31 ppl |
| 4. depth=4 → 6 | Stage-7-deeper | -0.10 ppl |
| 5. BPE 1024/2048 vocab トークナイザ | Stage-8/9-BPE | bpb -0.10 |
| 6. RoPE (rotary positional) | Stage-5-RoPE | -0.08 ppl + params -9% |
| 7. **60MB データ + 1B tokens 訓練** | **Stage-10, Stage-11** | **bpb -0.32** |
| 8. **多言語 (MeCab + BPE-4096 + interleaved)** | **Stage-12** | 多言語 infrastructure |

### Failed / 飽和 experiments

| 実験 | 結果 | 教訓 |
|---|---|---|
| width=192 (Stage-8-wider) | depth=6 (-0.17 ppl) | depth >> width |
| depth=8 (Stage-8-deeper-plus) | depth=6 + 延長と並ぶだけ | depth 飽和 |
| 1MB scale で容量増 (Stage-4 1.87M) | 4b 855K より悪い | data-bound |
| BPE schedule 延長 (9-BPE-extend) | -0.004 bpb のみ | BPE は早期飽和 |
| AIPL mock provider | ランダム sampling | LLM proposer 必要 |
| **Stage-12 untreated (sequential corpus)** | **bpb 12.5 (catastrophic)** | **train/holdout 言語アンバランス。 interleaving 必須** |

## 重要ファイル一覧

| ファイル | 用途 |
|---|---|
| `local-genai/RESUME.md` | 詳細な進化履歴と現状 |
| `local-genai/NEXT_SESSION.md` | この再起動メモ + 総括 |
| `local-genai/train_stage4.py` | byte-level 訓練 (Stage-4 〜 Stage-8) |
| `local-genai/train_stage8_bpe.py` | BPE 訓練 (Stage-8 〜 Stage-12) |
| `local-genai/candidates/transformer_real.py` | TinyTransformer (learned/RoPE) |
| `local-genai/common.py` | コーパスロード + SHA-256 lock (10KB〜100MB_multi) |
| `local-genai/chat.py` | 5 backend REPL (n-gram / charrnn / transformer / BPE) |
| `local-genai/fair_compare.py` | 共通 holdout 評価 (1MB / 10MB tail) |
| `local-genai/build_10mb_corpus.py` | 10MB Shakespeare+KJV ビルダー |
| `local-genai/build_100mb_corpus.py` | 60MB Victorian classics ビルダー |
| `local-genai/build_500mb_corpus.py` | **99MB 多言語 (英米日本語) ビルダー + MeCab** |
| `local-genai/generate_samples.py` | byte-level サンプル生成 |
| `local-genai/generate_samples_bpe.py` | BPE サンプル生成 (CLI 引数対応) |
| `local-genai/score_lineage.py` | AIPL lineage 再採点 |
| `local-genai/out/transformer_stage7_deeper_extend.pt` | byte-level ppl champion (1.22M) |
| `local-genai/out/transformer_stage9_bpe_vocab2048.pt` | 10MB BPE champion (1.45M) |
| **`local-genai/out/transformer_stage11_1b_tokens_bpe.pt`** | **monolingual bpb champion (1.45M, 60MB, 1B tokens)** |
| **`local-genai/out/transformer_stage12_multi_bpe4k.pt`** | **多言語 champion (1.71M, 99MB 英米日本語)** |
| `local-genai/corpus/tinyshake_10MB.txt` | 10MB Shakespeare+KJV (locked) |
| `local-genai/corpus/tinyshake_60MB.txt` | 60MB Victorian classics (locked) |
| **`local-genai/corpus/tinyshake_100MB_multi.txt`** | **99MB 多言語 interleaved (locked)** |
| `local-genai/samples/samples_*.md` | 各 champion の生成サンプル |
| `aice-evolution-v2/examples/LocalGenAIStage10DataExpansionJP.aice` | Stage-10+ 進化計算仕様 |
| `aice-evolution-v2/schemas/local_genai_stage10.schema.json` | 拡張 schema |

## 環境前提

- macOS arm64 (M2, MPS available)
- `local-genai/.venv/bin/python` (PyTorch 2.11.0, numpy 2.4.4)
- `tokenizers==0.23.1` (BPE 用)
- `fugashi==1.5.2` + `unidic-lite==1.0.8` (Japanese MeCab セグメント用)
- `/opt/homebrew/bin/python3.13` (システム Python; AIPL/aice 用)

## 主要コマンド (再現用)

### monolingual champion (Stage-11) を再生成

```sh
local-genai/.venv/bin/python local-genai/train_stage8_bpe.py \
  --corpus 60MB --vocab-size 2048 \
  --steps 160000 --eval-every 2000 --warmup 1500 \
  --batch 24 --bptt 256 --ctx 256 \
  --depth 6 --d-model 128 --n-heads 4 \
  --lr 2e-3 --dropout 0.1 \
  --label-smoothing 0.05 --weight-decay 0.05 \
  --min-lr-frac 0.005 \
  --pos-encoding rope \
  --out-name transformer_stage11_1b_tokens_bpe.pt \
  --tokenizer-name tokenizer_stage11_1b_tokens_bpe.json
# 約 7 時間 (M2 MPS), best bpb 1.586 @ step 152000
```

### 多言語 champion (Stage-12) を再生成

```sh
# 1. コーパス build (依存: tokenizers, fugashi, unidic-lite)
local-genai/.venv/bin/python local-genai/build_500mb_corpus.py
# → corpus/tinyshake_100MB_multi.txt (99MB, sha 51e9c3d5...66d7cb)

# 2. 訓練
local-genai/.venv/bin/python local-genai/train_stage8_bpe.py \
  --corpus 100MB_multi --vocab-size 4096 \
  --steps 160000 --eval-every 2000 --warmup 1500 \
  --batch 24 --bptt 256 --ctx 256 \
  --depth 6 --d-model 128 --n-heads 4 \
  --lr 2e-3 --dropout 0.1 \
  --label-smoothing 0.05 --weight-decay 0.05 \
  --min-lr-frac 0.005 \
  --pos-encoding rope \
  --out-name transformer_stage12_multi_bpe4k.pt \
  --tokenizer-name tokenizer_stage12_multi_bpe4k.json
# 約 12.4 時間 (M2 MPS), best bpb 1.667 @ step 152000
```

### champion と対話

```sh
# 英語 (monolingual)
local-genai/.venv/bin/python local-genai/chat.py --model bpe \
  --checkpoint local-genai/out/transformer_stage11_1b_tokens_bpe.pt \
  --tokenizer local-genai/out/tokenizer_stage11_1b_tokens_bpe.json \
  -t 0.85 "In the beginning"

# 多言語 (Stage-12)
local-genai/.venv/bin/python local-genai/chat.py --model bpe \
  --checkpoint local-genai/out/transformer_stage12_multi_bpe4k.pt \
  --tokenizer local-genai/out/tokenizer_stage12_multi_bpe4k.json \
  -t 0.85 "国境 の 長い トンネル を 抜ける と"
```

### サンプル文書生成

```sh
# byte-level champion
local-genai/.venv/bin/python local-genai/generate_samples.py

# Stage-9 (10MB BPE) champion
local-genai/.venv/bin/python local-genai/generate_samples_bpe.py
  # default は Stage-9; --checkpoint で他 BPE checkpoint 指定可

# Stage-11 (60MB 1B tokens) champion
local-genai/.venv/bin/python local-genai/generate_samples_bpe.py \
  --checkpoint local-genai/out/transformer_stage11_1b_tokens_bpe.pt \
  --tokenizer local-genai/out/tokenizer_stage11_1b_tokens_bpe.json

# Stage-12 多言語 champion
local-genai/.venv/bin/python local-genai/generate_samples_bpe.py \
  --checkpoint local-genai/out/transformer_stage12_multi_bpe4k.pt \
  --tokenizer local-genai/out/tokenizer_stage12_multi_bpe4k.json
```

## git 状態

- branch: `main`
- origin: `https://github.com/yaskodama/git@github.com:yaskodama/aios-claude.git`
- 最新コミット: `e9c4ef8 local-genai: Stage-12 — first multilingual model (US+UK English + Japanese)`

## 続行候補 (オススメ順)

### 推奨 1: **Stage-13-jp-heavy** (日本語比率上昇)
- 現状 Stage-12 corpus 99MB 中、 日本語 ~1MB (1%)
- Aozora をもっと多く取得 (作家 ID/file ID を正しく取得、 ZIP 形式の.txt も取り込み)
- 目標: 日本語 ~20-30MB (20-30%) で fluency 改善
- 時間: コーパス build 30 分 + 訓練 ~13 時間

### 推奨 2: **Stage-13-500MB** (英語コーパス拡大)
- 99MB → 500MB に。 失敗 fetch (Higuchi, Ogai 等) の URL 修復
- 英米 PG 追加 (もっと多くの Hardy, Trollope, Dickens; American: Frost, Sandburg, Whitman, Norris 等)
- 時間: コーパス build 1 時間 + 訓練 ~12 時間

### 推奨 3: **Stage-13-2B-tokens** (Stage-12 訓練延長)
- Stage-12 を steps=320K に延長 → 約 2B tokens 処理
- 時間: 訓練のみ ~25 時間 (long single run)

### 推奨 4: **AIPL-v4** (Ollama 接続)
- gemma2:2b 等をローカル起動
- AIPL の `AIPL_AI_PROVIDER=ollama` で LLM proposer 切替
- 人間が見つけた Pareto を AI が自動で更に押し下げられるか

### 推奨 5: **アプリ化** (chat.py 強化 + WebUI 検討)
- 既に 5 backend 対応済 (chat.py REPL)
- gradio や streamlit で簡易 WebUI
- プロジェクトの「成果披露」

## ppl / bpb トラジェクトリ (Stage-1 → Stage-12)

```
1MB tail ppl: 5.93 → 5.20 → 5.12 → 4.65 → 4.23 (Stage-4 → 7-extend, -29%)
10MB tail ppl: 7.32 → 4.73 → 4.19 → 4.04 (Stage-4d → 7-extend, -45%)
10MB tail bpb: 2.014 → 1.906 (byte → BPE-2048)
60MB bpb:      1.632 → 1.586 (Stage-10 → 11, 1B tokens)
99MB 多言語 bpb: 1.667 (Stage-12, 多言語化のコスト分上昇)
```
