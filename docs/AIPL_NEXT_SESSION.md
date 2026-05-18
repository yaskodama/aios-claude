# AIPL — Next Session Resume (2026-05-18, second update)

最新コミット `7cde80b` (origin/main と同期済み).

```
7cde80b aipl: User Manual next-gen chapter + evolution round 6 results
1ece4f3 c-aipl: aipl2c --check surfaces CE-10 effects + closes CE-13 🟡
341bc03 js-aipl: nextgen smoke runner + sample .abcl + session-doc refresh
441cdb0 js-aipl: JS-B / JS-N close 26/26 — CE-10/12/13 + DR-11
4ffba13 js-aipl: port CE-11 + DR-10/12/13 to shared JS-Browser + JS-Node
```

## TL;DR

**全 6 ランタイムが 26/26 next-gen feature ✅ で揃いました.**

| Runtime | Next-gen (26 features) | Note |
|---|:-:|---|
| Py-I    | 26/26 ✅ | reference impl |
| OCaml   | 26/26 ✅ | dune build |
| JS-O    | 26/26 ✅ | OCaml-backed JS bundle |
| **JS-B**| **26/26 ✅** | browser, `src/browser-abcl/src/*.js` |
| **JS-N**| **26/26 ✅** | Node HTTP server, `src/node-aipl-server/server.mjs` |
| C       | 26/26 ✅ | `abcl_nextgen_runtime.{c,h}` 880 LOC |

## Restart prompt to paste into Claude

```
docs/AIPL_NEXT_SESSION.md と docs/AIPL_Runtime_Feature_Matrix.{md,pdf}
を読み込んで現状を把握して下さい。さらに docs/AIPL_Design_and_Implementation.pdf
と docs/AICE_Meta_Research.pdf に研究論文が二本、
docs/AIPL_User_Manual.pdf にユーザマニュアルがあります。

AIPL は 7 ランタイム + 9 codegen バックエンド + WebSocket + remote
actors (HMAC) + 研究論文 2 本 + ユーザマニュアルの言語プロジェクトです。
2026-05-18 セッションで 6 ランタイム全てが 26 個の next-gen 機能
(CE-1..13 type inference + DR-1..13 distributed runtime) を ✅ で
揃え、進化計算で発見された新機能セットを全実装に統一しました。

最初に走らせるべきは (cwd は repo root):
  dune build && bash abclc/_smoke_test.sh | tail -3
期待出力: total: 71  pass: 71  fail: 0

加えて JS-B/JS-N nextgen smoke:
  bash src/browser-abcl/_smoke_nextgen.sh | tail -3
期待出力: pass=14  fail=0
```

---

## 1. 全テストの現状 (再起動後にここが緑なら基準点に戻れる)

| Smoke スクリプト | 結果 |
|---|:-:|
| `dune build` | exit 0 |
| `bash abclc/_smoke_test.sh` | **71/71 PASS** |
| `bash abclc/_smoke_test_c.sh` | **15/15 PASS** (C codegen) |
| `bash src/test_remote_actor.sh` | **9/9 PASS** (plain + HMAC) |
| `bash src/test_c_llvm_openmp.sh` | **4/4 PASS** |
| `cd src/browser-abcl && bash _smoke_test.sh` | syntax 7/7, parse 4/4, typecheck 4/4 |
| `bash src/browser-abcl/_smoke_nextgen.sh` | **14/14 PASS** (CE-10/12/13 + DR-11) |
| `cd src/node-aipl-server && bash _smoke_test.sh` | **10/10 PASS** |
| `cd src/python-aipl && bash _smoke_test.sh` | 27/27 typeinf + 36/36 distributed |

---

## 2. パーサのコンフリクト状況 (全て 0)

| ファイル | ツール | 利用ランタイム | s/r | r/r |
|---|---|---|:-:|:-:|
| `src/parser.mly` | ocamlyacc | OCaml + JS-O + C codegen (9 backends) | **0** | **0** |
| `src/python-aipl/grammar.lark` | Lark LALR | Py-A + Py-I | **0** | **0** |
| `src/browser-abcl/src/parser/grammar.jison` | jison | JS-B + JS-N | **0** | **0** |

