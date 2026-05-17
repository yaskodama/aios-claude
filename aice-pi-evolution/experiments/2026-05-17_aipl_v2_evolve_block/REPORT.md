# AIPL v2 (1) — `evolve` block 言語拡張の進化計算

**日付:** 2026-05-17
**実験名:** AIPL bootstrap v2, sub-experiment (1) `evolve-block`
**作業ディレクトリ:** `aice-pi-evolution/experiments/2026-05-17_aipl_v2_evolve_block/`
**親系列:** v1 = aice-evolution-v2 (既存 AIPL bootstrap)
**姉妹実験:** [v2 (2) Type Inference (最優先)](../2026-05-17_aipl_v2_type_inference/REPORT.md)

---

## 1. 目的

過去の PsiLang シリーズ (v1〜v4) で観測した最大の構造的問題:

> **同じ進化計算記述が `.aice` (YAML) / `.ga.json` (JSON) / `aipl_codegen.py` (Python) の 3 箇所に分散**しており、PsiLang v3 では「.aice で hard floor 宣言したが .ga.json に届かなかった」事故が起きた。

AIPL v2 (1) はこの分散を解消するため、**AIPL に `evolve { }` first-class 構文を導入する**設計を進化計算で探索する。

## 2. 実験構成

- `AIPL_v2_EvolveBlock.aice` (案 1 YAML)、12 軸、6 reviewer (R1〜R6_RealWorldPrecedent)、hard_floor=R6
- `aipl_evolve_block.schema.json` (12 軸 + 10 coherence rules)
- `AIPL_v2_EvolveBlock.ga.json` (中間 IR)
- `AIPL_v2_EvolveBlock.aipl` (980 行、aipl_codegen v4 で生成)
- 進化計算: MAP-Elites, seed_count=8, generations=30, rng_seed=31415929

## 3. 結果

| 指標 | 値 |
|---|---|
| 完走 | ✓ 38 個体 / 1140 calls / **$0.430** / 51 分 |
| max score | **0.721** |
| mean | 0.229 |
| std | 0.163 |
| hard-floor zeros | 1 (R6 が 0.0 を返した個体 1 つを fitness=0 にクランプ) |
| coherence violations | **0/38** (v4 codegen の rejection sampling が機能) |

### Top 5 個体

| # | id | gen | score | 設計の核 |
|---:|---|---:|---:|---|
| 1 | I25 | 17 | **0.721** | **native_block_curly** + **inline_function** reviewer + **json_record** genome |
| 2 | I28 | 20 | 0.695 | **decorator_style** + inline_function + json_record |
| 3 | I34 | 26 | 0.555 | (#1 と同一 cell) |
| 4 | I19 | 11 | 0.435 | json_literal_in_code + block_decl + csv_string + **breaking_change** |
| 5 | I27 | 19 | 0.385 | yaml_embed_in_code + block_decl + plain_object + **strict_no_change** |

### Top 5 軸分布 (重要な合意)

| 軸 | 支持された値 | 解釈 |
|---|---|---|
| `aice_dialect_compat` | **yaml_v1_only 5/5** | YAML 1 次ソース化、curly-brace 廃止 |
| `lineage_persistence` | **per_generation 5/5** | v3 の checkpoint を言語標準化 |
| `parser_impact` | **new_grammar_productions 4/5** | sugar layer ではなく真の新構文 |
| `reviewer_evaluator_style` | **builtin_evaluate 4/5** | future_fanout を runtime builtin に隠す |
| `reviewer_declaration` | inline_function 3, block_decl 2 | **lambda 形式の reviewer** が優勢 |
| `genome_representation` | **json_record 3/5** | dict-like 表現 (現状の踏襲) |
| `backward_compat_strategy` | opt_in_new_syntax 3 | 既存コードを破壊しない |

## 4. 進化計算が示唆する evolve-block の最適形

Top 1 (I25, score 0.721) の遺伝子を AIPL 構文に書き起こすと:

```aipl
// 設計案: AIPL に追加すべき構文 (top 1 genome から復元)
evolve PiPhase1 {                        // ← native_block_curly
  reviewers: [
    fn(genome, profile) -> Float {        // ← inline_function (lambda)
      let s = now ai_call_with_system(persona, prompt);
      ai_score(s)
    }
  ],
  cell_axes: ["paradigm", "type_system", ...],
  genome: { paradigm: "functional", ... } // ← json_record
} guarantees {
  per_generation_checkpoint,              // ← lineage_persistence
  no_silent_death
}
```

## 5. 実装方針 (top 5 のコンセンサス)

| 改修対象 | 内容 | 推定行数 |
|---|---|---:|
| `aipl_parser.py` | `evolve` キーワード + curly block の grammar production | +200 |
| `aipl_interp.py` | Evaluator を builtin として組み込み | +300 |
| `aipl_codegen.py` | YAML `.aice` を 1 次ソース化、curly `.aice` 廃止 | -200 |
| 既存 .aipl | 無変更で動く (opt-in) | 0 |

合計 **+300 行で実装可能** と推定 (R4 reviewer の予測)。

## 6. 限界と次のステップ

- **#1 と #3 が同一 cell**: top 5 内の多様性は不十分。R6 hard floor は機能 (1 個体 = 0) したが top 5 内では効かず。
- **真の new_grammar 改修は中規模**: parser + interp + codegen の 3 ファイルに渡る。Phase A〜C の段階的ロードマップが妥当。
- **(2) Type Inference と独立**: 別経路で進化計算が走った結果、(2) は型推論アルゴリズムを探索。両者を組合せた合成プラン (REPORT 末尾) が次の研究方向。

## 7. 関連ファイル

| ファイル | 役割 |
|---|---|
| `AIPL_v2_EvolveBlock.aice` | 案 1 YAML 問題定義 |
| `aipl_evolve_block.schema.json` | 12 軸 + 10 coherence rules |
| `AIPL_v2_EvolveBlock.ga.json` | 中間 IR |
| `AIPL_v2_EvolveBlock.aipl` | AIPL 実行プログラム (980 行) |
| `AIPL_v2_EvolveBlock.aipl_lineage.json` | 38 個体の lineage |
| `ai_usage.json` | $0.430 / 1140 calls |
| `AIPL_v2_EvolveBlock.log` | 実行ログ (gen 1〜30 の checkpoint) |

## 8. まとめ

| 項目 | 結果 |
|---|---|
| evolve-block syntax 探索 | ✓ top 1 = native curly block + inline lambda reviewer + json_record genome |
| 進化計算による設計発見 | ✓ aice_dialect / lineage / parser_impact の 3 軸で強い合意 |
| 実装可能性 | ✓ aipl_parser/interp/codegen に +300 行で実装可能 |
| 後方互換 | ✓ opt_in_new_syntax で既存 .aipl はゼロ変更で動く |
| 同時実験 (2) との関係 | 並走 (型推論側で別の合意を発見) |

進化計算は AIPL に追加すべき `evolve { }` 構文の形を**人間の事前設計なしに**抽出した。次の課題は (1) と (2) の合成 = 「evolve block + 型推論」を持つ AIPL v2 を実装し、過去 4 つの .ga.json を 1:1 で書き直すこと。
