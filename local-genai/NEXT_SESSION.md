# 次回セッション再起動メモ + プロジェクト総括

---

## 🔄 SESSION RESTART (2026-05-23 終了時スナップショット)

### 現在の状態 (1 行)
**Stage-1 robust champion = `L5mkn` (`modified_kn n=5 α=0.8`) ppl 3.5356** (N1 比 -77.2%、cross-corpus geomean 5.48 で 1 位)。 ローカル単独最高は **`Lmkn5d2` (modified_kn n=5 α=1.5) ppl 3.4913** だが **kodama-lab corpus で負け** ( pinned-specific overfit と判明)。 **G2 (context-conditional KN) 完走 (2026-05-24)**: kn_ctx 実装 + http://www.kodama-lab.com 取り込みでクロスコーパス検証。 **G4 (MAP-Elites) 完走 (2026-05-23)**: archive 22/100 cell、 silver = `LkE2 (kneser_ney n=5 α=0.9) ppl 3.6439`。

### 進化推移 (Stage-1 absolute champion 6 段階)
```
15.52 (N1 baseline)
 ↓  -27%
11.34 (L4 backoff n=3 α=0.2, gemma2:2b 単発)
 ↓  -12%
 9.96 (Lg4a backoff n=4 α=0.05, gemma2:2b autoloop)
 ↓  -17%
 8.30 (L3d backoff n=3 α=0.08, llama3.2:3b autoloop)
 ↓  -14%
 7.15 (Lg6 backoff n=4 α=0.01, gemma+llama ensemble)
 ↓  -51%
 3.54 (L5mkn modified_kn n=5 α=0.8, ensemble + G1 KN 拡張)  ← 現 champion
```

### 本セッションで作成・変更したファイル
| ファイル | 行/サイズ | 内容 |
|---|---:|---|
| `local-genai/aipl_v4_autoloop.py` | 410 行 | 完全自動世代交代ループ (elitism + patience + ensemble proposer + KN-aware prompt) |
| `local-genai/kn_smoothing.py` | 167 行 | `KneserNeyNGram` + `ModifiedKneserNeyNGram` |
| `local-genai/aipl_v4_evolve.py` | (修正) | evaluate_genome を 4-style dispatch 化、 _validate / PROMPT_TEMPLATE 更新、 name max 4→16 chars |
| `local-genai/ollama_chat.py` | 122 行 | gradio web chat UI (gemma2:2b + llama3.2:3b 切替、 G1 完了状態の system prompt) |
| `aice-evolution-v2/examples/LocalGenAIAutoloopNextEvolution.aice` | 195 行 | 次の進化空間 6 グループの設計仕様 |
| `aice-evolution-v2/examples/LocalGenAIAutoloopNextEvolution.ga.json` | 17.1 KB | GA spec (21 prior_seeds + 8 design axes) |
| `aice-evolution-v2/examples/LocalGenAIAutoloopNextEvolution.aipl` | 22.1 KB | AIPL runtime プログラム (8-axis MAP-Elites + 4 reviewers) |
| `local-genai/aipl_v4_map_elites.py` | 410 行 | **G4 実装**: archive-based MAP-Elites (cell = smoothing × n × alpha_bin, 100 cells)。 N1/N2/N3 + 5 prior winner seed → empty-cell 狙いの LLM prompt → cell-best acceptance |

### lineage JSON (実験記録)
```
local-genai/out/
├── aipl_v4_autoloop_20260523_154048.json     gemma 単独 winner Lg4a ppl 9.96
├── aipl_v4_autoloop_llama32_3b.json          llama 単独 winner L3d ppl 8.30
├── aipl_v4_autoloop_ensemble.json            gemma+llama ensemble winner Lg6 ppl 7.15
├── aipl_v4_autoloop_g1_kn.json               G1 KN-aware winner L5mkn ppl 3.54
└── aipl_v4_map_elites_g4.json                G4 MAP-Elites archive (22/100 cell, silver LkE2 ppl 3.64)  ★ 最新
```

### G2 + cross-corpus 結果 (2026-05-24)

