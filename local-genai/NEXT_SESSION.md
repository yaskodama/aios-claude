# 次回セッション再起動メモ + プロジェクト総括

## 再起動時に Claude に入力する文 (コピペ用)

```
local-genai/RESUME.md と local-genai/NEXT_SESSION.md を読み込んで現状を把握して下さい。
champion は二系統 (両方とも depth=6, d=128, RoPE, 10MB 学習, 直交 3 種正則化):
  - byte-level ppl champion = Stage-7-deeper-extend (1.22M params, ppl 4.038 @ 10MB / 4.231 @ 1MB)
  - bits-per-byte champion = Stage-9-BPE-vocab2048 (1.45M params, bpb 1.906 / ppl_byte 3.749)

進化計算は depth / width / schedule / tokenizer 全方向を探索済み:
  - depth=6 + 訓練長 (40K step) が最適 (depth=8 / width=192 はいずれも劣る)
  - BPE は byte より高品質、 vocab 1024→2048 で更に改善 (ただし -0.005 bpb で飽和傾向)
  - AIPL revival は v1 (predictor 校正) / v2 (schema 拡張 4 軸追加) / v3 (coherence 強化)
    まで完了。 真の champion 再発見には LLM proposer (Ollama gemma2:2b 等) 接続が必要 (v4)

chat.py は 5 backend 対応済み: trigram / bigram / charrnn / transformer / bpe
最終 champion でデモは `local-genai/.venv/bin/python local-genai/chat.py --model bpe -t 0.85`

次の候補:
  (a) Stage-AIPL-v4: Ollama を AIPL に接続して LLM-directed mutation を実装
  (b) Stage-10-data: 10MB → 100MB に拡張 (現状 1.45M params が data-saturated 気味)
  (c) プロジェクト総括ドキュメント作成 (PROJECT_SUMMARY.md 等)
  (d) 別タスク

あなたが推奨する次の一手と理由を一言で教えて下さい。
```

---

## プロジェクト総括 (2026-05-11 終了時点)

### 出発点 (再起動直後の状態)
- Stage 1: bigram + Laplace (357 params, 9.5KB corpus, ppl 15.52)
- Stage 2 LSTM: R2 LSTM untied, 197K params on 100KB corpus (own holdout ppl 5.23)
- Stage 3 Tx 試行: 4-block transformer 失敗 (839K, 100KB own holdout ppl 14.18)
- 共通ベンチ未確立。 各 stage が自身の holdout でしか評価されていなかった。

### 最終状態
- **byte-level ppl champion**: Stage-7-deeper-extend (1.22M, 10MB 学習, 10MB tail ppl **4.038** / 1MB tail ppl **4.231**)
- **bits-per-byte champion**: Stage-9-BPE-vocab2048 (1.45M, 10MB 学習 + BPE-2048, **bpb 1.906** / ppl_byte 3.749)
- 共通 1MB / 10MB tail での fair_compare ベンチ確立
- AIPL の予測器・スキーマを実測値で再校正、新軸 4 つ追加 (v1-v3)
- chat.py で 5 backend 全てと対話可能、 生成サンプルも保存済み

### 累計改善

| 指標 | 出発点 (Stage-4 推定) | 最終 | 改善 |
|---|---:|---:|---:|
| 1MB tail ppl | 5.929 (Stage-4) | **4.231** (Stage-7-deeper-extend) | **-29%** |
| 10MB tail ppl | 7.32 (Stage-4d-orth OOD) | **4.038** (Stage-7-deeper-extend) | **-45%** |
| 10MB tail bpb | 2.014 (byte-level 同) | **1.906** (Stage-9-BPE-vocab2048) | -5% |

### 6 つの discovery (累計効果順)

| 軸 | 由来 stage | 単独効果 |
|---|---|---|
| 1. 10MB データ + 1M params | Stage-6c, 6d | 1MB tail -0.47 ppl (4d-orth → 6c) |
| 2. 直交 3 種正則化 (dropout 0.1 + ls 0.05 + wd 0.05) | Stage-4d-orth | 同サイズ -0.43 ppl (4b → 4d-orth) |
| 3. 訓練 20000 → 40000 step + 深 cosine 減衰 | Stage-7-deeper-extend | 1MB tail -0.31 ppl |
| 4. depth=4 → 6 | Stage-7-deeper | -0.10 ppl (6d → 7-deeper) |
| 5. BPE 1024-vocab トークナイザ | Stage-8-BPE | bpb -0.10 (-5%) + 訓練 1/4 時間 |
| 6. RoPE (rotary positional) | Stage-5-RoPE | -0.08 ppl + params -9% |

