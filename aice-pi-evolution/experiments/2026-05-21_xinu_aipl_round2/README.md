# AIPL × Embedded Xinu × Raspberry Pi  Round 2

`AIPL` を Embedded Xinu (arm-qemu / 実 Raspberry Pi) で進化させる
プロジェクトの第 2 ラウンド作業ディレクトリ.

## 経緯

`AIPL_XinuRazPi_Round1` (2026-05-20) で R0/R1, P1-P4, F1-F4, G1-G3/G5,
N1 部分, R_BackwardCompat を達成し、その後の追加トラックとして
以下が揃った状態を baseline とする:

- LOAD/COMPILE/RUN 動的 compile pipeline (in-kernel `abclc + cc + aoutRun`)
- pure-AIPL host orchestrator (`host_diners_dynamic.aipl`)
- WM Console + 2nd shell window (WMCON0 + 60×16 cell grid + VT100-lite)
- readline + 32 entry 循環 history (Ctrl-P/N + 矢印 + ESC sequence)
- WM halt 共通化 (SYS_EXIT で QEMU + Cocoa クリーン終了)
- in-Xinu memfs (XFS on RAMDISK0) + shell utilities (ls/pwd/cd/mkdir/cat/cp)
- in-Xinu make (cwd の `.c/.aipl` から Makefile 自動生成 + cc/abclc + run)

加えて Kernel Evolution Round 1 が S1 PriorityAging / S2 MLFQ /
S3 DeadlineHints / S4 IdlePower / Sec1 StackCanaries まで完了済.

## Round 2 設計

`AIPL_XinuRazPi_Round2.aice` — 13 phase / 3 方向 / 53 assertion 目標

| 方向 | phase | 概要 |
|---|---|---|
| **D** In-Xinu Dev env | D1-D5 | REPL / line editor / hot-reload / debugger / module system |
| **C** Multi-Pi Cluster | C1-C4 | bootstrap / remote spawn / actor migration / cluster LWW (CRDT) |
| **O** Observability | O1-O4 | per-actor latency histogram / FB dashboard / distributed trace / memory profiler |
| 横断 | R_BackwardCompat, ImplCost | Round 1 17 + RemoteRPC 2 + kernel evo 5 + memfs/make 2 smoke を全 PASS 維持 |

### implementation_order (依存最小トポロジー)

```
D1 → D3 → D4
D1 + D2 → D5
baseline → D2
baseline → C1 → C2 → C3
                ↘ C4
baseline → O1 → O2
C1 + O1 → O3
baseline → O4
```

## 進化計算

### Reviewers (Gemini ai_v1)

| reviewer | weight | 役割 |
|---|---|---|
| R_DevExperience | 0.25 | REPL/editor/hot-reload/debugger/module の実装容易性 |
| R_DistributedCorrectness | 0.30 | remote spawn / migration / CRDT の正当性 |
| R_ObservabilityCoverage | 0.20 | histogram / dashboard / trace / profiler の overhead |
| R_BackwardCompat | 0.25 | Round 1 + kernel evo + memfs/make smoke の不変保持 |

### 起動コマンド

```sh
# parse-only (.ga.json まで)
cd aice-evolution-v2 && python3 -m src.cli --no-run \
  -o ../aice-pi-evolution/experiments/2026-05-21_xinu_aipl_round2/ \
  ../aice-pi-evolution/experiments/2026-05-21_xinu_aipl_round2/AIPL_XinuRazPi_Round2.aice

# .aipl 生成 + use_ai 0→1 patch (4 reviewer 全て)
python3 -m src.cli --no-run --abcl -o ... AIPL_XinuRazPi_Round2.aice
sed -i.bak -E 's/(new Reviewer\("R_[^"]+", "[^"]+"), 0, (0\.[0-9]+, util, digits\);)/\1, 1, \2/g' \
  AIPL_XinuRazPi_Round2.aipl

# 実行 (Gemini)
AIPL_AI_PROVIDER=gemini python3 -u src/python-aipl/aipl_main.py \
  aice-pi-evolution/experiments/2026-05-21_xinu_aipl_round2/AIPL_XinuRazPi_Round2.aipl \
  --timeout 2400 --idle-ms 600000
# 出力: out/AIPL_XinuRazPi_Round2.aipl_lineage.json
```

## ファイル

| | |
|---|---|
| `AIPL_XinuRazPi_Round2.aice` | 設計書 (ソース) |
| `AIPL_XinuRazPi_Round2.ga.json` | 中間 IR (mock 用、gen=30/seed=8) |
| `AIPL_XinuRazPi_Round2_ai.ga.json` | AI 用 IR メタデータ (gen=15/seed=12/rng=7) |
| `AIPL_XinuRazPi_Round2.aipl` | MAP-Elites orchestrator (gen=10/seed=6、use_ai=1) |
| `out/` | 進化計算結果 (`*.aipl_lineage.json` 等、未作成) |
| `_smoke_*.sh` | phase 別の smoke (未作成、各 phase 完了時に追加) |

## 不変条件 (各 phase 完了時 PASS 必須)

| | |
|---|---|
| Round 1 AIPL smoke | 17 個 (`_smoke_r1.sh` 〜 `_smoke_n1.sh` + memfs/make) in `../2026-05-20_xinu_razpi_aipl/` |
| RemoteRPC smoke | `host_rpc_demo.py` 9/9 + `host_diners.py` 50 meals + `host_diners_dynamic.aipl` |
| kernel evo smoke | `_smoke_s3_deadline.sh` 5/5 + S1/S2/S4/Sec1 既存検証 |
| backwardcompat gate | `_smoke_backwardcompat.sh`: Gate1 ≥ 85/85, Gate2 ≥ 74/85 |

## 各 phase 完了後の checklist

```
1. aipl2c --xinu で .aipl → C 変換が通る
2. Xinu kernel が link 成功 (xinu.elf 生成)
3. QEMU -nographic で xsh$ プロンプトまで到達
4. phase 固有の assertion が green
5. R_BackwardCompat の 4 smoke 群が全 PASS
6. xinu-raz + abclcp-project の両 repo に commit、SHA を本 README に追記
```

## 次のアクション

進化計算 (Gemini) 完走後の lineage を見て、best individual の
(state_model, effect_handling, type_strength, ownership) を確認し、
implementation_order に従って D1 (AIPL REPL) から着手する.
