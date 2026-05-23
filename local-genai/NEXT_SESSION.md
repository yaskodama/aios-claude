# 次回セッション再起動メモ + プロジェクト総括

## 2026-05-23: AIPL-v4 (Ollama proposer) Stage-1 smoke test 完了

### 結果サマリ
- **Ollama (gemma2:2b) を proposer にして Stage-1 に LLM-generated candidates を 4 個追加**
- **LLM 提案の L4 (`backoff, n=3, alpha=0.2`) が ppl 11.34 を達成** — 既存ベースライン N1 (ppl 15.52) を **-27% (=27% 改善)** で上回る
- ただし `reviewers.py` の reproducibility 評価が `uses_external_api=True` で -2 → norm スコアは N1 (2.167) が勝者表示。実 ppl での発見と rubric の評価軸の差を確認できた
- 1 回目の Ollama 呼び出しで 4/4 candidates valid (rejection 0、19.84s)
- 完全な lineage: `out/aipl_v4_stage1_20260523_113801.json`

### 構成
| 役割 | ファイル |
|---|---|
| メインドライバ | `local-genai/aipl_v4_evolve.py` (新規 327 行) |
| ベースライン (touch せず) | `local-genai/evolve.py` + `stages.py` + `candidates/ngram_real.py` |
| Ollama | `brew install ollama` で導入、`gemma2:2b` (1.6GB) pull 済み |
| デーモン起動 | `nohup /opt/homebrew/opt/ollama/bin/ollama serve > /tmp/ollama_serve.log 2>&1 &` |

### 各 LLM 候補の結果
| name | style | n | alpha | ppl | rationale |
|---|---|---:|---:|---:|---|
| **L4** | backoff | 3 | 0.20 | **11.34** | Reduce complexity by exploring a 3-gram model with backoff |
| L5 | plain | 1 | 1.80 | 18.60 | Explore the single unigram option for potential sparsity mitigation |
| L2 | backoff | 4 | 0.70 | 40.61 | Backoff n-grams improve performance on sparse datasets |
| L3 | plain | 5 | 1.50 | 102.82 | Explore high-order unigrams for improved context capture |

### コマンド (再現用)
```sh
# 1. Ollama daemon (起動済みなら省略)
nohup /opt/homebrew/opt/ollama/bin/ollama serve > /tmp/ollama_serve.log 2>&1 &

# 2. Stage-1 smoke test (LLM 4 candidates + 既存 N1/N2/N3 baselines)
local-genai/.venv/bin/python local-genai/aipl_v4_evolve.py --llm-candidates 4

# 3. サニティ確認 (LLM 無効化、ベースラインだけ)
local-genai/.venv/bin/python local-genai/aipl_v4_evolve.py --no-llm

# 4. 別モデルで試す
local-genai/.venv/bin/python local-genai/aipl_v4_evolve.py --model llama3.2:3b --llm-candidates 6
```

### 残課題 / 次の改善余地
1. **rubric 修正**: 現状 LLM 提案は `uses_external_api=True` で reproducibility -2 されるが、シード固定+lineage 保存で実質再現可能。`reviewers.py` を「LLM 提案でも lineage に proposer/model/prompt を保存していれば減点しない」改修案あり。
2. **Stage-2 以降への展開**: 今は Stage-1 (n-gram) のみ。CharRNN/TinyTransformer 段にも proposer を拡張するには、`evolve.py` の `evaluate_stage_n` (design estimator) 側と統合する必要あり。
3. **モデル比較**: gemma2:2b 以外 (llama3.2:3b, qwen2.5:3b, phi3:mini) の proposal 品質横並び評価。
4. **AIPL 完全自動ループ**: 親 = LLM, 子 = LLM, …の世代交代型ループ。現状は 1 stage = 1 ラウンドで終わる。

### 追加実験 (同日): 5 回集計でヒット率測定

`gemma2:2b` を 4 候補 × 5 回 (= 20 LLM 提案) で安定性測定:

| Run | LLM 最良 candidate | best ppl | vs N1 (15.52) |
|:--:|---|---:|---:|
| 1 | L5 `plain n=5 α=0.1` | 26.36 | −70% (悪化) |
| 2 | L2b `plain n=3 α=2.0` | 42.76 | −176% (悪化) |
| 3 | **L3 `backoff n=5 α=0.05`** | **12.70** | **+18% (改善)** ✅ |
| 4 | L1 `backoff n=4 α=0.2` | 18.99 | −22% (悪化) |
| 5 | L4 `plain n=2 α=1.8` | 19.24 | −24% (悪化) |

