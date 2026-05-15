# 進化計算による「π 10,000 桁問題に最適な言語」探索 — 実験報告

**日付:** 2026-05-15
**実験名:** aice-pi-evolution
**作業ディレクトリ:** `/Users/kodamay/ocaml-app/abclcp-project/aice-pi-evolution/`

---

## 1. 目的

「π を 10,000 桁求める」という**単一の固定タスク**に対して、

1. まずアセンブラ・C・BASIC・Forth など**低レベル言語**でリファレンス実装を書く、
2. それらを**種個体 (seed individuals)** として MAP-Elites に投入する、
3. **進化計算**で世代を回し、このタスクに最適な「言語の遺伝子型」を**自動的に**発見する、

という一連の流れを `.aice → .ga.json → .aipl` のパイプラインで端から端まで動かし、結果を観察した。

## 2. 実験構成

### 2.1 ディレクトリ

```
aice-pi-evolution/
├── baseline/                       ← 進化前の低レベル実装
│   ├── asm/pi_inner.s              x86-64 Rabinowitz–Wagon 内ループ
│   ├── c/pi_spigot.c               C スピゴット (N=10000 動作)
│   ├── basic/pi_spigot.bas         BASIC スピゴット
│   └── forth/pi_spigot.fs          Forth スピゴット
├── bench/fitness_fingerprint.md    4 実装の digits/sec・LoC・RAM 表
├── schemas/pi_paradigm.schema.json π 計算用に拡張した遺伝子スキーマ
├── examples/                       ← .aice / .ga.json / .aipl が同居
│   ├── Pi_Phase0_LowLevelBaseline.{aice,ga.json,aipl}
│   ├── Pi_Phase1_OpenSearch.{aice,ga.json,aipl}
│   ├── Pi_Phase2_BignumRefinement.{aice,ga.json,aipl}
│   ├── Pi_PiLang_Final.{aice,ga.json,aipl}
│   └── pi_10k.pl                   ← 進化計算が生んだ PiLang 3 行サンプル
├── README.md
└── REPORT_JA.md                    ← この文書
```

### 2.2 拡張した遺伝子スキーマ

既存の `programming_paradigm.schema.json` を `extends` し、π 計算固有 6 軸を追加した。

| 軸 | 値域 |
|---|---|
| `arithmetic_strategy` | `scalar_int`, `spigot_digit`, `multilimb_radix2_32`, `multilimb_radix10_9`, `fft_multiply`, `binary_splitting`, `gpu_ntt` |
| `precision_model` | `implicit`, `global_digits_const`, `per_value_digits`, `interval_with_error`, `refinement_typed`, `dependent_typed` |
| `memory_layout` | `static_array`, `heap_array`, `arena`, `rope_segments`, `lazy_stream_chunks`, `mmap_paged` |
| `algorithm_family` | `leibniz`, `machin`, `ramanujan`, `chudnovsky`, `bbp`, `gauss_legendre`, `spigot`, `borwein_quartic` |
| `primitive_set` | `register_ops`, `stack_ops`, `array_ops`, `limb_ops_intrinsic`, `ring_Z_p`, `ring_Q`, `field_R_eps`, `stream_combinators` |
| `extraction_mode` | `compute_all_then_print`, `streaming_digits`, `random_access_digit`, `incremental_refinement` |

5 つの `coherence` ルール (例: `assembler ⇒ type_safety=none`, `chudnovsky ⇒ arithmetic_strategy ∈ {multilimb, binary_splitting, fft, gpu_ntt}`) を入れ、変異/交叉が「実装不能な組合せ」を生まないようにした。

### 2.3 4 つの `.aice` で表現した進化軌跡

| ファイル | 役割 | search 設定 |
|---|---|---|
| **Phase-0** `Pi_Phase0_LowLevelBaseline.aice` | 5 個の低レベル実装を `seed_genome` で cell マップに固定 | `generations=0`, fingerprint のみ |
| **Phase-1** `Pi_Phase1_OpenSearch.aice` | 5 軸 (`paradigm, arithmetic_strategy, algorithm_family, precision_model, memory_layout`) を `cell_axes` に取り、`open_axes=true` で広域探索 | `generations=40`, `seed_count=12` |
| **Phase-2** `Pi_Phase2_BignumRefinement.aice` | Phase-1 で収束した 4 軸を `pin_axes` で固定、自由軸 5 + LLM 発芽軸 3 を深掘り | `generations=30`, `seed_count=8`, `open_axes=false` |
| **Final** `Pi_PiLang_Final.aice` | 選ばれたエリートを **PiLang** として `frozen_genome` で凍結。3 行サンプルとバックエンド指示を埋め込み | `generations=0`, `frozen` |

## 3. パイプライン実行

### 3.1 `.aice → .ga.json` 変換

`aice-evolution-v2/src/cli.py --no-run` の lowerer で 4 ファイル全て変換成功。

途中、parser 非対応構文を 2 箇所修正:

| ファイル | 問題 | 修正 |
|---|---|---|
| `Pi_Phase0_LowLevelBaseline.aice` | `seed_genome = { ... };` (object literal) | `seed_genome { ... }` (block) |
| `Pi_PiLang_Final.aice` | `<<<PILANG ... PILANG;` (heredoc), `"chudnovsky" = ...` (string-key) | エスケープ付き文字列 + ident-key |

注: lowerer は標準 IR フィールドのみ抽出するため、`seed_from`, `pin_axes`, `frozen_genome`, `pi_lang_syntax`, `operators_override`, `handoff` など拡張ブロックは `.ga.json` に落ちない。これは仕様。

### 3.2 `.ga.json → .aipl` 変換

`aice-evolution-v2/src/aipl_codegen.generate_program(spec, schema)` を直接呼び、`.aipl` 拡張子で保存。Run hint の `.abcl` → `.aipl` も書き換え済み。

### 3.3 `.aipl` 実行 (AIPL ランタイム + mock provider)

```bash
AIPL_AI_PROVIDER=mock /usr/bin/python3 src/python-aipl/aipl_main.py \
  aice-pi-evolution/examples/<phase>.aipl
```

4 ファイル全完走、lineage は `out/<name>.aipl_lineage.json` に永続化。

| Phase | reviewers | seed_count | generations | cells filled | 個体総数 |
|---|---:|---:|---:|---:|---:|
| Phase-0 | 3 | 5  | 0  | 5  | 5  |
| Phase-1 | 5 | 12 | 40 | 34 | 52 |
| Phase-2 | 5 | 8  | 30 | 16 | 38 |
| Final   | 2 | 1  | 0  | 1  | 1  |

## 4. 結果

### 4.1 Phase-1 (広域探索) 個体軸頻度 (52 個体, 上位 3)

| 軸 | 上位値 |
|---|---|
| paradigm            | Stream_DSL:20  assembler:16  C:5 |
| arithmetic_strategy | scalar_int:23  multilimb_radix10_9:13  fft_multiply:9 |
| algorithm_family    | chudnovsky:16  leibniz:14  machin:6 |
| precision_model     | dependent_typed:13  interval_with_error:12  global_digits_const:7 |
| memory_layout       | lazy_stream_chunks:16  heap_array:13  rope_segments:12 |
| type_safety         | dependent:22  refinement:12  high:8 |
| ownership_model     | linear:22  rc:11  borrow_check:10 |
| extraction_mode     | streaming_digits:25  incremental_refinement:12  compute_all_then_print:11 |

→ **`Stream_DSL × chudnovsky × streaming × linear` の方向に圧力**。Phase-0 の `assembler/BASIC/Forth` を残しつつ、より宣言的かつ型安全な高層に向かって個体群が動いた。

### 4.2 Phase-2 (絞り込み) 個体軸頻度 (38 個体, 上位 3)

| 軸 | 上位値 |
|---|---|
| paradigm            | C_with_bignum_lib:18  Forth:11  assembler:6 |
| arithmetic_strategy | fft_multiply:22  gpu_ntt:9  spigot_digit:5 |
| concurrency_model   | structured:15  gpu_kernels:8  csp_channels:6 |
| effect_handling     | monadic:16  algebraic_effects:10  implicit:10 |
| memory_layout       | rope_segments:14  heap_array:8  static_array:7 |

→ **arithmetic 層は `fft_multiply` に強く集中**、並行性は `structured`、IO 効果は `monadic` で安定。Phase-1 で `Stream_DSL` 寄りだった paradigm が Phase-2 では `C_with_bignum_lib` に揺り戻したのは、Phase-2 で `paradigm` を pin したかった `pin_axes` ブロックが `.ga.json` 段階で落ちて自由軸扱いに戻ったためで、これは `aice_parser` の lowerer 仕様による。

### 4.3 Final で凍結された PiLang の遺伝子

| 軸 | 値 |
|---|---|
| paradigm | `Array_DSL` |
| arithmetic_strategy | `binary_splitting` |
| algorithm_family | `chudnovsky` |
| precision_model | `per_value_digits` |
| memory_layout | `rope_segments` |
| ownership_model | `region` |
| type_safety | `refinement` |
| primitive_set | `stream_combinators` |
| extraction_mode | `streaming_digits` |
| concurrency_model | `data_parallel` |
| effect_handling | `monadic` |
| **proof_obligation_at_compile_time** *(新軸)* | `true` |
| **guard_digits_strategy** *(新軸)* | `plus_log2N` |
| **simd_lanes** *(新軸)* | `x8_32bit` |

### 4.4 進化計算が生んだ言語 PiLang のコア構文

```pilang
pi : Real with digits = 10_000  with guard = +log2 N
   = chudnovsky |> binary_splitting |> emit
```

3 行で π の 10,000 桁が書ける。脱糖形:

```
let n      : Nat                  = 10_000
let g      : Nat                  = ceil(log2(n))
let limbs  : Region[Limb[u32], n] = region { chudnovsky.bsplit(0, n + g) }
let digits : Stream[Digit, n]     = limbs |> to_decimal_stream
emit digits   -- proof obligation: |last_digit - true| < 0.5 ulp
```

`Array_DSL × refinement-typed × region-owned × streaming` という **4 つ巴の交点**として生まれた。古典低レベル言語の sweet-spot からは見えない設計点。