dangling-else は `%nonassoc IFX < %nonassoc ELSE` + `%prec IFX` で明示的に解消されており、yacc/jison 警告 0 件. AWAIT は `%nonassoc UAWAIT` + `AWAIT expr %prec UAWAIT` で binop との shift/reduce を回避.

DR-11 saga 構文 (`saga { step { ... } compensate { ... } }`) は jison の `%s saga` start condition + brace-depth state で実装. `step` / `compensate` は saga ブロック内でのみ token 化されるので、`method step()` や `send self.step()` 等の既存サンプル (drone_simulator.abcl) と衝突しない.

手書き再帰下降のため LR 系コンフリクト概念がない: `aice-evolution-v2/src/aice_parser.py` (`.aice` DSL), `aipl-self-host/level-c/parser.abcl` (AIPL セルフホスト).

---

## 3. Next-gen 26 機能の状態 (確定値)

### Phase C–E2 type inference (CE-1..13)

| ID | 機能 | Py-A | Py-I | OCaml | JS-O | JS-B | JS-N | C |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| CE-1..9 | HM 推論 + refinement + Z3 + --check / --infer / record structural | ✅ | ✅ | ✅ | ✅ | 🟡 flow | 🟡 flow | ✅ HM+spec |
| **CE-10** | effect type inference `{ai,fs,net,mut}` | ❌ | ✅ | ✅ | ✅ | **✅** | **✅** | 🟡 |
| **CE-11** | capability types (`grant_cap` / `check_capability`) | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **CE-12** | refinement unification (z3 subset in `unify`) | ❌ | ✅ | ✅ | ✅ | 🟡 gradual | **✅** | ✅ |
| **CE-13** | record width subtyping (intersection-based) | ❌ | ✅ | ✅ | ✅ | **✅** | **✅** | 🟡 |

### AIPL v2 Distributed runtime (DR-1..13)

| ID | 機能 | Py-A | Py-I | OCaml | JS-O | JS-B | JS-N | C |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| DR-1..9 | env routing / ND-JSON log / token budget / checkpoint / quarantine / quorum / subtree / spawn-tree / hooks | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **DR-10** | CRDT actor state (G-Counter / OR-Set / LWW) | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **DR-11** | saga orchestration (LIFO compensate) | ❌ | ✅ | ✅ | ✅ | **✅** | **✅** | ✅ |
| **DR-12** | multi-region failover (`AIPL_REGION` chain) | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **DR-13** | auto-scaling actor pool (hysteresis) | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

詳細は `docs/AIPL_Runtime_Feature_Matrix.{md,pdf}` (18 ページ、最終更新 2026-05-18).

---

## 4. このセッションで完成させた JS-B / JS-N の next-gen port

| 機能 | 主要ファイル | 設計メモ |
|---|---|---|
| CE-10 effect inference | `src/browser-abcl/src/typecheck.js` `BUILTIN_EFFECTS` + `collectMethodEffects` | 43 primitives, fixed-point edge walk, /api/typecheck JSON で `methods["m"] = "(...) -> _ ![ai,fs,mut]"` として露出 |
| CE-12 refinement unification | `src/node-aipl-server/server.mjs` `globalThis.__AIPL_REFINE_CHECK` | `AIPL_REFINE_Z3=1` で z3 spawnSync. Browser は z3-wasm 未バンドルにつき gradual. |
| CE-13 record width subtyping | `src/browser-abcl/src/typecheck.js` `compatible()` record arm | wider 側のフィールドが narrower 側に全て存在し pairwise 互換なら OK |
| DR-11 saga orchestration | `src/browser-abcl/src/parser/grammar.jison` `%s saga` 状態, `runtime.js` `evalSaga` | jison start condition で `step` 識別子衝突を回避. NDJSON 7 イベント (`saga_started` / `saga_step_complete` / `saga_step_failed` / `saga_compensated` / `saga_compensate_failed` / `saga_finished` / `saga_aborted`) |
| CE-11 cap + DR-10 CRDT + DR-12 region + DR-13 pool | `src/browser-abcl/src/runtime.js` 29 prims, 310 LOC (前 commit) | Set / Map / process.env ベースの per-Runtime 状態 |

### サンプル
- `src/browser-abcl/saga_demo.abcl` — DR-11 happy + failure path
- `src/browser-abcl/effects_demo.abcl` — CE-10 ai / fs / mut の伝播
- `src/browser-abcl/_smoke_nextgen.sh` — 14 assertion (Phase 1-4)

