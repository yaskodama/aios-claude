# aice-pi-evolution — NEXT_SESSION ハンドオフ

**最終更新:** 2026-05-16 (Phase-1 を gen 11/40 で中断、性能問題を整理してから再起動する方針)
**前セッションの最後の状態:** OpenAI gpt-4o-mini で Phase-1 を 3 回試行し、3 回目で gen 11/40 まで進んだ時点でユーザが手動中断。23 個体分の lineage と非ゼロスコア (0.16〜0.58, mean 0.32) を保存済。原因はスループット低 (実効並列 1〜2、理論 8 の 1/4〜1/8)。

このファイルだけで前回セッションを再現/継続できることを目標にしている。

---

## 0. 進行中タスク: OpenAI gpt-4o-mini で Phase-1 を real-LLM 実行 (2026-05-16〜)

### 0.0 セッション 2026-05-16 で起きたこと (3回の試行ログ)

| 試行 | 結果 | 教訓 (修正済) |
|---|---|---|
| #1 | 5秒で死亡 (1 call) | `--timeout 2.0` / `--idle-ms 120` の既定値が短すぎ。real LLM 用には不適 |
| #2 | gen 38/40 (1267 calls, $0.44) で silent death | OpenAI SDK の HTTPS request にタイムアウト無 → ハング後プロセス消滅。lineage を 1 回もダンプしていなかった |
| #3 | gen 11/40 (23 個体, $0.20) で **ユーザが手動中断**。理由: スループットが遅すぎる (~23 calls/min, 理論 240+/min) | 並列化が orchestrator 構造上効いていない (§0.4 参照) |

**3 回の試行から確定した修正 (このセッションでコミット):**

1. `aipl_ai.py` の Anthropic/OpenAI クライアント初期化に **per-request timeout (60s) + SDK max_retries (3)** を追加 (`AIPL_AI_REQUEST_TIMEOUT`, `AIPL_AI_SDK_RETRIES` で上書き可)。
2. `aipl_ai.py` の Vertex backend 経路 (`_get_anthropic_client()` + `AIPL_ANTHROPIC_BACKEND=vertex`) を追加 (使っていないが温存、§0.A 参照)。
3. `aipl_ai.py` の `_price_for()` がバージョン付きモデル ID (`claude-haiku-4-5@20251019` 等) も base 名 lookup する。
4. `aipl_ai.py` の `_get_openai_client()` ヘルパに集約。
5. `Pi_Phase1_OpenSearch.aipl` に **毎世代の `lineage.dump()` チェックポイント** (`[ckpt gen=N] flushed M individuals` 行を出す) を追加。silent death 時も保存済み個体だけは残る。

### 0.1 中断時点の状態 (2026-05-16 05:42)

- AI usage: 599 calls, 382k in tokens, 239k out tokens, **$0.20 課金**
- Lineage: `out/Pi_Phase1_OpenSearch.aipl_lineage.json` に **23 個体** (gen 0〜11)
  - スコア: 全 23 個非ゼロ、min=0.16, max=0.58, mean=0.32
  - operators: seed=12, uniform_crossover=3, axis_resample=8
- Python プロセス: 中断済 (kill -TERM)
- Monitor / watcher: 全て停止

### 0.2 セッション再開時に最初に決める分岐

**A) この lineage (23 個体, gen 0–11) で完了とみなして REPORT を更新する**
   - 短期成果が欲しいならこちら。スコア分布を REPORT_JA.md に追記、Phase-2 をこの lineage を seed_from に使って始める。
   - 追加コスト $0、所要時間 5 分。

**B) Phase-1 を最初から再実行し 40 世代完走させる (現状構造)**
   - 推定: ~60 分, ~$0.4。
   - リスクは前回と同じ「実効並列度 1〜2 で遅い」だけ。silent death は §0.0-修正 で潰れている。