- **ヒット率 = 5 回中 1 回 (20%)** 単独計測、本セッション既存 2 回を合算で **7 回中 2 回 ≈ 29%**
- LLM call cost: 平均 3.7s (初回 5.3s、以降キャッシュ 3 秒台)
- 勝ちパターン: **`backoff + n≥3 + α≤0.2`** (実勝 2 回は両方このパターン)
- 負けパターン: **`plain + n≥5 + α≥1.0`** (必ず ppl > 100、5-gram のスパース性を高 α で均してしまい unigram 退化)

### 推奨される次のチューニング
```sh
# 1) 温度を下げて勝ちパターンに収束させる
local-genai/.venv/bin/python local-genai/aipl_v4_evolve.py --llm-candidates 6 --temperature 0.4

# 2) 候補プールを増やしてヒット確率を上げる (8 個独立なら少なくとも 1 勝 ≈ 83%)
local-genai/.venv/bin/python local-genai/aipl_v4_evolve.py --llm-candidates 8

# 3) 別モデルで比較
ollama pull llama3.2:3b
local-genai/.venv/bin/python local-genai/aipl_v4_evolve.py --model llama3.2:3b --llm-candidates 4
```

### 起動チェックリスト (再起動時)
1. `cd /Users/kodamay/ocaml-app/abclcp-project` (絶対パスでも可)
2. Ollama デーモン確認: `curl -s http://127.0.0.1:11434/api/tags >/dev/null && echo up || echo down`
   - down なら: `nohup /opt/homebrew/opt/ollama/bin/ollama serve > /tmp/ollama_serve.log 2>&1 &`
3. モデル確認: `ollama list` (gemma2:2b が無ければ `ollama pull gemma2:2b` ─ 約 1.6GB)
4. 実行: `local-genai/.venv/bin/python local-genai/aipl_v4_evolve.py --llm-candidates 4`
5. `--no-llm` で baselines だけのサニティラン (ppl 15.52 出れば OK)

---



## 再起動時に Claude に入力する文 (コピペ用)

```
local-genai/RESUME.md と local-genai/NEXT_SESSION.md を読み込んで現状を把握して下さい。

champion 系統:
  - 絶対 bpb champion = Stage-13-jp-heavy (1.71M, 113MB 多言語 15%JP, bpb 1.494)
    samples/fluency_eval_125.md で JP fluency 0.544、 EN 0.997、 Code 0.483 と確定
  - monolingual EN champion = Stage-11 (1.45M, 60MB, bpb 1.586, 1B tokens 訓練済)

完成済インフラ:
  - chat.py: 12 個のスラッシュコマンド + multi-turn + readline 履歴
  - web_chat.py: gradio で browser UI (5 model dropdown, multi-turn ChatInterface)
  - evaluate_samples.py: JP/EN/Code 自動採点 (3 軸 × 言語別)
  - generate_samples_bpe.py: 125 prompts (BR Shakespeare + Victorian + American + KJV + JP 古典/現代/哲学/短 + 質問 + コード + 多言語混合)
  - build_dialogue_samples.py: 5 scripted demo セッション
  - Stage-14-local .aice + Stage-14-cloud .aice (具体的な進化計画 spec)

次の選択肢:
  (a) Stage-15-jp-heavier (Aozora ×15 → JP 比 30%+, 訓練 ~13 時間)
  (b) Stage-13-extend (steps=320K で ~2B tokens, ~21 時間)
  (c) Stage-14-local 200MB × 1.5B tokens (~15 時間)
  (d) Stage-14-cloud (1GB × 10B, cloud_h100 必要)
  (e) AIPL-v4 (Ollama 接続で LLM-directed mutation)
  (f) アプリ最終仕上げ (chat.py / web_chat.py のパッケージング, dist 化)

あなたが推奨する次の一手と理由を一言で教えて下さい。
```

---

## プロジェクト総括 (2026-05-14 終了時点)

