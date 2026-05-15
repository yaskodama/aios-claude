# aice-pi-evolution — NEXT_SESSION ハンドオフ

**最終更新:** 2026-05-15
**前セッションの最後の状態:** 全 4 phase が mock provider で完走、報告書 `REPORT_JA.md` 保存済、`aipl_codegen.py` の arity バグ修正済。

このファイルだけで前回セッションを再現/継続できることを目標にしている。

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
    src = generate_program(spec, schema).replace(f"{stem}.abcl", f"{stem}.aipl")
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
| 言語ファイル拡張子 | `.aipl` (`.abcl` ではなく) | ユーザ明示指定。AIPL = ABCL は本プロジェクトでは同義だが、ユーザは `.aipl` を採用 |
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