実装:
- `local-genai/kn_smoothing.py` に **`ContextConditionalKN` クラス追加** (style="kn_ctx")。 discount D を context count tier で動的調整 (`ctx_total<=2: 1.3α / 3..10: α / >=11: 0.6α`)
- `aipl_v4_evolve.py` evaluate_genome に kn_ctx dispatch、 `_validate` に kn_ctx 受理、 prompt に G2 family の説明追加
- `aipl_v4_autoloop.py` の prompt に「at least 1 candidate MUST use kn_ctx」明示
- **新 corpus `local-genai/corpus/kodama_lab.txt`** (14030 bytes, UTF-8, sha256=`03a30d32...`) を http://www.kodama-lab.com から構築 (home + books + classroom + seminar/clang + seminar/java + cg + literacy + yas01-05 を結合・タグ抜き)

cross-corpus 評価結果 (pinned 9.5KB vs kodama-lab 14KB):
| Genome | style | n | α | ppl_pinned | ppl_kodama | geomean |
|---|---|---:|---:|---:|---:|---:|
| **L5mkn** | modified_kn | 5 | 0.8 | 3.5356 | **8.4944** | **5.48** ⭐ robust |
| Lmkn5d2 | modified_kn | 5 | 1.5 | **3.4913** | 9.4036 | 5.73 (pinned-overfit) |
| LkE2 | kneser_ney | 5 | 0.9 | 3.6439 | 9.6166 | 5.92 |
| Lctx5b | kn_ctx | 5 | 0.9 | 3.7744 | 10.40 | 6.27 |
| Lg6 | backoff | 4 | 0.01 | 7.1547 | 19.42 | 11.79 |
| N1 | plain | 1 | 1.0 | 18.24 | 92.38 | 41.05 |

知見:
- **Lmkn5d2 は pinned で勝つが kodama で負ける**: α=1.5 で MKN の 3 discount tier が全て D=0.99 に飽和 → 「全 discount 飽和 MKN」効果で pinned に過剰適合
- **L5mkn (α=0.8) が cross-corpus 真王者**: 両コーパスで上位、 generalization 最強
- **kn_ctx (G2 本命) は default tier では MKN を破れず**: tier boundary (sparse<=2, dense>=11) の手動設定が pessimistic、 改善余地大
- **kodama-lab corpus は約 2.5 倍難しい**: UTF-8 マルチバイト (日本語 3-byte) で実効 byte-vocab が膨らむ

保存先:
- G2 autoloop lineage: `local-genai/out/aipl_v4_autoloop_g2_knctx.json`
- cross-corpus 結果: `local-genai/out/aipl_v4_g2_cross_corpus.json`
- kodama-lab corpus: `local-genai/corpus/kodama_lab.txt` (sha256 pinned)

### G4 MAP-Elites 結果 (2026-05-23 後半)
- **Cell 充填**: 8 (seed) → **22 / 100** (.aice 目標 30+ には未達。 patience でなく max-gens=8 で停止、 gen7 で +3 cell なのでもう少し延ばせば 30 行ける見込み)
- **Family coverage**: plain 3 / backoff 7 / **kneser_ney 7** (前 0!) / **modified_kn 5** (前 1!)
- **Top-3 ppl が全部 KN/MKN n=5**: L5mkn 3.5356 > **LkE2 (KN n=5 α=0.9) 3.6439** > Le2 (MKN n=5 α=0.35) 4.1627 — single-discount KN も MKN champion と僅差で competitive と判明
- **明らかな空き cell パターン**: (plain, n=3, *) (plain, n=5, *) (backoff, n=1, *) (KN, n=1, *) — n=1 系と高次 plain は LLM もほぼ触らず

### バックグラウンドプロセス (セッション終了時に running)
| サーバ | PID | ポート | 用途 |
|---|---:|---:|---|
| Ollama daemon | 6507 | 11434 | gemma2:2b + llama3.2:3b ホスティング |
| gradio chat UI | 7368 | 7861 | http://127.0.0.1:7861/ で対話 |

両方とも nohup なのでマシン再起動まで生き続けます。 止めたい場合:
```sh
pkill -f ollama_chat.py
pkill -f "ollama serve"
```