### 出発点
- Stage-1 bigram: 357 params, 9.5KB, ppl 15.52
- Stage-2 LSTM: 197K params on 100KB, ppl 5.23
- Stage-3 transformer: 失敗 (839K, 100KB, ppl 14.18)

### 最終到達点 (Stage-13-jp-heavy)
- 1.71M params, 113MB 多言語コーパス (英米 15% + KJV + 日本語 15%)
- bpb **1.494** / ppl/byte 2.817 (10MB tail bpb 2.014 から **-26%**)
- 訓練 10.5 時間 / 983M トークン処理
- 日本語 fluency 0.544 (Stage-11 の英語のみ 0.064 から +750%)
- 英語 fluency 0.997 (英語のみ champion と同等、 回帰なし)

### 進化ステージ全体 (Stage-1 → Stage-13)

| stage | params | corpus | bpb | ppl/byte |
|---|---:|---:|---:|---:|
| 1 | 357 | 9.5KB | — | (15.5) |
| 4 | 1.87M | 1MB | — | (5.93) |
| 5-RoPE | 165K | 1MB | — | (5.12) |
| 7-deeper-extend | 1.22M | 10MB | 2.014 | 4.04 |
| 9-BPE-vocab2048 | 1.45M | 10MB | 1.906 | 3.77 |
| 10-60MB | 1.45M | 60MB | 1.632 | 3.10 |
| 11-1B-tokens | 1.45M | 60MB (1B tok) | 1.586 | 3.00 |
| 12-multilingual | 1.71M | 99MB (1% JP) | 1.667 | 3.18 |
| **13-jp-heavy** | **1.71M** | **113MB (15% JP)** | **1.494** | **2.82** |

### 8 つの discovery

| 軸 | 由来 stage | 効果 |
|---|---|---|
| 直交 3 種正則化 | 4d-orth | 同サイズ -0.43 ppl |
| 深 cosine schedule | 4f-extend | -0.31 ppl |
| RoPE | 5-RoPE | -0.08 ppl + params -9% |
| 容量 + 10MB データ | 6d | -0.47 ppl |
| depth=4 → 6 | 7-deeper | -0.10 ppl |
| BPE-1024/2048/4096 | 8-9-12 | bpb -0.10 |
| 60MB データ + 1B tokens | 10-11 | bpb -0.32 |
| **MeCab + 多言語 + JP 比率 ×15** | **12-13** | **JP fluency 0.07 → 0.54 (+750%)** |

### Failed / 飽和

| 実験 | 結果 | 教訓 |
|---|---|---|
| width=192 (4 depth) | depth=6 (1.22M) に負け | depth >> width |
| depth=8 | depth=6 + 延長と並ぶだけ | depth 飽和 |
| 1MB scale で容量増 | 4b 855K より悪い | data-bound |
| BPE schedule 延長 | 微小改善 (-0.004) | BPE は早期飽和 |
| AIPL mock provider | ランダム sampling | LLM proposer 必要 |
| Stage-12 v0 (sequential) | bpb 12.5 (catastrophic) | train/hold 言語アンバランス必須 fix |

### 評価結果 (125-prompt suite, all 4 BPE champions)

| Champion | JP | EN | Code | 総合 |
|---|---:|---:|---:|---:|
| Stage-9 (10MB) | 0.076 | 0.998 | 0.415 | 0.564 |
| Stage-11 (60MB) | 0.064 | 0.998 | 0.460 | 0.561 |
| Stage-12 (1% JP) | 0.459 | 0.997 | 0.481 | 0.736 |
| **Stage-13 (15% JP)** | **0.544** | **0.997** | **0.483** | **0.773** |

**温度別 (Stage-13 JP)**: 0.6 → 0.671, 0.85 → 0.576, 1.05 → 0.384 → **日本語使用時は 0.6 推奨**

## 重要ファイル一覧

