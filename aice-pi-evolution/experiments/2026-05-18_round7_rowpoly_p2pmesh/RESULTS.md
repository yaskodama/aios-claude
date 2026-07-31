# Round 7 — CE-16 + DR-17 Variant Selection (2026-05-18)

実行: `cd aice-evolution-v2 && AIPL_AI_PROVIDER=openai AIPL_AI_EVAL_WORKERS=8 python3 -m src.cli ../aice-pi-evolution/experiments/2026-05-18_round7_rowpoly_p2pmesh/AIPL_Round7_RowPolyP2PMesh.aice --ai --abcl`

14 個体 / 8 世代 / 7 cells filled.  Refinement round: 機能名は
round 6 で決定済み (CE-16 row-polymorphic actor interfaces, DR-17
P2P actor mesh), 今回は各 4 variant の中からベストを選ぶ.

## Top 5 elites

| Rank | id | gen | composite | effect_handling | state_repr | paradigm |
|------|----|-----|-----------|-----------------|------------|----------|
| 1    | I0007 | 1 | **0.716** | algebraic_effects | symbol_owned | ParallelOOP |
| 2    | I0006 | 0 | 0.694 | implicit | symbol_owned | FunctionalOOP |
| 3    | I0005 | 0 | 0.631 | algebraic_effects | enum_state | BASIC |
| 4    | I0010 | 4 | 0.607 | implicit | enum_state | Java_OOP |
| 5    | I0011 | 5 | 0.595 | capability | enum_state | Java_OOP |

## Variant ranking (avg across top 5)

### CE-16 type-system variants

| Rank | Variant | Avg | Verdict |
|------|---------|------|---------|
| 🥇   | **V1 Tail-row-variable unify** | **0.530** | Selected — OCaml-style canonical row poly. `TRecord` に tail: row_var 追加、unify 時に差分を fresh tvar に吸収. |
| 2    | V3 Structural object subsumption | 0.477 | 理論的だが大改修 (HM 全体に kind annotation) |
| 3    | V4 Phantom interface witness | 0.473 | 保守的すぎ、CE-13 と表現力ほぼ同じ |
| ❌   | V2 Polymorphic record open marker | 0.423 | Generalize/Instantiate の周辺挙動が微妙 |

### DR-17 distributed variants

| Rank | Variant | Avg | Verdict |
|------|---------|------|---------|
| 🥇   | **W1 Plumtree (eager + lazy push)** | **0.503** | Selected — Erlang / Riak production heritage. spanning tree + gossip overlay. |
| 2    | W2 HyParView (active+passive list) | 0.487 | Plumtree の下層、組合せ候補 |
| 3    | W3 SWIM-only flat mesh | 0.400 | 最小コストだが routing 提供せず |
| ❌   | W4 Kademlia DHT | 0.390 | 重く、AIPL 規模に過剰 |

## 選定: **(CE-16 V1 Tail-row-var, DR-17 W1 Plumtree)**

両軸とも 1 位の variant が選ばれた.見積もり:

- CE-16 V1: Py-I 80-120 LOC + OCaml 150-200 LOC = ~280 LOC
- DR-17 W1: Py-I 350-500 LOC + OCaml 400-600 LOC = ~900 LOC
- **合計: ~1180 LOC** (round 6 で見積もった ≤1800 LOC レンジ内)

## 補助シグナル

- `implementability` = 0.852 — 全 elite で実装可能と判定
- `task::EvolvabilityToProductionStack` = 0.513 — Erlang/Akka peer 級まではあと一歩
- 収束軸: paradigm = ParallelOOP, type_safety = high, state_representation = symbol_owned (top 2 elite) / enum_state (3-5)
- `effect_handling` は依然 multi-modal (algebraic_effects / implicit / capability の混在) — implementation phase で決め打ちすれば良い

## 推奨される round 8 / 実装 phase

CE-16 V1 と DR-17 W1 を Py-I → OCaml 順に実装:

1. **CE-16 V1 (Py-I `aipl_inference.unify`)**
   - `TRecord` を `TRecord of fields * tail` (tail: `TyVar option`) に拡張
   - `unify` の TRecord arm を tail-variable で差分吸収するよう書き換え
   - Generalize/Instantiate で tail を quantify
   - 既存 CE-13 width subtyping コードは row variable で素直に generalize
   - 見積もり 100 LOC + 既存 record arm の置換

2. **CE-16 V1 (OCaml `src/types.ml` + `infer.ml`)**
   - `TRecord` 同形式に拡張
   - unify, prune, instantiate, string_of_ty に tail 対応 (~30 LOC each)
   - 既存 record-aware tests (RecordStructural.aipl) で regression check
   - 見積もり 200 LOC

3. **DR-17 W1 (Plumtree, `aipl_dist.py`)**
   - actor が eager peer (spanning tree neighbor) と lazy peer (gossip overlay) を維持
   - broadcast: digest を全 peer に, full payload は eager のみ
   - missing-payload pull で lazy peer から取得
   - 見積もり 400 LOC

4. **DR-17 W1 (OCaml `aipl_dist.ml`)**
   - 同上を OCaml で. 既存 DR-* 機能 (structured log, env routing) と統合
   - 見積もり 500 LOC

## 出力ファイル

- `aice-evolution-v2/out/AIPL_Round7_RowPolyP2PMesh.report.md`
- `aice-evolution-v2/out/AIPL_Round7_RowPolyP2PMesh.lineage.json`
- `aice-evolution-v2/out/AIPL_Round7_RowPolyP2PMesh.elite_map.json`
- `aice-evolution-v2/out/AIPL_Round7_RowPolyP2PMesh.ranking.json`