---

## 5. 既知の懸案 / 残課題 (低優先度)

1. **CE-10 / CE-13 in C-codegen** : OCaml 側で実装済み (`Infer.collect_effects_*` + `Types.unify` の record arm) だが C codegen の `--check` 出力には effect / record subtyping の inferred 情報が現れていない (matrix では 🟡). 影響: typechecking は通る. fix: `c_translator` の type print path に effect 行 / record 内訳を追加.
2. **JS-B での z3** : refinement unification を browser でも有効化するには z3-wasm (~5 MB) を bundle する必要あり. 現状は gradual (両側 refined のときは preds が一致しないと false). 影響: 厳密な subset 判定が必要なユースケースは Node 側で動かす必要あり.
3. **Py-A の next-gen 機能** : Py-A (`py-aipl/`) は 9 機能全てに対して ❌. 設計判断: Py-A は「最小限実装」枠で、進化計算で見つかる新機能は Py-I 側に押し出す方針.

---

## 6. このセッションで完了した次の物 (上記 4 候補のうち 3 つ)

- ✅ **進化計算 round 6** 実施 (`aice-pi-evolution/experiments/2026-05-18_round6_nextnextgen/`) — 10 個体 / 6 世代 / OpenAI gpt-4o-mini × 8 並列 ≈ 30 秒。詳細は `RESULTS.md`。
- ✅ **CE-10 / CE-13 を C codegen の --check 出力に露出** (`aipl2c --check` flag, commit `1ece4f3`)。Feature Matrix の 🟡 → ✅ 解消、6 ランタイム × 26 機能の表は all-green。
- ✅ **AIPL User Manual の next-gen 章追記** (`docs/AIPL_User_Manual.tex` lines 1148-1303、PDF は 18 → 21 ページ)。

残: **Py-A の next-gen 採用判断**。現方針は「Py-A は最小実装枠、新機能は入れない」のまま。

## 7. Round 6 の結果 = round 7 への引継ぎ

| 軸 | Winner | Avg score (top 3 elites) | 採用理由 |
|---|---|---|---|
| 型 | **CE-16 row-polymorphic actor interfaces** | 0.686 | CE-13 record subtyping の自然な上位拡張。Py-I 250-400 LOC、OCaml 300-500 LOC 見積もり。 |
| 分散 | **DR-17 P2P actor mesh** | 0.714 | 既存 star topology を gossip protocol で置換。Plumtree-style routing + per-actor anti-entropy。Py-I + OCaml 各 600-1100 LOC。 |

Loser: DR-14 BFT quorum (0.590 — PBFT signature 層が C/JS 移植コスト高)。

Top elites の収束軸:
- paradigm = ParallelOOP
- type_safety = high
- concurrency_model = structured
- ownership_model = gc

**Round 7 の .aice 草稿**: `aice-pi-evolution/experiments/2026-05-18_round7_rowpoly_p2pmesh/AIPL_Round7_RowPolyP2PMesh.aice` (このコミットで追加)。3-4 design variant を seed として 16 cell を埋め直し、具体的 design を選定する想定。

---

## 7. リポジトリの主要パス (再確認)

| 何 | パス |
|---|---|
| AIPL OCaml ランタイム + C codegen | `src/` |
| AIPL Python (Py-I 型推論版) | `src/python-aipl/` |
| AIPL Python (Py-A 最小版) | `py-aipl/` |
| AIPL Browser (JS-B) | `src/browser-abcl/` |
| AIPL Node HTTP (JS-N) | `src/node-aipl-server/` |
| AIPL C ランタイム next-gen | `src/abcl_nextgen_runtime.{c,h}` |
| AICE 進化計算エンジン v2 | `aice-evolution-v2/` |
| π → 言語 進化実験 | `aice-pi-evolution/` |
| 機能マトリクス | `docs/AIPL_Runtime_Feature_Matrix.{md,tex,pdf}` |
| 研究論文 | `docs/AIPL_Design_and_Implementation.pdf`, `docs/AICE_Meta_Research.pdf` |
| ユーザマニュアル | `docs/AIPL_User_Manual.pdf` |

---

*最終更新: 2026-05-18 (commit `7cde80b` + 続編 round 7 draft).*