| ファイル | 用途 |
|---|---|
| `local-genai/RESUME.md` | 詳細な進化履歴と現状 |
| `local-genai/NEXT_SESSION.md` | この再起動メモ + 総括 |
| `local-genai/chat.py` | **CLI REPL (12 スラッシュコマンド + multi-turn + readline)** |
| **`local-genai/web_chat.py`** | **gradio browser UI (5 model dropdown, ChatInterface)** |
| `local-genai/evaluate_samples.py` | JP/EN/Code 自動採点 |
| `local-genai/generate_samples.py` | byte-level サンプル (20 prompts) |
| `local-genai/generate_samples_bpe.py` | BPE サンプル (125 prompts) |
| `local-genai/build_dialogue_samples.py` | 5 scripted demo セッション |
| `local-genai/build_500mb_corpus.py` | 多言語コーパス (MeCab + 英米 PG + Aozora) |
| `local-genai/build_100mb_corpus.py` | 60MB Victorian classics |
| `local-genai/build_10mb_corpus.py` | 10MB Shakespeare+KJV |
| `local-genai/train_stage4.py` | byte-level 訓練 (Stage-4-8) |
| `local-genai/train_stage8_bpe.py` | BPE 訓練 (Stage-8 〜 Stage-13) |
| `local-genai/candidates/transformer_real.py` | TinyTransformer (learned/RoPE) |
| `local-genai/common.py` | コーパス SHA-256 lock + ロード |
| `local-genai/fair_compare.py` | 共通 holdout 評価 |
| `local-genai/score_lineage.py` | AIPL lineage 再採点 |
| **`local-genai/out/transformer_stage13_jp_heavy.pt`** | **絶対 bpb champion** |
| `local-genai/out/transformer_stage11_1b_tokens_bpe.pt` | monolingual EN champion |
| `local-genai/samples/samples_stage13_jp_heavy_125.md` | 125-prompt samples |
| `local-genai/samples/fluency_eval_125.md` | 4 champion 横並び評価 |
| `local-genai/samples/sessions/demo_*.txt` | 5 dialogue demos |
| `aice-evolution-v2/examples/LocalGenAIStage14LocalOnlyJP.aice` | M2 単体完結版 spec |
| `aice-evolution-v2/examples/LocalGenAIStage14GigaCorpusJP.aice` | cloud 想定版 spec |

## 環境前提

- macOS arm64 (M2, MPS available)
- `local-genai/.venv/bin/python` (PyTorch 2.11.0)
- `tokenizers==0.23.1`, `fugashi==1.5.2`, `unidic-lite==1.0.8`, `gradio==6.14.0`
- `/opt/homebrew/bin/python3.13` (AIPL/aice 用)

## 主要コマンド (再現用)

### REPL で対話 (CLI)

```sh
local-genai/.venv/bin/python local-genai/chat.py --model bpe \
  --checkpoint local-genai/out/transformer_stage13_jp_heavy.pt \
  --tokenizer local-genai/out/tokenizer_stage13_jp_heavy.json
```

### ブラウザで対話 (WebUI)

```sh
local-genai/.venv/bin/python local-genai/web_chat.py
# → http://127.0.0.1:7860 (auto-fallback to 7861, 7862 if busy)
```

5 model dropdown / 温度・max・seed スライダ / multi-turn ON/OFF。

### Stage-13 を再生成 (10.5 時間)

```sh
# 1. corpus build (~30 分; PG/Aozora fetch + MeCab セグメント)
local-genai/.venv/bin/python local-genai/build_500mb_corpus.py
# → tinyshake_120MB_jp_heavy.txt (113MB)
#   (AOZORA_REPEAT=5 で日本語比 15% 確保)

# 2. 訓練
local-genai/.venv/bin/python local-genai/train_stage8_bpe.py \
  --corpus 120MB_jp_heavy --vocab-size 4096 \
  --steps 160000 --eval-every 2000 --warmup 1500 \
  --batch 24 --bptt 256 --ctx 256 \
  --depth 6 --d-model 128 --n-heads 4 \
  --lr 2e-3 --dropout 0.1 \
  --label-smoothing 0.05 --weight-decay 0.05 \
  --min-lr-frac 0.005 --pos-encoding rope \
  --out-name transformer_stage13_jp_heavy.pt \
  --tokenizer-name tokenizer_stage13_jp_heavy.json
```

### サンプル生成 + 評価

