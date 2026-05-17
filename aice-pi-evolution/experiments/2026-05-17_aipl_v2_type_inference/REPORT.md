# AIPL v2 (2) — Python AIPL 型推論強化の進化計算 (最優先)

**日付:** 2026-05-17
**実験名:** AIPL bootstrap v2, sub-experiment (2) `type_inference` — **最優先**
**作業ディレクトリ:** `aice-pi-evolution/experiments/2026-05-17_aipl_v2_type_inference/`
**親系列:** v1 = aice-evolution-v2 (既存 AIPL bootstrap)
**姉妹実験:** [v2 (1) EvolveBlock](../2026-05-17_aipl_v2_evolve_block/REPORT.md)
**v2 (3) 分散ランタイム:** retarded (sibling 実験設計済、本ファイル末尾参照)

---

## 1. 目的

ユーザ明示優先順位: **「AIPL の進化は Python 版 (型推論あり) をまず進化させて下さい。型推論は一番重要です」**

現状の `src/python-aipl/aipl_typeck.py` (877 行) は基本的な型検査のみ (`_compatible`, `_parse_signature`, `_typevars_in`)。AIPL v2 (2) は**型推論を強化する設計**を進化計算で発見する。具体的目標:

1. 大半の式が**注釈なしで型推論される** (gradual typing)
2. PsiLang2 chudnovsky.psi の Int/Rat/Real が**自動推論される**
3. 既存 AIPL プログラム (4 つの Pi_Phase\*.aipl + chudnovsky.psi 各種) が**無変更で型検査を通る**
4. `aipl_typeck.py` への拡張が **+2500 LOC 以内**

## 2. 実験構成

- `AIPL_v2_TypeInference.aice` (案 1 YAML)、12 軸、6 reviewer、hard_floor=R6_RealWorldPrecedent
- `aipl_type_inference.schema.json` (12 軸 + **12 coherence rules**)
- `AIPL_v2_TypeInference.ga.json` (中間 IR)
- `AIPL_v2_TypeInference.aipl` (1046 行、aipl_codegen v4 生成)
- MAP-Elites, seed_count=8, generations=30, rng_seed=31415931

## 3. 結果

| 指標 | v2 (2) Type Inference | v2 (1) EvolveBlock (参考) |
|---|---:|---:|
| 完走 | ✓ 38 個体 / 1140 calls / **$0.478** / 38 分 | 38 個体 / $0.430 / 51 分 |
| max score | 0.650 | 0.721 |
| **mean score** | **0.406** | 0.229 (+77% 改善) |
| std | 0.141 | 0.163 |
| **hard-floor zeros** | **0** | 1 |
| coherence violations | 0/38 | 0/38 |

→ (2) は mean が大幅高 = **top 5 全員が高水準の realistic 設計**。R6 hard floor が機能して fitness=0 個体ゼロ。

### Top 5 個体

| # | id | gen | score | 設計の核 |
|---:|---|---:|---:|---|
| 1 | I5 (seed) | 0 | **0.650** | **constraint_based_global** · **bidirectional_w_refinement** · **gradual** · optional_strict · external_zarith_solver |
| 2 | I18 | 10 | 0.621 | **bidirectional** · static_simple · structural · mandatory_for_public · extend_inline |
| 3 | I19 | 11 | 0.620 | bidirectional · **hindley_milner** · nominal · optional_with_fallback_dyn · rewrite_full |
| 4 | I11 | 3 | 0.616 | constraint_based_global · **dynamic_only** · structural · optional_strict · extend_inline |
| 5 | I7 (seed) | 0 | 0.615 | bidirectional · hindley_milner · **row_polymorphism** · optional_with_fallback_dyn · rewrite_full |

### Top 5 軸分布

| 軸 | 支持された値 | 解釈 |
|---|---|---|
| `inference_algorithm` | **bidirectional 3 + constraint_based_global 2** | 「双方向局所推論」 (Liquid Haskell / F\*) と「全プログラム制約解決」 (Hindley-Damas-Milner) の二派 |
| `inference_scope` | **incremental_per_method 4/5** | **actor method を推論単位とする** (AIPL の特徴を最大活用) |
| `default_inference_target` | **principal_type_from_use 3/5** | 推論失敗時は「使われ方から最も特殊な型」を採用 |
| `error_message_style` | **ocaml_style_with_path 3/5** | 「型エラー: パス + 期待型 + 実際型」 |
| `annotation_requirement` | optional_with_fallback_dyn 2 + optional_strict 2 | **gradual typing の中道** |
| `type_system_strength` | HM 2, dynamic 1, static_simple 1, refinement 1 | 強い合意なし (実装コストとのトレードオフ) |
| `subtyping` | structural 2 (他バラけ) | **構造的部分型** (= mypy/TypeScript 風) が優勢 |
| `implementation_strategy` | extend_inline 2, rewrite_full 2 | **拡張派と書き直し派が拮抗** |

## 4. 進化計算が示唆する型推論設計

Top 1 (I5, score 0.650) は最もアグレッシブな設計:

```
inference_algorithm    = constraint_based_global
type_system_strength   = bidirectional_w_refinement
subtyping              = gradual
implementation         = external_zarith_solver
```

