# AIPL × Embedded Xinu × Raspberry Pi  Evolution

`AIPL` を Embedded Xinu (arm-qemu / 実 Raspberry Pi) で進化させる
プロジェクトの作業ディレクトリ.

## Round 0 — 既存資産

| 項目 | パス |
|---|---|
| codegen | `src/aipl2c.ml --xinu` + `src/c_translator.ml:gen_program_xinu` (3283 行) |
| サンプル | `abclc/{Rotate4LinesXinu, Philosophers5Xinu, BoundedBufferXinu}.aipl` |
| 起動 sh | `run_{r4l, p5, bb, pingpong}_xinu.sh` |
| Xinu 本体 | `/Users/kodamay/projects/xinu-raz/xinu` (別 git, arm-qemu + PL110 LCD + PL050 mouse + WM) |

### 2026-05-20 動作確認の結果

- ✅ `aipl2c --xinu --no-typecheck` で 3 サンプル → C 変換 + Xinu link 成功
- ✅ `qemu-system-arm` で `xinu.elf` ブート、`xsh$` プロンプト + mouse/keyboard ready
- ⚠️ **regression**: 3 サンプル全てが現行型チェッカーで reject される
  - R4L: `tick : () -> 'a [Type error]`
  - P5: `send target is not actor: int`
  - BB: `put : ('a) -> 'b [Type error]`

## Round 1 設計

`AIPL_XinuRazPi_Round1.aice` — 21 phase / 5 方向 / 63 assertion 目標

| 方向 | phase | 概要 |
|---|---|---|
| **R** regression | R0, R1 | 型チェック修復 + smoke 自動化 |
| **P** scheduler | P1-P4 | actor=Xinu thread, priority, lock-free mailbox, sched visualizer |
| **F** features | F1-F4 | DistCheckpoint, LWW cell, effect/type parity, strings & arrays |
| **G** GUI/I/O | G1-G5 | framebuffer primitives, bitmap font, mouse dispatch, real-Pi GPIO, image bitmap |
| **N** network | N1-N4 | TCP/IP, WebSocket bridge, multi-Pi cluster, mDNS discovery |
| 横断 | R_BackwardCompat, ImplCost | 既存 26 個の CE/DR が壊れないこと、LOC 制約 |

## 進化計算結果

### mock_v1 (大規模)
- 38 個体 / 6 cells filled / 30 generations
- Best paradigm: ParallelOOP / BASIC / C / FunctionalOOP (composite 0.649 同点)
- 進化方向: `type_safety +0.75`, `concurrency_model -0.25`
- シナリオ 3 つ全て I0008 (ParallelOOP) が首位

### OpenAI gpt-4o-mini (小規模実評価)
- 14 個体 / 4 cells filled / 10 generations
- Best paradigm: **ParallelOOP** (composite 0.324)
- 進化方向: **`concurrency_model +1.00` (actor_messages 方向 — drone-sim と同じ!)**
- シナリオ別首位:
  - conservative → I0001 (BASIC) — 「組み込み環境の単純さ」
  - innovative → I0003 (C) — 「Xinu はもともと C カーネル」
  - general_purpose → I0003 (C) — 同上

### 統合的解釈

両 evaluator は **`actor_messages` × `type_safety = high`** を Xinu/Pi 上の
AIPL 進化方向として強く支持.特に OpenAI は組み込み現実 (C 親和) を
反映して C/BASIC も評価.

→ Round 1 設計の **方向 P (actor→Xinu thread)** と
**方向 F (effect/type parity, LWW)** が進化計算結果と整合.
**方向 G/N** は composite に直接効かないが、デモ価値 + 実 Pi 適合性で
独立に追求.

## ファイル

| | |
|---|---|
| `AIPL_XinuRazPi_Round1.aice` | 設計書 |
| `AIPL_XinuRazPi_Round1_ai.ga.json` | OpenAI 用 IR (gen=10 / seed=4) |
| `out/` | mock_v1 結果 (.ga.json / .lineage.json / .elite_map.json / .report.md / .ranking.json) |
| `out_ai/` | OpenAI gpt-4o-mini 結果 同上 |

## 次のアクション

R0 (型チェック修復) → R1 (smoke 自動化) → P1 (actor=Xinu thread) の順に
implementation_order に従って 1 phase = 1 commit で進める.

各 phase 完了後の checklist:

```
1. aipl2c --xinu --no-typecheck で .aipl → C 変換が通る
2. Xinu kernel が link 成功 (xinu.elf 生成)
3. QEMU -nographic で xsh$ プロンプトまで到達
4. phase 固有の assertion が green
```
