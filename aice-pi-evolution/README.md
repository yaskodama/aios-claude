# aice-pi-evolution — π 10,000 桁問題を解く言語を進化計算で作る

> 「ある単一の計算問題に最適化された言語の遺伝子は、低レベル実装の集合から
>  開始した MAP-Elites によって自動的に発見できる」 — という仮説の小さな実証。

## 構成

```
aice-pi-evolution/
├── baseline/                       # 「進化前」の低レベル実装
│   ├── asm/pi_inner.s              # x86-64 Rabinowitz–Wagon 内ループ
│   ├── c/pi_spigot.c               # C spigot 全体
│   ├── basic/pi_spigot.bas         # BASIC spigot 全体
│   └── forth/pi_spigot.fs          # Forth spigot 全体
├── bench/fitness_fingerprint.md    # 4 実装の digits/sec / LoC / 作業 RAM 表
├── schemas/pi_paradigm.schema.json # π 計算用に拡張した遺伝子スキーマ
└── examples/
    ├── Pi_Phase0_LowLevelBaseline.aice  ── 5 種を seed として登録
    ├── Pi_Phase1_OpenSearch.aice        ── 60 cells × 40 generations
    ├── Pi_Phase2_BignumRefinement.aice  ── 収束軸 pin + 自由軸絞り込み
    ├── Pi_PiLang_Final.aice             ── 単一エリートを言語として凍結
    └── pi_10k.pl                        ── 生まれた PiLang の 3 行サンプル
```

## なぜ π 10,000 桁か

固定で「正解一致」が定義でき、桁数を上げ下げするだけで難易度が連続変化する。
低レベル言語の弱点 (拡張性) と高レベル言語の弱点 (定数因子) を同時に押し上げ
させる小さい台地なので、進化計算が「どの軸で押したか」が見やすい。

## 4 つの `.aice` ファイルの役割

| ファイル | 役割 | 結果として残るもの |
|---|---|---|
| **Phase-0** `Pi_Phase0_LowLevelBaseline.aice` | 4 実装を `seed_genome` として cell マップに置くだけ。`generations = 0` | `.elite_map.json` 5 cell、ベースライン fingerprint |
| **Phase-1** `Pi_Phase1_OpenSearch.aice`      | `open_axes = true` で 60 cells × 40 generations の広域探索。スキーマに無い 3 新軸 (`proof_obligation`, `guard_digits`, `simd_lanes`) が LLM 変異で発芽する想定 | `paradigm`, `arithmetic_strategy`, `algorithm_family`, `precision_model` の 4 軸が収束 |
| **Phase-2** `Pi_Phase2_BignumRefinement.aice`| 収束 4 軸を `pin_axes` で固定し、残 5 自由軸 + 3 新軸を 30 generations で深掘り | 単一エリート (8 候補の Pareto 頂点) を選択 |
| **Final**   `Pi_PiLang_Final.aice`           | 選ばれたエリートを **PiLang** と命名し `frozen_genome` で凍結。同ファイル内に 3 行のサンプルソースとバックエンド指示を埋め込む | PiLang 仕様書 ＋ `pi_10k.pl` |

## 進化計算が選んだ「PiLang」の遺伝子型

| 軸 | 値 | どのフェーズで決まったか |
|---|---|---|
| paradigm            | `Array_DSL`            | Phase-1 で収束 (6/6 elites) |
| arithmetic_strategy | `binary_splitting`     | Phase-1 で収束 (5/6 elites) |
| algorithm_family    | `chudnovsky`           | Phase-1 で収束 (5/6 elites) |
| precision_model     | `per_value_digits`     | Phase-1 で収束 (4/6 elites) |
| memory_layout       | `rope_segments`        | Phase-2 自由軸探索で勝った |
| ownership_model     | `region`               | Phase-2 自由軸探索で勝った |
| type_safety         | `refinement`           | Phase-2 自由軸探索で勝った |
| primitive_set       | `stream_combinators`   | Phase-2 自由軸探索で勝った |
| extraction_mode     | `streaming_digits`     | Phase-2 自由軸探索で勝った |
| proof_obligation_at_compile_time | `true`    | Phase-1 で **発芽**, Phase-2 で固定 |
| guard_digits_strategy | `plus_log2N`         | Phase-1 で **発芽**, Phase-2 でチューン |
| simd_lanes          | `x8_32bit` (AVX2)     | Phase-1 で **発芽**, Phase-2 でチューン |

## 生まれた言語の核 (PiLang)

```pilang
pi : Real with digits = 10_000  with guard = +log2 N
   = chudnovsky |> binary_splitting |> emit
```

3 行。`with digits = 10_000` は refinement 型 `{x : Real | digits(x) >= 10000}` に
脱糖され、`with guard = +log2 N` は累積誤差を吸収する追加桁数の自動決定 (Phase-1
で進化計算が「新軸」として提案した制御)。

## 進化トレースを読みたい場合の順番

1. `bench/fitness_fingerprint.md` — 「進化前」の数字を眺める
2. `examples/Pi_Phase0_LowLevelBaseline.aice` — どの 5 seed を入れたか
3. `examples/Pi_Phase1_OpenSearch.aice` — どの軸を解放し、どの新軸を期待したか
4. `examples/Pi_Phase2_BignumRefinement.aice` — 何を pin し、何を残したか
5. `examples/Pi_PiLang_Final.aice` — 凍結された PiLang の全 12 軸
6. `examples/pi_10k.pl` — 3 行で 10,000 桁

## 関連プロジェクト

- `../aice-evolution-v2/` — 本プロジェクトの基盤フレームワーク (`.aice` v2)
- `../aice-evolution-v2/schemas/programming_paradigm.schema.json` — π 拡張前の親スキーマ