→ **Liquid Haskell / F\* / Coq 系**の精密な型システム。Z3/Zarith SMT 連携で `Int where k >= 0` のような refinement 条件まで自動検証する設計。

実装コスト reviewer R4 はこれを 0.3 と低く評価 (≤ 2000 行) — ハイリスク・ハイリターン。

Top 2-5 はより穏当な選択:
- bidirectional + HM/structural (mypy/Pyright スタイル)
- extend_aipl_typeck_inline (既存 877 行に追加)
- gradual + optional annotation (既存コード保護)

## 5. 推奨実装プラン (Top 2-5 の中央値)

Top 2 (I18, score 0.621) の設計を AIPL に組み込む手順:

```
Phase A: aipl_typeck.py に bidirectional 推論を追加  (+500-1000 行)
  - check(expr, expected_type) と synthesize(expr) の対関数を実装
  - actor method ごとに incremental_per_method スコープで推論
  - structural subtyping (record/dict 互換)
  - mandatory_for_public — public 関数の型注釈は要、内部は推論

Phase B: error_message を OCaml-style に改良  (+200-400 行)
  - 型エラー: ファイル名:行番号 + 期待型 + 実際型 + 候補修正

Phase C (将来): constraint_based_global へ拡張  (+1500 行)
  - whole-program inference for cross-module
  - row_polymorphism for record types
```

合計 **Phase A〜B で +1200 行程度**で実装可能 (R4 reviewer の中央値予測)。

## 6. (1) との比較分析

| 観点 | v2 (1) EvolveBlock | v2 (2) Type Inference |
|---|---|---|
| 探索対象 | 言語**構文**の追加 | 型**推論アルゴリズム** |
| 主に変更する場所 | `aipl_parser.py` + `aipl_codegen.py` | `aipl_typeck.py` |
| Top 1 設計 | curly block + lambda reviewer + json genome | constraint-global + bidirectional refinement + gradual |
| 現実先例 (R6) | DEAP / nevergrad / pyribs | mypy / Pyre / Pyright / OCaml / HM |
| 実装複雑度 | +300 行 (sugar layer + 1 grammar production) | +1200 行 (bidirectional + structural) |
| 既存コード影響 | opt-in (無変更で動く) | gradual (注釈なしで通る) |
| **mean score (= top の安定度)** | 0.229 | **0.406** |

両者を組合せた合成 AIPL v2:

```aipl
// (1) の evolve block + (2) の bidirectional 型推論
evolve PiPhase1 -> Lineage {              // 戻り値型注釈 (optional)
  reviewers: [
    fn(genome: Genome, profile: Profile) -> Float {   // 引数注釈は public 関数なので必須
      let s = now ai_call_with_system(persona, prompt);   // s: String が推論
      ai_score(s)                                       // : Float が推論
    }
  ],
  // cell_axes, genome は型推論で推定 (json_record リテラル)
}
```

## 7. 限界と次のステップ

- **Top 1 と Top 2-5 で実装方針が乖離**: SMT solver (Phase C) vs incremental_per_method (Phase A) — 段階的に Phase A → Phase C に向かう道筋を取れば両立可能。
- **(2) と (1) の融合実装は未着手**: 別 PR で組み合わせるべき。
- **AIPL v2 (3) 分散ランタイム** は本サブ実験では設計のみ (`AIPL_v2_Distributed.aice.original_draft` 残置)。型推論実装が落ち着いたら再開予定。

## 8. 関連ファイル

| ファイル | 役割 |
|---|---|
| `AIPL_v2_TypeInference.aice` | 案 1 YAML 問題定義 |
| `aipl_type_inference.schema.json` | 12 軸 + 12 coherence rules |
| `AIPL_v2_TypeInference.ga.json` | 中間 IR |
| `AIPL_v2_TypeInference.aipl` | AIPL 実行プログラム (1046 行) |
| `AIPL_v2_TypeInference.aipl_lineage.json` | 38 個体の lineage |
| `ai_usage.json` | $0.478 / 1140 calls |
| `AIPL_v2_TypeInference.log` | 実行ログ (gen 1〜30 の checkpoint) |
| `AIPL_v2_Distributed.aice.original_draft` | 分散ランタイム実験 (v2 (3) 用、設計のみ) |

## 9. まとめ

| 項目 | 結果 |
|---|---|
| 型推論アルゴリズム探索 | ✓ top 1 = constraint-global + bidirectional refinement + gradual + SMT solver |
| **実装上の推奨** | Top 2 (bidirectional + structural + extend_inline + mandatory_for_public) — リスクが低い |
| 推論単位 | actor method 単位 (incremental_per_method) で **AIPL の特徴を最大活用** |
| エラーメッセージ | **OCaml-style** (path + expected/actual) |
| 既存コード影響 | gradual typing で注釈なしでも通る |
| 実装規模 | Phase A〜B で **+1200 行** で実用化可能 |
| (1) との関係 | 補完的 (構文 ↔ 推論)、合成 AIPL v2 として組合せ可能 |

ユーザ明示の最優先課題「型推論」に対して、**mypy/Pyright/OCaml 流の bidirectional + gradual** という現実先例に立脚した設計が浮上。これを **`aipl_typeck.py` に直接 extend** することで AIPL の型推論を一段引き上げる道筋が示された。