### 起動チェックリスト (新セッション開始時)
```sh
# 1. cd
cd /Users/kodamay/ocaml-app/abclcp-project

# 2. Ollama daemon 確認 (down なら起動)
curl -s http://127.0.0.1:11434/api/tags >/dev/null && echo up || \
  nohup /opt/homebrew/opt/ollama/bin/ollama serve > /tmp/ollama_serve.log 2>&1 &

# 3. モデル確認 (gemma2:2b と llama3.2:3b の 2 個があれば OK)
/opt/homebrew/opt/ollama/bin/ollama list

# 4. champion 再現 (約 10 秒)
local-genai/.venv/bin/python -c "
import sys; sys.path.insert(0, 'local-genai')
from common import load_corpus, split_corpus
from aipl_v4_evolve import evaluate_genome
raw = load_corpus(); train, holdout = split_corpus(raw)
r = evaluate_genome({'name':'L5mkn','style':'modified_kn','n':5,'alpha':0.8}, train, holdout)
print(f'L5mkn ppl = {r[\"holdout_ppl\"]:.4f}  (expected 3.5356)')
"

# 5. autoloop 再走 (約 1 分、 結果は ppl 3.5-3.6 程度)
local-genai/.venv/bin/python local-genai/aipl_v4_autoloop.py \
  --models gemma2:2b,llama3.2:3b --max-gens 8 --children 4 \
  --parents-keep 3 --patience 3 --temperature 0.5

# 6. chat UI 起動 (オプション)
nohup local-genai/.venv/bin/python -u local-genai/ollama_chat.py > /tmp/ollama_chat.log 2>&1 &
open http://127.0.0.1:7861/
```

### 次の進化候補 (.aice recommended_order 続き)
| Group | 内容 | 期待 | 工数 |
|---|---|---|---|
| **G5** | 3-model ensemble (qwen2.5:3b 追加) | -10-15% improvement の可能性 | 30 分 (pull 含む) |
| **G4+** | MAP-Elites 続走 (max-gens 12-16) で 30+ cell 到達 + crossover 導入 | archive 30+/100、 LkE2 を crossover 親に MKN×KN ハイブリッド | 30 分 (引数だけ) |
| **G2** | context-conditional alpha (KN 上に動的 D) | ppl 3.54 → 2.5-3.0 可能性 | 半日 (新 KN 派生実装) |
| **G3** | 小 BPE (256-512 vocab) | ppl やや悪化、 多様性目的 | 半日 |
| **G6** | Stage-2 (CharRNN) autoloop | R1/R2/R3 baseline を 1 gen 以内に超え | 1 日 (実訓練含む) |

✅ **G4 完了** (2026-05-23): `aipl_v4_map_elites.py` 実装、 22/100 cell、 silver LkE2 発見。
✅ **G2 完了** (2026-05-24): `ContextConditionalKN` 実装、 kodama-lab UTF-8 corpus 取り込み、 cross-corpus eval で L5mkn が robust champion と確認。

### G2+ 残課題 (kn_ctx を本当に MKN より強くするには)
- tier boundary を hyperparam 化 (sparse_max, dense_min を LLM 提案対象に)
- D 倍率も hyperparam 化 (sparse_mul, dense_mul)
- modified_kn と kn_ctx を **直交的に組合せ**: count-tier × context-tier の 2D discount matrix → 新 family `kn_ctx_mod`

### Claude 再起動時の起動文 (コピペ用)
```
local-genai/NEXT_SESSION.md 冒頭の「🔄 SESSION RESTART」を読み込んで現状把握して下さい。

要点:
- Stage-1 absolute champion は L5mkn (modified_kn n=5 α=0.8) ppl 3.5356
- gemma2:2b + llama3.2:3b の Ollama ensemble autoloop で達成
- 次の進化候補は G5 (3-model ensemble), G4 (MAP-Elites), G2 (context-conditional α)
- ollama daemon と gradio chat (port 7861) は前セッションから稼働中の可能性

推奨次手と理由を一言で。
```

---

## 2026-05-23 (PM-4): G1 (Kneser-Ney 拡張) — absolute champion ppl 3.54

`.aice` recommended_order の G1 (smoothing family 拡張) を実装、 autoloop の design space を 2 styles → 4 styles に拡張:

### 新規ファイル
- `local-genai/kn_smoothing.py` (167 行) — `KneserNeyNGram` + `ModifiedKneserNeyNGram` (drop-in 互換)
- `aipl_v4_evolve.py:evaluate_genome` を `style ∈ {plain, backoff, kneser_ney, modified_kn}` で dispatch、`_validate` も同期
- prompt template (gen 0 / gen 1+) に KN-family の使い方と典型 alpha 域 (0.5-0.9) を明記、 「少なくとも 1 候補に kneser_ney or modified_kn を入れて」ガイド追加