**C) Phase-1 のパラメータを縮めて再実行 (推奨、未試行)**
   - `Pi_Phase1_OpenSearch.aipl` の `seed_count = 12` → 8, `generations = 40` → 20 に変更。
   - 推定: ~25 分, ~$0.2。探索深さは半分だが選択圧の有無を確かめる分には十分。
   - 編集箇所: `aice-pi-evolution/examples/Pi_Phase1_OpenSearch.aipl:552-553`。

**D) Phase-1 の真の並列化を実装する (大改修、未試行)**
   - 現状: `Coordinator.run()` の `while gen <= generations { ... now worker.compute_score(...) ... }` が世代を完全直列に回している (§0.4)。
   - 改修案: generation 内の evaluator fan-out を `send` (fire-and-forget) で投げ、後で `gather` する形に書き換え。理論 5x 速。
   - 工数: aipl_codegen.py の `Evaluator` クラスと Coordinator template を書き換え。再生成すると Pi_Phase1_OpenSearch.aipl も更新される。
   - リスク: codegen 全体の影響範囲が大きいので Phase-0/2/Final も再テスト必要。

### 0.3 推奨手順 (再開時)

1. 状態を確認:
   ```bash
   cat out/ai_usage.json
   /usr/bin/python3 -c "
   import json
   d = json.load(open('out/Pi_Phase1_OpenSearch.aipl_lineage.json'))
   print('n=', len(d))
   scores = [x.get('score', 0) for x in d]
   print('min=', min(scores), 'max=', max(scores), 'mean=', sum(scores)/len(scores))
   "
   ```

2. 分岐 A/B/C/D をユーザと確認。

3. C を選んだ場合の編集と起動コマンド:
   ```bash
   # aice-pi-evolution/examples/Pi_Phase1_OpenSearch.aipl
   #   line 552:  var seed_count = 12;    → 8
   #   line 553:  var generations = 40;   → 20

   rm -f out/ai_usage.json out/Pi_Phase1_OpenSearch.aipl_lineage.json out/Pi_Phase1.log
   mkdir -p out
   nohup env \
     AIPL_AI_PROVIDER=openai \
     ABCL_AI_MAX_CONCURRENT=8 \
     AIPL_AI_TOKEN_BUDGET=5000000 \
     AIPL_AI_USAGE_FILE=out/ai_usage.json \
     AIPL_AI_REQUEST_TIMEOUT=60 \
     AIPL_AI_SDK_RETRIES=3 \
     PYTHONUNBUFFERED=1 \
     /usr/bin/python3 src/python-aipl/aipl_main.py \
       aice-pi-evolution/examples/Pi_Phase1_OpenSearch.aipl \
       --timeout 7200 --idle-ms 60000 \
     > out/Pi_Phase1.log 2>&1 &
   disown
   ```

4. 進捗監視:
   ```bash
   tail -F out/Pi_Phase1.log | grep --line-buffered -E "ckpt gen=|seed\] elite|done\] cells|lineage\] wrote"
   ```

### 0.4 スループット問題の根本原因 (2026-05-16 試行 #3 で判明)

実測: 555 calls / 24 min = **23 calls/min ≈ 0.4 calls/sec**。
理論最大 (concurrency=8, latency=1.5s): **4〜8 calls/sec = 240〜480 calls/min**。
**実効並列度は 1〜2** (理論の 5〜10%)。

**主因は `Pi_Phase1_OpenSearch.aipl:587-612` の構造:**
```aipl
while (gen <= generations) do {
  var parent = now elite.sample_random_genome();  // sync
  var child  = now generator.mutate(parent);      // sync, 1 LLM call
  var ccell  = now worker.compute_cell(child, ...);  // sync, 1 LLM call
  var cscore = now worker.compute_score(child, ...); // sync, 25 LLM calls
  send lineage.add(...);
  send elite.propose(...);
  var np = now lineage.dump(...);
  gen = gen + 1;
}
```
- `now` はブロッキング await。世代間の重なりがゼロ。
- 1 世代 ~27 calls × ~2s ÷ 並列度 1〜2 ≈ 30〜60s/gen → 40 世代で 20〜40 分。
- `compute_score` 内部の 5 reviewer × 5 task が真に並列なら 27 calls/gen → 5s/gen で済むはず。実測は ~60s/gen なので reviewer fan-out も大半が直列。

