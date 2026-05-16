# v3 LangDesign 進化計算 — Negative Result 報告書

**日付:** 2026-05-16 ~ 2026-05-17
**実験名:** `2026-05-16_v3_langdesign`
**作業ディレクトリ:** `aice-pi-evolution/experiments/2026-05-16_v3_langdesign/`
**親実験:** [v2 LangDesign_Expressive](../2026-05-16_v2_langdesign/REPORT.md)
**結論:** **狙い (現実離れの組合せを排除) と逆の結果**になった。**negative result** として記録する。

---

## 1. 目的

v2 top 5 に混入した「実在しない言語の組合せ」 (例: I35 = c_like + refinement 型) を排除し、より**現実先例に近い**遺伝子を進化計算で発見する。具体的には:

1. **6 新規 coherence rule** で `c_like ⇒ ¬refinement`, `haskell_like ⇒ functional` 等を schema レベルで強制
2. **R6_RealWorldPrecedent reviewer (weight 0.10) 追加** で「実在言語に該当するか」を採点
3. **R6 = 0 で hard floor** (最終 fitness=0) と `.aice` で宣言
4. `rng_seed` を 1 違いに変更して初期分散を変える

## 2. 実験経過

### 2.1 1 回目試行 (深夜) — silent hang で失敗

- 22:38 開始、03:00 過ぎ時点で個体 35/38 (92%) に達したが、その後 25 分間 stall → kill
- 原因: OpenAI gpt-4o-mini の SDK が深夜帯に silent hang (試行 #2 で観測した症状の再現)
- `.aipl` に毎世代 `lineage.dump()` checkpoint が**未実装**だったため、35 個体ぶんの評価データが全消失
- 1276 calls / **$0.56 を浪費**

### 2.2 codegen 修正

`aice-evolution-v2/src/aipl_codegen.py` の `Coordinator.run()` template を改修し、while 内で毎世代 `lineage.dump()` を呼ぶように変更。今後の全 evolution run が silent hang 耐性を持つようになった (`[ckpt gen=N]` 出力)。

### 2.3 2 回目試行 (朝) — 完走

- 07:16 開始 → 08:26 完走 (約 70 分)
- 38 個体、1368 calls、**$0.60** (v2 の $0.54 より 11% 増 — R6 prompt 追加分)
- checkpoint 動作確認 (gen 1〜30 まで `[ckpt gen=N] flushed M individuals` 出力)

## 3. 結果

### 3.1 全体スコア

| | v2 | v3 |
|---|---:|---:|
| 個体数 | 21 elite cells | 38 個体 (lineage) |
| max score | **0.700** | **0.670** ↓ |
| mean score | 0.516 | 0.479 ↓ |
| std | 0.103 | 0.090 |

→ R6 + 新 coherence で**スコア全体が低下**。

### 3.2 Top 5 (スコア降順)

| # | v3 | v2 (参考) |
|---:|---|---|
| 1 | I26 (gen 18, axis_resample) **0.670** — term_rewriting · refinement · interval_arithmetic · monadic_bind · haskell_like ⚠️ | I35 0.700 functional · refinement · real_with_precision · pattern_match · c_like ⚠️ |
| 2 | I7 (seed) 0.654 — 同上 ⚠️ | I17 0.675 term_rewriting · static_simple · arbitrary_int+rat · pattern_match · custom_minimal |
| 3 | I21 (gen 13, axis_resample) 0.613 — 同上 ⚠️ | I12 0.646 functional · static_simple · arbitrary_int+rat · pattern_match · ml_like |
| 4 | I2 (seed) 0.603 — oo · static_simple · arbitrary_int+rat · list_comp · ml_like | I37 0.638 declarative_eq · static_simple · arbitrary_int+rat · pattern_match · custom_minimal |
| 5 | I24 (gen 16, axis_resample) 0.584 — 同上 #1 ⚠️ | I15 0.635 hybrid · hindley_milner · dependent_precision · structured_loops · ml_like |

⚠️ = 新規 coherence rule (e.g. `haskell_like ⇒ functional`) に反する組合せ

### 3.3 軸分布 (top 5)

| 軸 | v2 top 5 | v3 top 5 |
|---|---|---|
| paradigm | functional 2 + 4 種類 (分散) | **term_rewriting 4** (集中), oo 1 |
| type_system | static_simple 3, refinement 1, hindley_milner 1 | **refinement 4**, static_simple 1 |
| arithmetic | arbitrary_int+rat 3, real_with_precision 1, dependent_precision 1 | **interval_arithmetic 4**, arbitrary_int+rat 1 |
| control_flow | pattern_match_fold 4, structured_loops 1 | **monadic_bind 4**, list_comprehension 1 |
| syntax_family | ml_like 2, custom_minimal 2, c_like 1 (3-way 同点) | **haskell_like 4**, ml_like 1 |

→ v3 top 5 は **4/5 が単一 cell** に集中。多様性が崩壊。

## 4. 主要な発見 (negative result)

### 4.1 想定 vs 実測

| 項目 | 想定 (v3 改善) | 実測 |
|---|---|---|
| 非現実組合せが top 5 に占める割合 | 0/5 | **4/5** (悪化) |
| max score | 上昇 (実言語近似が報奨) | 0.700 → **0.670 に低下** |
| 多様性 | 向上 | **1 cell に 80% 集中** |

### 4.2 失敗の三層構造

1. **`R6_RealWorldPrecedent` が hard floor として実装されていない**
   - `.aice` で「R6 = 0 → 最終 fitness = 0」と宣言したが、`.ga.json` の `meta_fitness` には weight 0.10 の加重平均としてしか表現できなかった (AIPL ランタイムには clamp 機構が無い)
   - 結果: 違反個体は満点から 10% 引かれるだけで生存

2. **seed が coherence rule を無視**
   - `aipl_codegen.py` の `Generator.seed()` template は schema の各軸からランダム選択するだけで coherence を尊重しない
   - I7 と I2 はどちらも seed (gen 0)。新コヒーレンス導入後も初期人口に違反個体が紛れる
   - mutate / cross は coherence-aware だが、seed が違反個体を撒けば子孫もその cell を共有

3. **MAP-Elites の cell 衝突**
   - I7 → I21 → I24 → I26 はすべて `term_rewriting + refinement + interval_arithmetic + monadic_bind + haskell_like` の cell に分類
   - 同じ cell で elite 競合 → 高スコア順に top 5 を取ると 4/5 が単一 cell から
   - cell 分布が seed の偏りを増幅

## 5. v4 に向けた教訓

進化計算で「現実性 / coherence」を制約するには、**reviewer (目的関数) の設計だけでは不十分**で、以下の 3 点をセットで実装する必要がある:

| 修正対象 | 内容 | 想定工数 |
|---|---|---|
| (a) `aipl_codegen.Generator.seed()` template | coherence rules を rejection sampling で適用 (違反個体は再抽選) | 30 行 |
| (b) `aipl_codegen.Evaluator` template | 特定 reviewer の score=0 で全体 fitness を 0 にクランプ | 20 行 |
| (c) `aipl_codegen.Generator.mutate()` / `cross()` の coherence 適用範囲 | 既に強制している axis_resample / coherent_shift と llm_proposal の整合性確認 | 確認のみ |

v4 でこの 3 点を実装すれば、本実験が示した failure mode を解消できる見込み。

## 6. 副次成果: codegen のチェックポイント機能

本実験 1 回目試行の silent hang を受けて、`aipl_codegen.py` の `Coordinator.run()` template に**毎世代 `lineage.dump()` checkpoint** を組み込んだ。

これで今後の **すべての evolution run** が:
- silent hang / kill 時に N 世代までの lineage を保持
- mock smoke test でも `[ckpt gen=N] flushed M individuals` 出力で進捗が見える
- Cost: 1 fs write per generation (無視できる)

この修正は本実験の **net positive な成果**。

## 7. ファイル一覧

| ファイル | 内容 |
|---|---|
| `LangDesign_Expressive_v3.aice` | 案 1 YAML 問題定義 (R6 + 6 coherence 追加) |
| `lang_design_paradigm_v3.schema.json` | 18 coherence rule (v2 から +6) |
| `LangDesign_Expressive_v3.ga.json` | 中間 IR (R6 reviewer 含む) |
| `LangDesign_Expressive_v3.aipl` | 実行プログラム (codegen 出力、毎世代 dump 入り) |
| `LangDesign_Expressive_v3.aipl_lineage.json` | 38 個体の lineage (本報告書の基礎データ) |
| `LangDesign_Expressive_v3.log` | 実行ログ (`[ckpt gen=N]` 30 件 + `[done]` + `[lineage]`) |
| `ai_usage.json` | OpenAI 課金記録 (1368 calls / $0.60) |
| `out/` | 実行中のチェックポイント (本番完走後は最終 lineage のみ) |
| `REPORT.md` | この文書 |

## 8. 結論

> **進化計算の目的関数 (reviewer) だけで制約を表現するのは限界がある。** ハード制約は genome 生成と評価集計の両段階に実装する必要がある。

PiLang / PhiLang / PsiLang の三世代が示してきたのは「進化計算が示唆する設計原理を抽出する」プロセスだった。v3 はそれに対し、**ナイーブな設計修正は逆効果を生む** という非対称性を実例で示したという意味で、negative result ながら**方法論研究上の価値**がある。

---

## 参考

- [v2: LangDesign_Expressive (positive result)](../2026-05-16_v2_langdesign/REPORT.md) — PsiLang を生んだ実験
- [v1: Pi_Phase1_Robustness](../2026-05-16_robustness_v1/REPORT.md) — PhiLang
- [祖先: PiLang](../../REPORT_JA.md) — 数値計算問題からの言語生成