### autoloop 結果 (gemma+llama ensemble, max-gens=8 patience=3)
| Stage | Winner | ppl | vs N1 |
|---|---|---:|---:|
| (前回 ensemble Laplace) | `Lg6 backoff n=4 α=0.01` | 7.15 | -54% |
| **G1 KN-aware ensemble** | **`L5mkn modified_kn n=5 α=0.8`** (llama 提案) | **3.5356** | **-77.2%** |

- Gen 0 で即 L5mkn 発見、 Gen 1-3 improvement なしで patience early stop
- top 6 全部 ppl < 4.1 (全 KN-family、 旧 backoff/plain は ppl > 17)
- proposer 内訳: gemma2:2b は `Lkn (KN n=4 α=0.7) ppl 4.13` 等を出し、 llama3.2:3b が新 champion を提案

### KN 事前手動計測 (autoloop 起動前)
```
backoff   n=4 α=0.01: 7.1547  ← 前 champion 再現 ✅
kneser_ney n=3 α=0.7: 5.41
kneser_ney n=4 α=0.7: 4.13
modified_kn n=4 α=0.7: 4.11
modified_kn n=5 α=0.7: 3.59  ← autoloop が再発見 (L5knp by gemma)
```

### 再現
```sh
local-genai/.venv/bin/python local-genai/aipl_v4_autoloop.py \
  --models gemma2:2b,llama3.2:3b --max-gens 8 --children 4 \
  --parents-keep 3 --patience 3 --temperature 0.5
```

- lineage: `local-genai/out/aipl_v4_autoloop_g1_kn.json`

### 次の進化 (.aice recommended_order の続き)
- **G5**: 3-model ensemble (gemma+llama+qwen2.5:3b)
- **G4**: MAP-Elites で smoothing × n cell 充填、 未踏 (modified_kn, n=5, α<0.4) 等
- **G2**: context-conditional alpha (KN の上に重ねる)

---

## 2026-05-23 (PM-3): gemma+llama ensemble — absolute champion ppl 7.15

`aipl_v4_autoloop.py` に `--models <m1,m2,...>` の ensemble モードを追加。各 gen で children を model 間に分割、proposed_by を全 candidate に保存。

| Mode | Final ppl | Winner | vs N1 | Elapsed |
|---|---:|---|---:|---:|
| gemma2:2b 単独 | 9.96 | `Lg4a` (gemma) | -35.8% | 44.9s |
| llama3.2:3b 単独 | 8.30 | `L3d` (llama) | -46.5% | 50.6s |
| **gemma+llama ensemble** | **7.15** | **`Lg6 backoff n=4 α=0.01`** (llama 提案) | **-53.9%** | 56.2s |

### Per-model 貢献 (ensemble の最終 population, parents-keep=3 由来の生存 elite)
- llama3.2:3b: top 5 全部 (ppl 7.15, 7.81, 9.96, 11.97, ...)
- gemma2:2b: 2 個のみ (ppl 24.06, 35.21)、トップ層にゼロ

### ensemble が単独 llama を上回った理由 (推察)
- gen 0..1 で gemma の弱い提案 (ppl 60+ 圏) が `seen_genome_keys` を太らせ、llama を「やってない領域」へ押し出した
- 単独 llama は gen 3 で 8.30 に到達後 patience で停止したが、ensemble は gen 3 (7.81) → gen 4 (7.15) と improvement 継続
- 結果として **どちらも単独では到達しなかった `backoff n=4 α=0.01` を発見**

### 再現
```sh
local-genai/.venv/bin/python local-genai/aipl_v4_autoloop.py \
  --models gemma2:2b,llama3.2:3b --max-gens 6 --children 4 --parents-keep 3 --patience 2 --temperature 0.5
```

- lineage: `local-genai/out/aipl_v4_autoloop_ensemble.json`

---

## 2026-05-23 (PM-2): llama3.2:3b で autoloop — absolute champion 更新

同じ args で proposer model を llama3.2:3b に差し替え:

| Model | Gen 0 best | Gen 1 best | Gen 3 best | Final ppl | Winner | vs N1 | Total |
|---|---:|---:|---:|---:|---|---:|---:|
| gemma2:2b | 15.52 (N1) | 13.24 | 9.9577 | 9.9577 | `Lg4a backoff n=4 α=0.05` | -35.8% | 44.9s |
| **llama3.2:3b** | **10.24 (L2a)** | 9.9577 | 8.2990 | **8.2990** | **`L3d backoff n=3 α=0.08`** | **-46.5%** | 50.6s |

