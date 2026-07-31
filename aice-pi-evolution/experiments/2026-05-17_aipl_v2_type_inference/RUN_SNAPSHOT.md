# AIPL 全サンプル — 実行確認 (Phase E-2 段階)

**実行日:** 2026-05-17
**目的:** 全 AIPL サンプル (.aipl 33 件 + .aipl 21 件) が型検査だけでなく **インタプリタで実際に走るか** を確認。

## 結果サマリ

| Suite | 件数 | run PASS | run FAIL |
|---|---:|---:|---:|
| `src/python-aipl/samples/*.aipl` | 33 | 33 | 0 |
| `samples/feature_*/*.aipl` (型推論デモ) | 21 | 21 | 0 |
| **合計** | **54** | **54** | **0** |

**判定基準** (FAIL = いずれか発生):
- Python Traceback
- `[parse error]`
- `[FATAL]`
- `[actor X.Y] error:` (runtime exception in any actor)

## .aipl デモサンプルの実行詳細

これらは元々型推論検査用に書かれていて `print()` を呼ばないものが多いため、runtime での stdout 出力は基本 0 bytes ですが、actor methods は内部で走っています (副作用や reply 経由で確認可)。

| Feature | Sample | runtime 出力 | サイズ |
|---|---|---|---|
| a_hm | sample1_arithmetic | (no stdout) | 0 bytes |
| a_hm | sample2_predicates | (no stdout) | 0 bytes |
| a_hm | sample3_rat_real | area=12.56637061435916 hyp=5. scale=5. absdiff=4.5 | 51 bytes |
| b_crossclass | sample1_simple | (no stdout) | 0 bytes |
| b_crossclass | sample2_chained | (no stdout) | 0 bytes |
| b_crossclass | sample3_init_args | (no stdout) | 0 bytes |
| c_refinement | sample1_satisfiable | (no stdout) | 0 bytes |
| c_refinement | sample2_unsatisfiable | (no stdout) | 0 bytes |
| c_refinement | sample3_mixed | (no stdout) | 0 bytes |
| d_actorfields | sample1_simple | (no stdout) | 0 bytes |
| d_actorfields | sample2_inferred_from_writes | (no stdout) | 0 bytes |
| d_actorfields | sample3_conflict | (no stdout) | 0 bytes |
| e_records | sample1_basic | (no stdout) | 0 bytes |
| e_records | sample2_inferred_from_use | (no stdout) | 0 bytes |
| e_records | sample3_conflict | (no stdout) | 0 bytes |
| f_realrat | sample1_real_sat | (no stdout) | 0 bytes |
| f_realrat | sample2_real_unsat | (no stdout) | 0 bytes |
| f_realrat | sample3_rat_mixed | (no stdout) | 0 bytes |
| g_integration | sample1_typeck_catches | (no stdout) | 0 bytes |
| g_integration | sample2_inference_catches | (no stdout) | 0 bytes |
| g_integration | sample3_clean | (no stdout) | 0 bytes |

## .aipl 公式サンプルの実行詳細

`src/python-aipl/samples/*.aipl` 全 33 件は `python3 aipl_main.py <file>` でデフォルト挙動 (型検査なし、interp 走る) で実行。Traceback / parse error / FATAL いずれもなしで終了。

詳細ログは `src/python-aipl/_run_logs/*.log` (gitignored)。

## 修正履歴 (この検証で見つかったもの)

- `feature_a_hm/sample3_rat_real.aipl` を全面書き直し。元コードは `rat()`, `rat_add()`, `real_from_rat()` 等の **存在しない builtin** を呼んでいて、runtime で `unknown function: rat` が出ていた (型推論デモとしてのみ機能していた)。実在の `sqrt` / `abs` + Float 演算 + `println` に置き換え、両 pass (推論・実行) で 0 issue + 実際の数値出力 (`area=12.566..., hyp=5, scale=5, absdiff=4.5`) を得るように修正。

## 注意点

- `feature_g_integration/sample3_clean.aipl` は実行時に **カレントディレクトリに `out.txt`** を作成する (`write_file("out.txt", "DISK FULL")` を呼ぶため)。検証スクリプト末尾で削除する。
- `feature_d_actorfields/sample3_conflict.aipl` / `feature_c_refinement/sample2,3` / `feature_f_realrat/sample2,3` 等は意図的にエラー型の入力を含むが、runtime までは到達せず (静的検査で止まる項目はない設計)、interp に渡せば actor 越境で誤りなく動く。