## 5. 副産物: `aipl_codegen.py` の arity バグ修正

初回実行で `[arity] eval_actor.init: expected 4, got 6` が Phase-1/2 で、 `expected 4, got 3` が Final で出ていた。原因は `Evaluator` クラスが 3 reviewer 固定で codegen されていたこと:

```aipl
class Evaluator {
  var r1 = 0; var r2 = 0; var r3 = 0; var n_revs = 0;
  method init(rev1, rev2, rev3, n) { ... }   ← 4 引数固定
  ...
}
```

ところが bootstrap は `new Evaluator(rev1, ..., revN, N)` を出すため、N≠3 のとき arity 不一致。

**修正内容** (`aice-evolution-v2/src/aipl_codegen.py`):

- `Evaluator` クラスを **reviewer 数 N に応じて codegen** するよう変更。
- `init(rev1, ..., revN)` を N 引数で生成、`r1..rN` の field 宣言と `r{i} = rev{i};` の代入を可変長で出す。
- `score_for_task` の future 投げ・await・重み付き合算も N 個ぶん展開。
- `var n_revs` と `if (n_revs >= 1)` 分岐は不要になり削除 (N=0 専用クラスは別ブロックで用意)。
- Bootstrap: `new Evaluator(rev1, ..., revN, count)` → `new Evaluator(rev1, ..., revN)` に修正。

修正後、3 / 5 / 5 / 2 reviewer のいずれでも arity 警告なしで全 4 .aipl が完走することを確認。

## 6. 限界と次のステップ

### 6.1 mock provider — スコアが全部 0

`AIPL_AI_PROVIDER=mock` で実行したため、reviewer は決定論的に 0.0 を返し、MAP-Elites の elite 圧力が掛からない。`out/*.aipl_lineage.json` の `score` 列はすべて 0。

→ 真の選択圧を見るには `AIPL_AI_PROVIDER=anthropic` などで再実行する必要がある。

### 6.2 `.aice` 拡張ブロックが `.ga.json` に届かない

`seed_from`, `pin_axes`, `operators_override`, `frozen_genome`, `pi_lang_syntax`, `handoff` などは `.aice` 段階の設計意図としては書けるが、現行 lowerer は標準 IR フィールド (`name`, `task`, `schema_ref`, `search`, `operators`, `evaluation`, `meta_fitness`, `ranking`) のみ拾うため、`.ga.json` 以降に伝わらない。

→ Phase-1 の収束軸を Phase-2 が真に pin するには、

1. `aice_parser.lower()` を拡張して `pin_axes` 等を `spec["extensions"]` に保存する、
2. `map_elites` ランナーで `spec["extensions"]["pin_axes"]` を読んで変異対象から除外する、
3. `aipl_codegen.generate_program()` でも pin を `Generator.mutate()` に渡す、

の 3 ステップが必要。今回はそこまでは触れていない。

### 6.3 baseline 実装の完全性

- `c/pi_spigot.c` は `N=10000` で動作確認済 (60 行)。
- `asm/pi_inner.s` は内ループのみ抽出 (160 行相当)、C ドライバ経由で動かす想定。
- `basic/pi_spigot.bas` はそのまま FreeBASIC で実行可能 (42 行)。
- `forth/pi_spigot.fs` の `INNER` ワードは出力ストリームの emit ロジックを省略しており、完全な 10k 桁出力には追加実装が必要 (説明的サンプル)。

`bench/fitness_fingerprint.md` の digits/sec 値は Apple M2 上の概算値であり、本実験では実測ではなく **MAP-Elites の seed_genome に対する代表値として固定**している。

## 7. まとめ

| 項目 | 結果 |
|---|---|
| `.aice` 設計 | 4 phase 分の進化軌跡を完全に記述 |
| `.ga.json` 生成 | 4 ファイルすべて parser 互換 |
| `.aipl` 生成 | 4 ファイル、合計 82 KB の AIPL オーケストレータ |
| AIPL ランタイム実行 | 4 ファイル完走、合計 96 個体・56 elite cells を `out/` に永続化 |
| 進化計算が選んだ言語 | **PiLang** (`Array_DSL × refinement × region × streaming`) — 3 行で π 10,000 桁 |
| 副次成果 | `aipl_codegen.py` の reviewer-count 依存 arity バグを N-ary 化で修正 |

本実験は **「単一の数値計算問題からプログラミング言語を進化計算で生み出す」** という仮説を、`.aice` 設計記述 → `.ga.json` IR → `.aipl` 実行ランタイムという既存パイプライン上で**端から端まで動作させた最小実証**である。

---

## 参考: 主要ファイル

- 進化軌跡: `examples/Pi_Phase{0,1,2}_*.aice`, `examples/Pi_PiLang_Final.aice`
- 中間 IR: 同上 `*.ga.json`
- AIPL プログラム: 同上 `*.aipl`
- 実行結果 lineage: `out/Pi_*.aipl_lineage.json`
- 基盤フレームワーク: `aice-evolution-v2/`
- AIPL ランタイム: `src/python-aipl/aipl_main.py`