```sh
# 125 prompts × 3 温度 = 375 サンプル
local-genai/.venv/bin/python local-genai/generate_samples_bpe.py \
  --checkpoint local-genai/out/transformer_stage13_jp_heavy.pt \
  --tokenizer local-genai/out/tokenizer_stage13_jp_heavy.json

# 自動採点 + 横並び表
local-genai/.venv/bin/python local-genai/evaluate_samples.py \
  local-genai/samples/samples_stage9_bpe_vocab2048_125.md \
  local-genai/samples/samples_stage11_1b_tokens_bpe_125.md \
  local-genai/samples/samples_stage12_multi_bpe4k_125.md \
  local-genai/samples/samples_stage13_jp_heavy_125.md \
  --md-out local-genai/samples/fluency_eval_125.md
```

### 5 demo セッション生成

```sh
local-genai/.venv/bin/python local-genai/build_dialogue_samples.py
# → samples/sessions/demo_*.txt (5 ファイル)
```

## git 状態

- branch: `main`
- origin: `https://github.com/yaskodama/aios-claude.git`
- 最新コミット: `074d82d local-genai: web_chat.py — fix multi-turn errors in gradio 6 ChatInterface`

## 続行候補 (オススメ順)

### A. Stage-15-jp-heavier (AOZORA_REPEAT=15) ★ 推奨
- 内容: build_500mb_corpus.py の AOZORA_REPEAT を 5 → 15 に変更、 日本語比 30-40%
- 時間: corpus rebuild 30 分 + 訓練 12-15 時間 (一晩)
- 期待: JP fluency 0.54 → 0.65-0.75、 温度 1.05 でも日本語維持
- リスク: 英語が薄まる (Stage-13 EN 0.997 → 0.99 程度の低下)

### B. Stage-14-local (200MB × 1.5B tokens, jp_30)
- 内容: Stage-14-local spec の最初の実験。 英米 PG を 200MB まで拡大 + jp_ratio_30
- 時間: corpus build 1 時間 + 訓練 14-18 時間
- 期待: bpb 1.45 切り、 全方位の言語多様性向上

### C. Stage-13-extend (steps=320K = ~2B tokens)
- 内容: 既存 Stage-13 を schedule 2 倍延長
- 時間: ~21 時間
- 期待: 1.494 → 1.42-1.46 (best @ step 160K が未収束だった)

### D. アプリ最終化 (パッケージング + dist)
- 内容: `pip install local-genai` で配布可能化、 デフォルト Stage-13 checkpoint を含む
- 時間: 3-5 時間
- 価値: 「他の人が試せる」 状態に到達

### E. AIPL-v4 (Ollama 接続で本格進化計算)
- 内容: gemma2:2b 等を proposer にして AIPL を再起動
- 時間: 実装 3-5 時間 + 検証 10+ 時間
- 価値: メタ実験 (AI が人の発見を超えられるか)

### F. Stage-14-cloud (1GB × 10B tokens, cloud GPU)
- 内容: M2 不可、 cloud_h100 環境必要
- 時間: 1 時間 setup + 12-24 時間訓練
- 期待: bpb 1.20-1.35

## ppl / bpb 推移 (Stage-1 → Stage-13)

```
1MB tail ppl: 5.93 → 5.30 → 5.12 → 4.65 → 4.23  (Stage-4 → 7-extend)
10MB tail ppl: 7.32 → 4.73 → 4.04            (Stage-4d OOD → 7-extend)
10MB tail bpb: 2.014 → 1.906                 (byte → BPE)
60MB tail bpb: 1.632 → 1.586                 (Stage-10 → 11 1B tok)
99MB multi bpb: 1.667                        (Stage-12, 1% JP)
113MB jp-heavy bpb: 1.494                    (Stage-13, 15% JP)  ← 現 champion
```

## 評価インフラ確立 (本セッションの主成果)

Stage-13 訓練完了後、以下の評価インフラを構築:

1. **`evaluate_samples.py`** — JP/EN/Code 3 軸自動採点
2. **125-prompt suite** — 11 カテゴリの体系的 prompt
3. **全 4 BPE champion を 125-prompt で横並び評価** → fluency 単調改善を確認
4. **`build_dialogue_samples.py`** — 5 scripted demo セッション (chat.py /save の代替)
5. **`web_chat.py`** — gradio ベース browser UI (multi-turn 対応、 5 model dropdown)

これにより:
- 新 Stage の効果を **客観的・定量的に**比較可能 (fluency 数値)
- ローカル LLM を **実アプリ**として体験可能 (CLI + WebUI 両方)
- 過去 chamions も全部 retrospective で同基準評価可能