### Failed / 飽和 experiments (やってはダメと判明)

| 実験 | 結果 | 教訓 |
|---|---|---|
| 1MB scale で容量増 (Stage-4 1.87M) | overfit, ppl 5.93 (4b 855K より悪い) | データ量より容量が先に天井 |
| width=192 (Stage-8-wider, 1.82M) | 7-deeper (1.22M) に負け (+0.17 ppl) | **depth >> width** at this scale |
| depth=8 (Stage-8-deeper-plus, 1.61M) | 7-deeper-extend と並ぶ (+0.004 ppl) | depth scaling は飽和、 schedule 延長のほうが効く |
| BPE schedule 延長 (9-BPE-extend) | 8-BPE 比 -0.004 bpb のみ | BPE は token 情報量が高く早期飽和 |
| AIPL mock provider | ランダム sampling で coherence 不完全 | LLM proposer が必要 |

### ppl / bpb 推移 (Stage-4 → Stage-9)

```
1MB tail ppl: 5.93 → 5.73 → 5.52 → 5.30 → 5.20 → 5.12 → 4.77 → 4.65 → 4.54 → 4.23  (-29%)
10MB tail ppl:  —  →  —  →  —  → 7.32 → 4.73 → 4.25 → 4.19 → 4.06 → 4.04
                            (4d-orth OOD)                               (in-distribution)
10MB tail bpb:  —  →  —  →  —  →  —  →  —  →  —  →  —  →  —  → 2.01 → 1.92 → 1.91 → 1.91
                                                              (byte → BPE 切替)
```

---

## 重要ファイル一覧

| ファイル | 用途 |
|---|---|
| `local-genai/RESUME.md` | 詳細な進化履歴と現状 |
| `local-genai/NEXT_SESSION.md` | この再起動メモ + 総括 |
| `local-genai/train_stage4.py` | byte-level 訓練 (Stage-4 〜 Stage-8 全 stage) |
| `local-genai/train_stage8_bpe.py` | BPE 訓練 (Stage-8/9 BPE 系) |
| `local-genai/candidates/transformer_real.py` | TinyTransformer (learned/RoPE 両対応) |
| `local-genai/candidates/charrnn_real.py` | GRU/LSTM (Stage-2) |
| `local-genai/candidates/ngram_real.py` | n-gram (Stage-1) |
| `local-genai/candidates/design_estimator.py` | AIPL 予測器 (v3 まで校正済) |
| `local-genai/common.py` | コーパスロード + SHA-256 lock (10KB/100KB/1MB/10MB) |
| `local-genai/chat.py` | 5 backend 対応 REPL (n-gram / charrnn / transformer / BPE) |
| `local-genai/fair_compare.py` | 全 checkpoint を共通 holdout で再評価 (--corpus 1MB/10MB) |
| `local-genai/build_10mb_corpus.py` | PG から 10MB コーパス再生成 |
| `local-genai/generate_samples.py` | 20 プロンプト × 3 温度のサンプル生成 |
| `local-genai/score_lineage.py` | AIPL lineage を予測器+reviewer で再採点 |
| `local-genai/out/transformer_stage7_deeper_extend.pt` | byte-level ppl champion (1.22M) |
| `local-genai/out/transformer_stage9_bpe_vocab2048.pt` | bpb champion (1.45M) |
| `local-genai/out/tokenizer_stage9_bpe_vocab2048.json` | bpb champion 用 BPE tokenizer (vocab=2048) |
| `local-genai/corpus/tinyshake_10MB.txt` | 10MB コーパス (Shakespeare 全集 + KJV, hash locked) |
| `local-genai/samples/samples_stage7_deeper_extend.md` | byte-level champion の生成サンプル (20 プロンプト × 3 温度) |
| `aice-evolution-v2/examples/LocalGenAIScaledEvolutionJP.abcl` | AIPL evolution orchestrator (v2 で新軸追加) |
| `aice-evolution-v2/schemas/local_genai_scaled.schema.json` | gene schema (v2 で 4 軸追加) |

## 環境前提

- macOS arm64 (M2, MPS available)
- `local-genai/.venv/bin/python` (PyTorch 2.11.0, numpy 2.4.4)
- `tokenizers==0.23.1` (Stage-8/9-BPE 用、 .venv に install 済)
- `/opt/homebrew/bin/python3.13` (システム Python; AIPL/aice 用)

