# Round 6 — Next-Next-Gen Feature Discovery Results (2026-05-18)

実行: `cd aice-evolution-v2 && AIPL_AI_PROVIDER=openai AIPL_AI_EVAL_WORKERS=8 python3 -m src.cli ../aice-pi-evolution/experiments/2026-05-18_round6_nextnextgen/AIPL_Round6_NextNextGen.aice --ai --abcl`

10 個体 / 6 世代 / 3 cells filled. Top 3 elites がすべて
`concurrency_model=structured` + `type_safety=high` + `paradigm=ParallelOOP` に収束し、
`effect_handling` 軸のみ multi-modal (monadic / algebraic_effects / implicit).

## Top 3 elites

| Rank | id | gen | composite | effect_handling | ownership_model |
|------|----|-----|-----------|-----------------|-----------------|
| 1    | I0005 | 1 | **0.795** | monadic | gc |
| 2    | I0010 | 6 | 0.784 | algebraic_effects | gc |
| 3    | I0009 | 5 | 0.758 | implicit | gc |

## 8 task の avg score (top 3 elites を平均)

| Task | Avg | Verdict |
|------|------|---------|
| **task::P2PMeshDR17**      | **0.714** | 🥇 分散軸トップ |
| task::RowPolyActorCE16     | 0.686 | 🥇 型軸トップ |
| task::GradualRegionCE17    | 0.667 | |
| task::DependentIndexCE15   | 0.662 | |
| task::ExactlyOnceDR15      | 0.662 | |
| task::SessionTypesCE14     | 0.643 | |
| task::LiveMigrationDR16    | 0.624 | |
| task::BFTQuorumDR14        | **0.590** | ⚠️ 分散軸最下位 |

## 推奨 (round 7 への引継ぎ)

- **型軸**: CE-16 Row-polymorphic actor interfaces を採用
  - CE-13 record subtyping の上位拡張なので技術的距離が小さい
  - Py-I `aipl_inference.unify` の record arm をさらに開かれた行に
  - 見積もり: Py-I 250-400 LOC、OCaml 300-500 LOC
- **分散軸**: DR-17 P2P actor mesh を採用
  - 既存 star topology を gossip ベースに置換
  - `aipl_dist.py` に Plumtree-style routing + per-actor anti-entropy
  - 見積もり: 600-1100 LOC、両 runtime
- **棄却**: CE-14 session types (複雑度高い割に impl-cost 高い)、
  CE-15 dependent index (Z3 を unify に組み込むのは別 round)、
  DR-14 BFT quorum (PBFT のシグネチャ層が C/JS 移植困難)

## 評価次元の感度

- `coherence`: 1.000 (max) — schema 整合性は破られず
- `implementability`: 0.910 — 全体的に実装可能と判定
- `task::ImplCost`: 0.719 — 1500-2500 LOC レンジが現実的
- `task::TwoRuntimeFloor`: 0.614 — Py-I + OCaml 同時実装は中程度の負担

## 次の round 7 タスク

`aice-pi-evolution/experiments/2026-05-NN_round7_rowpoly_p2pmesh/` を作って:

1. `.aice` を書く: CE-16 row-poly の grammar 拡張 + DR-17 P2P routing protocol の 3-4 variant を seed に
2. 16 cell を埋め直して具体的 design を選定
3. Py-I → OCaml 順で実装、JS-O/JS-B/JS-N/C は後続

## 出力ファイル

- `aice-evolution-v2/out/AIPL_Round6_NextNextGen.report.md`
- `aice-evolution-v2/out/AIPL_Round6_NextNextGen.lineage.json`
- `aice-evolution-v2/out/AIPL_Round6_NextNextGen.elite_map.json`
- `aice-evolution-v2/out/AIPL_Round6_NextNextGen.ranking.json`