- **llama3.2:3b が absolute winner**。winner ppl 8.30 で gemma2:2b 9.96 を **-16.7%**、N1 baseline を **-46.5%**
- llama3.2:3b は **gen 0 で既に baseline 全部超え** (L2a: plain n=2 α=0.01 ppl 10.24)。gemma は gen 3 までかかった
- 速度差 +13% (50.6 vs 44.9s) は許容範囲、品質改善幅と引き換えに完全に妥当
- llama3.2:3b lineage: `local-genai/out/aipl_v4_autoloop_llama32_3b.json`

### 再現コマンド
```sh
ollama pull llama3.2:3b   # 約 2GB、初回のみ
local-genai/.venv/bin/python local-genai/aipl_v4_autoloop.py \
  --model llama3.2:3b --max-gens 6 --children 4 --parents-keep 3 --patience 2 --temperature 0.5
```

### 推奨次手 (autoloop 拡張)
1. **設計空間拡張**: `(style, n, alpha)` の 3 軸に加え、chunk-level interpolation 係数や hybrid (e.g. plain + Lidstone) を追加
2. **複数 LLM ensemble**: gemma2:2b + llama3.2:3b の両方から子を取り、収束加速を試す
3. **Stage-2 (CharRNN) 拡張**: pytorch_cpu 学習コストありなので、design estimator を残しつつ実訓練版 autoloop に置換するか検討

---

## 2026-05-23 (PM): AIPL-v4 完全自動世代交代ループ実装 + 新 champion

### 結果サマリ
- **新ドライバ `local-genai/aipl_v4_autoloop.py` (327 行)** で multi-generation 進化ループを実装
- 構成: Gen 0 = baselines (N1/N2/N3) + LLM 子 4 個 / Gen 1..N = top-K 親 (elitism keep=3) + 親 ppl を表で見せた prompt で LLM 子 4 個。patience=2 で early stop
- **新 champion: `Lg4a` (`backoff n=4 α=0.05`) ppl 9.9577** — N1 (15.52) 比 **-35.8%**、前ベスト L4 (ppl 11.34) 比 **-12%**
- best ppl trajectory: gen 0 (15.52) → gen 1 (13.24, -14.7%) → gen 3 (9.96, -24.8%) → gen 4-5 停滞 → patience early stop
- 全 6 世代 gemma2:2b に 1 回ずつ呼び出し、合計 約 45 秒

### key bug fix
- `aipl_v4_evolve.py` の `_validate` で name `len <= 4` 制限 → `len <= 16` に緩和
- これがないと gemma2:2b の自然な命名 (`Lx3_laplace`, `L7_backoff` 等) で勝ちパターン候補が全 reject されていた
- 旧 max=4 で行った最初の autoloop ラン (`aipl_v4_autoloop_20260523_153925.json`) では gen 2 で `Lx3_laplace`: `backoff n=3 α=0.2` (= 前回 ppl 11.34 champion) が name reject → early stop に追い込まれていた

### 再現コマンド
```sh
# Ollama デーモン
nohup /opt/homebrew/opt/ollama/bin/ollama serve > /tmp/ollama_serve.log 2>&1 &

# 完全自動ループ (約 45 秒)
local-genai/.venv/bin/python local-genai/aipl_v4_autoloop.py \
  --max-gens 6 --children 4 --parents-keep 3 --patience 2 --temperature 0.5

# サニティ (baselines のみ、N1=15.52 が出ればOK)
local-genai/.venv/bin/python local-genai/aipl_v4_autoloop.py --no-llm --max-gens 1
```

- 最新 lineage: `local-genai/out/aipl_v4_autoloop_20260523_154048.json`

### 残課題 (autoloop 由来の新しい論点)
1. **モデル比較**: gemma2:2b 単独。llama3.2:3b / qwen2.5:3b で同じ autoloop を回し、収束速度と最終 ppl を比較
2. **ハイパラ拡張**: 現状 `(style, n, alpha)` の 3 軸のみ。chunk-level interpolation、token vs byte 等の追加軸を design space に入れる
3. **Stage-2 (CharRNN) 拡張**: `evolve.py:evaluate_stage_n` の design estimator と autoloop を統合
4. **rubric 修正**: LLM 提案も lineage に prompt/seed/model を保存しているので reproducibility 満点化したい

---

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