## 主要コマンド (再現用)

### byte-level ppl champion (Stage-7-deeper-extend) を再生成

```sh
local-genai/.venv/bin/python local-genai/train_stage4.py \
  --corpus 10MB \
  --steps 40000 --eval-every 1000 --warmup 1500 \
  --batch 24 --bptt 256 --ctx 256 \
  --depth 6 --d-model 128 --n-heads 4 \
  --lr 2e-3 --dropout 0.1 \
  --label-smoothing 0.05 --weight-decay 0.05 \
  --min-lr-frac 0.005 \
  --pos-encoding rope \
  --out-name transformer_stage7_deeper_extend.pt
# 約 193 分 (M2 MPS), best ppl 4.038 @ step 40000
```

### bpb champion (Stage-9-BPE-vocab2048) を再生成

```sh
local-genai/.venv/bin/python local-genai/train_stage8_bpe.py \
  --corpus 10MB --vocab-size 2048 \
  --steps 40000 --eval-every 1000 --warmup 1500 \
  --batch 24 --bptt 256 --ctx 256 \
  --depth 6 --d-model 128 --n-heads 4 \
  --lr 2e-3 --dropout 0.1 \
  --label-smoothing 0.05 --weight-decay 0.05 \
  --min-lr-frac 0.005 \
  --pos-encoding rope \
  --out-name transformer_stage9_bpe_vocab2048.pt \
  --tokenizer-name tokenizer_stage9_bpe_vocab2048.json
# 約 83 分 (M2 MPS), best bpb 1.906 @ step 36000
```

### 全 checkpoint を再評価

```sh
cd local-genai && .venv/bin/python fair_compare.py              # 1MB tail
cd local-genai && .venv/bin/python fair_compare.py --corpus 10MB  # 10MB tail
```

### champion と対話

```sh
# byte-level champion REPL
local-genai/.venv/bin/python local-genai/chat.py --model transformer

# BPE champion REPL (推奨、出力品質ベスト)
local-genai/.venv/bin/python local-genai/chat.py --model bpe

# 単発生成
local-genai/.venv/bin/python local-genai/chat.py --model bpe -t 0.85 \
  "In the beginning"
```

### サンプル文書生成

```sh
local-genai/.venv/bin/python local-genai/generate_samples.py
# → local-genai/samples/samples_stage7_deeper_extend.md (20 プロンプト × 3 温度)
```

### AIPL evolution 再走 (mock provider)

```sh
cd aice-evolution-v2/examples && \
  AIPL_AI_PROVIDER=mock /opt/homebrew/bin/python3.13 \
    ../../src/python-aipl/aipl_main.py LocalGenAIScaledEvolutionJP.abcl
cd ../../local-genai && .venv/bin/python score_lineage.py
```

## git 状態

- branch: `main`
- origin: `https://github.com/yaskodama/aios-claude.git`
- 最新コミット: `12ef1c5 aipl-revival v3: coherence violations + interaction bonuses`

## 続行候補 (オススメ順)

### 推奨 1: **Stage-AIPL-v4 (LLM proposer 接続)**
- Ollama (gemma2:2b 等) をローカル起動
- AIPL の `AIPL_AI_PROVIDER=ollama` (or 類似) で proposer を切替
- 過去 top genome を context に渡し、 「直交軸全 best にした候補」を起草させる
- 真の AIPL revival = AI が人の発見を再発見できるか
- 時間: Ollama setup ~30 分 + AIPL 再走 ~10 分 + 上位候補訓練

### 推奨 2: **Stage-10-data (100MB 拡張)**
- 1.45M params が 10MB で軽く data-saturated 気味
- Project Gutenberg + Wikipedia 一部 etc. で 100MB build
- Stage-9-BPE-vocab2048 recipe を 100MB で再学習
- bpb 1.8 切り狙い
- 時間: コーパス build ~30 分 + 訓練 ~150 分

### 推奨 3: **PROJECT_SUMMARY.md 作成**
- 進化計算プロジェクト全体の white paper 風サマリ
- 6 つの discovery を defining experiments と共に詳述
- 「人手 vs AIPL」 の比較セクション

### 4. **chat.py の生成品質を REPL 体験で評価**
- byte-level vs BPE の体感差を確認
- 温度 / max_chars / seed を変えて多様性を観察