→ **真の高速化には §0.2-D (codegen 改修) が必要**。短期スコープなら §0.2-C (パラメータ縮小) で凌ぐ。

### 0.5 想定コスト (gpt-4o-mini)

| Phase | コール数 | 想定 in | 想定 out | 想定コスト |
|---|---:|---:|---:|---:|
| Phase-0 | 15 | ~30k | ~5k | ~$0.01 |
| Phase-1 (現状 12 seed / 40 gen) | ~1,300 | ~2.5M | ~0.4M | **~$0.6〜$1.2** |
| Phase-1 (縮小 8 seed / 20 gen, 案 C) | ~600 | ~1.2M | ~0.2M | **~$0.3** |
| Phase-2 | ~950 | ~1.8M | ~0.3M | ~$0.5 |
| Final | 2 | ~5k | ~1k | <$0.01 |
| **合計 (現状)** | ~2,267 | ~4.3M | ~0.7M | **~$1.5〜$2** |
| **合計 (案 C)** | ~1,567 | ~3.0M | ~0.5M | **~$0.8〜$1** |

実績 (試行 #3 中断時): 599 calls / 11 世代 → 54 calls/gen (推定より 2x 高い)。reviewer×task の組合せが想定より多いか、retry が含まれている。

### 0.6 詰まる可能性 (再開時のチェックリスト)

- **`AIPL_AI_MODEL` env は無効**: 試行で確認済。`aipl_main.py` は env からモデル名を読まない。`aipl_ai.py:75` の `DEFAULT_OPENAI_MODEL = "gpt-4o-mini"` が効くだけ。別モデルにするときはこの定数を書き換え。
- **`--timeout` / `--idle-ms` の既定値は real LLM では NG**: 試行 #1 で確認 (2秒/120msで死亡)。最低 `--timeout 7200 --idle-ms 60000` を付ける。
- **OpenAI SDK のハング**: 試行 #2 で発生。修正済 (`AIPL_AI_REQUEST_TIMEOUT=60`, `AIPL_AI_SDK_RETRIES=3`)。これらの env を必ず付ける。
- **Rate limit (429)**: 試行中に出てない (tier 1 で RPM=500, TPM=200k に届かない)。`_is_retryable` がバックオフを掛ける。
- **`max_tokens` 既定 4096**: Reviewer 返答は 1-2 行なので過剰。コスト圧縮したいなら `aipl_ai.py:79` の `DEFAULT_MAX_TOKENS` を 512 程度に。今回試行では未調整。
- **silent death**: 試行 #2 で原因不明 (sample で全スレッド cond_wait)。`AIPL_AI_REQUEST_TIMEOUT=60` で再現性は消えたが、長時間 (>1h) 走らせるなら毎世代の checkpoint dump 必須 (試行 #3 で適用済、Pi_Phase1_OpenSearch.aipl:611-614)。
- **Mac の sleep**: 試行 #2 が放置中に死亡した可能性あり。長時間 run の前に Caffeinate を:
  ```bash
  caffeinate -i &  # claude code セッション内で起動した python のスリープ防止
  ```

### 0.A (postponed) Google Vertex AI 経由 — 後日復活用にメモを残す

**postpone した理由 (2026-05-16):** GCP Console での Vertex AI API 有効化と Model Garden の Claude Enable が完了できず、ブラウザ作業で時間を要したため。OPENAI_API_KEY は既に手元にあるので OpenAI に切替えた。再開する場合は以下の §0.A.1〜0.A.7 をそのまま使える (gcloud CLI は 568.0.0 がインストール済になっている)。

#### 0.A.1 経緯と狙い (Vertex 案、postponed)
- mock provider ではスコアが全 0 で MAP-Elites の選択圧がかからない (§6.1)
- 真の選択圧で Phase-1 を回したい → **Anthropic 公式 API は日本のクレカが Stripe 決済を通らない**ため断念
- 代替経路として **Google Vertex AI** を採用 (anthropic SDK は `AnthropicVertex` クライアントを既にサポート、anthropic 0.97.0 で確認済)
- 副次効果: GCP 新規アカウントの **$300 / 90日無料クレジット**で Phase-1 (Opus 4.7 で $28 想定) も実質無料で試せる

#### 0.A.2 現時点の到達点 (Vertex 案、postponed)
| 項目 | 状態 |
|---|---|
| anthropic Python SDK | 0.97.0 インストール済、`AnthropicVertex` import 可 |
| gcloud CLI | **2026-05-16 時点で 568.0.0 インストール済 (auth/project は未設定)** |
| GCP アカウント | あり (Google アカウント `yaskodama@gmail.com`) |
| GCP プロジェクト | **作成済 (詳細はユーザのブラウザ側で確認)** |
| Billing アカウント | **未確認** (Vertex AI API 有効化前に必要な可能性あり) |
| Vertex AI API 有効化 | **未完了** (ユーザのブラウザ作業で停止中) |
| Model Garden で Claude Enable | 未着手 |
| `aipl_ai.py` の Vertex 経路パッチ | **2026-05-16 完了** (`_get_anthropic_client` + `AIPL_ANTHROPIC_BACKEND=vertex`) |

#### 0.A.3 ユーザが次に踏むステップ (ブラウザ作業、postponed)

1. **Vertex AI API を有効化**:
   - `https://console.cloud.google.com/apis/library/aiplatform.googleapis.com` を開く
   - 上部でプロジェクトを確認
   - 青い **ENABLE** ボタンを押す (30秒〜1分)
   - 詰まる主因: Billing アカウント未リンクなら左メニュー → Billing → アカウントリンク

2. **Model Garden で Claude を Enable**:
   - `https://console.cloud.google.com/vertex-ai/model-garden`
   - 検索バーで `Claude` → 使うモデル (推奨: **Claude Haiku 4.5** で疎通テスト→ Opus 4.7 で本実行)
   - 各モデルカードで **Enable** ボタンを押す
   - **対応リージョン**をメモ (Claude は `us-east5` が主流)
   - **正式モデル ID** をメモ (例: `claude-haiku-4-5@<version>`, `claude-opus-4-7@<version>`)

3. **gcloud CLI インストール + 認証** (ターミナルで):
   ```bash
   brew install --cask google-cloud-sdk
   # シェル再起動後
   gcloud init                                # アカウント + プロジェクト紐付け
   gcloud auth application-default login      # ADC (SDK が読む認証)
   ```

4. **動作確認**:
   ```bash
   gcloud config get-value project    # プロジェクト ID
   gcloud auth application-default print-access-token | head -c 20
   ```

#### 0.A.4 セッション再開時に Claude (アシスタント) が踏むステップ (Vertex 案)

1. ユーザに「Vertex AI API 有効化と Model Garden で Claude Enable は済んだか」を確認
2. ユーザに以下を聞き出す:
   - **GCP プロジェクト ID** (例: `aipl-pi-evolution-123456`)
   - **リージョン** (例: `us-east5`)
   - **Claude モデルの正式 ID** (Vertex の Model Garden に表示されているバージョン付き ID)
3. `aipl_ai.py` をパッチして Vertex 経路を追加 (§0.5 参照)
4. 疎通テスト → Phase-1 本実行

#### 0.A.5 `aipl_ai.py` パッチ (2026-05-16 実装済)

**実装済の関数:** `_get_anthropic_client()` (`src/python-aipl/aipl_ai.py:42-71`)。`AIPL_ANTHROPIC_BACKEND=vertex` で `AnthropicVertex(project_id, region)` を返す。`AIPL_VERTEX_PROJECT_ID` / `AIPL_VERTEX_REGION` を読む。`_price_for()` はバージョン付き ID (`claude-haiku-4-5@20251019` 等) も base 名で lookup する。

旧設計メモ (参考のみ):

**目的**: 既存の `ANTHROPIC_API_KEY` 直接経路を壊さず、env で backend を切替可能にする。

**追加する環境変数**:
```bash
export AIPL_AI_PROVIDER=anthropic
export AIPL_ANTHROPIC_BACKEND=vertex       # 'direct' (default) | 'vertex' | 'bedrock'
export AIPL_VERTEX_PROJECT_ID=<gcp-project-id>
export AIPL_VERTEX_REGION=us-east5
export AIPL_AI_MODEL=claude-haiku-4-5@<version>   # Vertex 用バージョン付きID
```

**修正対象ファイル**: `src/python-aipl/aipl_ai.py`

**修正箇所**:
- 現在 `_anthropic_client = anthropic.Anthropic()` が 3 箇所 (lines 617, 712, 766) に重複
- これらを **`_get_anthropic_client()` ヘルパに集約**
- ヘルパ内で `AIPL_ANTHROPIC_BACKEND=vertex` なら `anthropic.AnthropicVertex(project_id=..., region=...)` を返す
- それ以外 (`direct` または未指定) なら従来通り `anthropic.Anthropic()`

**疎通テストコマンド** (パッチ後):
```bash
AIPL_AI_PROVIDER=anthropic \
AIPL_ANTHROPIC_BACKEND=vertex \
AIPL_VERTEX_PROJECT_ID=<project-id> \
AIPL_VERTEX_REGION=us-east5 \
AIPL_AI_MODEL=claude-haiku-4-5@<version> \
/usr/bin/python3 -c "
import sys; sys.path.insert(0, 'src/python-aipl')
from aipl_ai import call_ai
print(call_ai('say ok in one word'))
"
```
→ `ok` 等が返れば疎通成功。

**Phase-1 本実行**:
```bash
mkdir -p out
AIPL_AI_PROVIDER=anthropic \
AIPL_ANTHROPIC_BACKEND=vertex \
AIPL_VERTEX_PROJECT_ID=<project-id> \
AIPL_VERTEX_REGION=us-east5 \
AIPL_AI_MODEL=claude-haiku-4-5@<version> \
AIPL_AI_MAX_CONCURRENT=4 \
AIPL_AI_TOKEN_BUDGET=5000000 \
AIPL_AI_USAGE_FILE=out/ai_usage.json \
/usr/bin/python3 src/python-aipl/aipl_main.py \
  aice-pi-evolution/examples/Pi_Phase1_OpenSearch.aipl
```

#### 0.A.6 想定コスト (Vertex 価格は Anthropic 直と同等)

| Phase | コール数 | Haiku 4.5 | Opus 4.7 |
|---|---:|---:|---:|
| Phase-0 | 15 | ~$0.05 | ~$0.30 |
| Phase-1 | ~1,300 | ~$6 | ~$28 |
| Phase-2 | ~950 | ~$5 | ~$21 |
| Final | 2 | <$0.01 | ~$0.05 |
| **合計** | ~2,267 | **~$11** | **~$50** |

→ **$300 無料クレジット**内に余裕で収まる。最初は Haiku で疎通、本番のみ Opus 推奨。

#### 0.A.7 詰まる可能性のある箇所 (Vertex 案のチェックリスト)

- **Billing アカウント未リンク**: Vertex AI API ENABLE が押せない / グレーアウト → Console の Billing メニューから請求先アカウントをリンク
- **Model Garden で Claude が Enable できない**: リージョン制限の可能性 → `us-east5` を明示選択
- **ADC が読まれない**: `GOOGLE_APPLICATION_CREDENTIALS` が古い値で残っていると優先される → `unset GOOGLE_APPLICATION_CREDENTIALS` で gcloud ADC に戻す
- **モデル ID 不一致**: Vertex は `claude-opus-4-7@20251019` のようなバージョン付き ID が必須。直接 API の `claude-opus-4-7` だと 404 → Model Garden の表示通りにコピー
- **`aipl_ai.py` の `_record_usage`**: `claude-opus-4-7@20251019` のような ID は pricing table (line 138〜) に無いので `(0,0)` 扱いになる。コストトラッキングだけは Anthropic 直の場合と数字がズレることに注意 (実際の課金は GCP 側で正確に計測される)

---

## 1. プロジェクトの場所と中身

```
/Users/kodamay/ocaml-app/abclcp-project/aice-pi-evolution/
├── baseline/{asm,c,basic,forth}/   ← π 10,000 桁の低レベル実装 4 種
├── bench/fitness_fingerprint.md    ← 4 実装の digits/sec, LoC, RAM 表
├── schemas/pi_paradigm.schema.json ← π 計算用に拡張した遺伝子スキーマ (6 軸追加)
├── examples/
│   ├── Pi_Phase0_LowLevelBaseline.{aice,ga.json,aipl}
│   ├── Pi_Phase1_OpenSearch.{aice,ga.json,aipl}
│   ├── Pi_Phase2_BignumRefinement.{aice,ga.json,aipl}
│   ├── Pi_PiLang_Final.{aice,ga.json,aipl}
│   └── pi_10k.pl                  ← 進化計算が生んだ PiLang 3 行サンプル
├── README.md                       ← プロジェクト全体の俯瞰
├── REPORT_JA.md                    ← 詳細実験報告 (本セッションの成果)
└── NEXT_SESSION.md                 ← この文書
```

実行成果物 (再生成可) :
```
/Users/kodamay/ocaml-app/abclcp-project/out/Pi_*.aipl_lineage.json   ← 4 個体台帳
```

## 2. 基盤フレームワーク (改変済)

| パス | 役割 | 改変の有無 |
|---|---|---|
| `aice-evolution-v2/src/aice_parser.py` | `.aice` → `.ga.json` lowerer | 未改変 |
| `aice-evolution-v2/src/aipl_codegen.py` | `.ga.json` → `.aipl` codegen | **改変済** (arity 修正, §5 参照) |
| `aice-evolution-v2/src/cli.py` | CLI エントリ | 未改変 |
| `aice-evolution-v2/schemas/programming_paradigm.schema.json` | 親スキーマ | 未改変 |
| `src/python-aipl/aipl_main.py` | AIPL ランタイム | 未改変 |

## 3. 再起動チェックリスト

```bash
cd /Users/kodamay/ocaml-app/abclcp-project

# (1) ファイル一式が揃っているか
ls aice-pi-evolution/examples/Pi_*.{aice,ga.json,aipl} | wc -l   # 期待値 12

# (2) .aice → .ga.json は再現できるか (隣に上書き出力)
for f in Pi_Phase0_LowLevelBaseline Pi_Phase1_OpenSearch \
         Pi_Phase2_BignumRefinement Pi_PiLang_Final; do
  python3 -m aice-evolution-v2.src.cli \
    aice-pi-evolution/examples/${f}.aice --no-run \
    -o aice-pi-evolution/examples
done

# (3) .ga.json → .aipl は再現できるか
python3 - <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, "aice-evolution-v2")
from src.aipl_codegen import generate_program
base = Path("aice-pi-evolution")
schema = json.loads((base / "schemas/pi_paradigm.schema.json").read_text())
for stem in ("Pi_Phase0_LowLevelBaseline","Pi_Phase1_OpenSearch",
             "Pi_Phase2_BignumRefinement","Pi_PiLang_Final"):
    spec = json.loads((base / "examples" / f"{stem}.ga.json").read_text())
    src = generate_program(spec, schema).replace(f"{stem}.aipl", f"{stem}.aipl")
    (base / "examples" / f"{stem}.aipl").write_text(src, encoding="utf-8")
    print(stem, "ok", len(spec['evaluation']['reviewers']), "reviewers")
PY

# (4) .aipl が AIPL ランタイムで完走するか
mkdir -p out
for f in Pi_Phase0_LowLevelBaseline Pi_Phase1_OpenSearch \
         Pi_Phase2_BignumRefinement Pi_PiLang_Final; do
  AIPL_AI_PROVIDER=mock /usr/bin/python3 src/python-aipl/aipl_main.py \
    aice-pi-evolution/examples/${f}.aipl 2>&1 \
    | grep -E "\[arity\]|seed_count|cells filled|\[lineage\] wrote"
done
# 期待: [arity] 警告は 0 件
```

期待結果 (前回実測):

| Phase | reviewers | seed | gens | cells | individuals |
|---|---:|---:|---:|---:|---:|
| Phase-0 | 3 | 5  | 0  | 5  | 5  |
| Phase-1 | 5 | 12 | 40 | 34 | 52 |
| Phase-2 | 5 | 8  | 30 | 16 | 38 |
| Final   | 2 | 1  | 0  | 1  | 1  |

## 4. 前セッションで採用した重要な設計判断

| 項目 | 決定 | 理由 |
|---|---|---|
| 言語ファイル拡張子 | `.aipl` (`.aipl` ではなく) | ユーザ明示指定。AIPL = ABCL は本プロジェクトでは同義だが、ユーザは `.aipl` を採用 |
| Phase-0 の `generations` | 0 | fingerprint だけ取って Phase-1 へ橋渡しする設計。種を進化させない |
| Final の `algorithm` | `frozen` | 言語仕様の凍結ファイルとして使う。MAP-Elites は走らせない |
| Phase-1 `open_axes` | `true` | LLM 変異が 3 新軸 (`proof_obligation`, `guard_digits`, `simd_lanes`) を発芽させる余地を残す |
| Phase-2 `open_axes` | `false` | もう新軸は増やさない収束フェーズ |
| baseline 実装の完成度 | C は完全、asm は内ループのみ、BASIC は完全、Forth は emit 省略 | reference として動く最小コードに留めた。fitness_fingerprint.md の数値は Apple M2 概算値 |

## 5. `aipl_codegen.py` の Evaluator arity 修正 (前セッションのパッチ)

**症状:** reviewer 数 ≠ 3 のときに AIPL ランタイムが `[arity] eval_actor.init: expected 4, got N` を出していた。

**原因:** `Evaluator` クラスが `init(rev1, rev2, rev3, n)` の 4 引数固定で生成されていた。bootstrap は `new Evaluator(rev1, ..., revN, count)` を出すため、N≠3 で arity 不一致。

**修正:** `n_reviewers` の値に応じて `class Evaluator` 全体を codegen するように変更。`r1..rN` の field、`init(rev1..revN)` の参 N 引数、`score_for_task` 内の future-fanout を可変長で展開。N=0 専用の縮退クラスも用意。Bootstrap 側は `, {reviewer_count}` を外した。

**影響範囲:** `aice-evolution-v2/src/aipl_codegen.py` のみ。`.aice` / `.ga.json` / スキーマには触れていない。修正後、3 / 5 / 5 / 2 reviewer のいずれでも警告ゼロで完走することを確認済。

該当箇所 (修正後の構造): `aipl_codegen.py` line 88 付近の `if n_reviewers == 0: ... else: ... evaluator_class_block = ...` ブロックと、template の `{evaluator_class_block}` プレースホルダ、bootstrap の `var eval_actor = new Evaluator({reviewer_init_args});`。

## 6. 既知の限界 (次セッションが踏みうる地雷)

### 6.1 mock provider はスコアが全部 0

`AIPL_AI_PROVIDER=mock` だと reviewer は決定論的に 0.0 を返し、MAP-Elites の elite 圧力が掛からない。lineage の `score` 列は全 0。真の選択圧で再実行したいなら:

```bash
AIPL_AI_PROVIDER=anthropic /usr/bin/python3 src/python-aipl/aipl_main.py \
  aice-pi-evolution/examples/Pi_Phase1_OpenSearch.aipl
```

(課金が走るので注意 — Phase-1 は 52 個体 × 5 reviewer × 5 task ≒ 1300 LLM コール規模)

### 6.2 `.aice` 拡張ブロックが `.ga.json` に届かない

現行 `aice_parser.lower()` は標準 IR フィールド (`name`, `task`, `schema_ref`, `search`, `operators`, `evaluation`, `meta_fitness`, `ranking`) のみ抽出する。以下のブロックは `.aice` には書けるが下流に伝わらない:

- `seed_from { ... }` (Phase-1/2 で「前 phase の elite 引き継ぎ」を表現)
- `pin_axes { ... }` (Phase-2 で「収束軸を固定」を表現)
- `operators_override { ... }` (各 phase で mutation 重みを書き換え)
- `open_axes_inherited { ... }` (LLM 発芽した新軸を継承)
- `frozen_genome { ... }`, `pi_lang_syntax { ... }`, `backend { ... }`, `evolution_trace { ... }` (Final で言語仕様を埋め込み)
- `handoff { ... }` (全 phase で次 phase への申し送り)

→ これらを真に効かせるには `aice_parser.py` の lowerer を `spec["extensions"]` 経由で拡張ブロックを保持する形に直し、`map_elites.py` と `aipl_codegen.py` 双方で参照する必要がある。**次セッションで触れる場合の最有力候補。**

### 6.3 Phase-2 が paradigm を pin できなかった件

§6.2 が直接の原因。Phase-2 の `pin_axes { paradigm = "Array_DSL"; ... }` は `.ga.json` で消滅したため、ランタイムでは自由軸扱いとなり結果として `paradigm = C_with_bignum_lib:18` などに揺り戻した。

### 6.4 `aipl_codegen.py` の reviewer_count 配下にもう一発バグ

Final の `[arity]` は消えたが、bootstrap の `new Evaluator(...)` 呼び出しのインデント揺らぎなど細部は未確認。新規 `.aice` を作って reviewer 数を 0 にしたケースのみ手動確認すべき。

## 7. 次セッションで取り組む候補 (優先順)

1. **`aice_parser` lowerer 拡張** — `pin_axes` / `seed_from` / `operators_override` を `spec["extensions"]` に保存。Phase-2 が paradigm を真に pin できるようにする (§6.2-3)。
2. **real-LLM での Phase-1 リラン** — `AIPL_AI_PROVIDER=anthropic` で 1 回流してスコアありの lineage を取り、Phase-2 の seed_from が意味を持つ状態にする (§6.1)。
3. **baseline の Forth 実装を完成** — 現状 INNER ワードは emit 省略。GForth で 10k 桁を C 実装と diff 一致させる。
4. **PiLang コンパイラのスケルトン** — `Pi_PiLang_Final.aice` の backend ブロックに従って、`pi_10k.pl` の 3 行を LLVM IR まで降ろせる最小フロントエンドを書く。

## 8. 関連メモリエントリ (このセッションで保存済)

メモリディレクトリ: `/Users/kodamay/.claude/projects/-Users-kodamay-ocaml-app-abclcp-project/memory/`

- `project_aice_pi_evolution.md` — このプロジェクトの存在と狙い
- `reference_aice_pipeline.md` — `.aice → .ga.json → .aipl` パイプラインがどこにあるか
- `feedback_aipl_extension.md` — `.aipl` 拡張子を使うユーザ指定

新セッション開始時にこれらを参照すれば、本ハンドオフ文書と整合する状態に戻れる。

---

**この文書は単体で完結している。** 上から順に読めば、前セッションのどこで止まったか、何を試せばいいか、踏むべきでない地雷がどこにあるかが分かる。
