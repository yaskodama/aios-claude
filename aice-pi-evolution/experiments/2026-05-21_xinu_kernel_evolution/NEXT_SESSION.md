# NEXT_SESSION.md — Xinu Kernel Evolution + RemoteRPC + DP

2026-05-21 セッション終了時点のハンドオフ。次回再起動時にここから読めば
全コミットの位置 + 残作業 + 再現コマンドが分かる。

## 1. 何ができたか — 累計サマリ

3 つのトラックが並走しています:

### A. Xinu Kernel Evolution Round 1 (6 phase 完了 / 16 中)

`.aice` 設計書 + 7 軸 schema + 4 Gemini reviewer。MAP-Elites 進化計算は
seed=6 gen=20 で 1 回実行したが Gemini API timeout で lineage 未生成
(再走 or scope 縮小が今後の選択肢)。

| Phase | xinu-raz commit | AIPL commit | 効果 |
|---|---|---|---|
| S4 IdlePower | `44521cf` | — | `pause()` (= ARM `wfi`) 無条件化。QEMU host CPU が idle 時 ~100% → ~0% |
| S1 PriorityAging | `74e92c9` | — | 100ms tick で THRREADY thread の prio +1 (cap basepri+5)、dispatch 時に basepri snap-back |
| Sec1 StackCanaries | `96b5abb` | — | `-fstack-protector-strong` + `__stack_chk_guard` / `__stack_chk_fail` stub |
| Sec3 MeasuredBoot | `5b6f8d8` | — | boot 時に kernel .text+.rodata の FNV-1a 64 hash を UART0 出力 |
| S3 DeadlineHints | `9f6796e` + `cf0870d` | `b683529` | `deadline_at` field + `setdeadline()` syscall + resched の EDF pick + AIPL extern `set_deadline(actor, ms)` |
| S2 MLFQ | `a6aa457` | — | `quantum_left` 40ms、消化時 prio -5 demote (cap basepri-15)。S1 aging が自然な promotion 路 |

検証 smoke:
- `_smoke_p2.sh` (Priority3Xinu) — 4/4 PASS、no-starvation 維持
- `_smoke_s3_deadline.sh` — 5/5 PASS (DeadlineDemoXinu で Urgent が
  priority=low + 5000ms deadline で priority=high Hoarder の前に dispatch)
- `_smoke_backwardcompat.sh` — Gate1 typecheck 86/86, Gate2 xinu codegen 73/86 (allowlist 13)

### B. RemoteRPC (Host PC ↔ Xinu の双方向通信)

| Item | commit | 内容 |
|---|---|---|
| Xinu RPC dispatcher | `976c313` (xinu-raz) | UART1 (PL011 @ 0x101F2000) を `-serial tcp:127.0.0.1:5555` で expose、`rpc_dispatcher_main` thread が PING/SEND/QUERY/LIST 処理 |
| AIPL side | `be36abe` | abclc/RemoteRpcDemoXinu.aipl (Counter + Greeter)、host_rpc_demo.{sh,py} |
| Diners distributed | `d1d8eae` | abclc/DiningPhilosophersDistXinu.aipl (5 Fork + 2 Philosopher) + host_diners.py |
| Dynamic compile | `0baaa26` (xinu-raz) + `d2bf864` | RPC に LOAD/COMPILE/RUN 追加、in-kernel `abclcTranslate + ccCompile + aoutRun` を駆動 |
| **Pure-AIPL host** | `4823978` | `tcp_*` 5 builtin を Py-I に追加、`host_diners_dynamic.aipl` (162 行) — Python script なしで AIPL のみで host を駆動 |
| Re-generated artifacts | `12255db` | `.aipl` の seed=6/gen=20 patch + Xinu kernel evolution の生成 .aipl |

### C. 進化計算 (`.aice` → `.aipl` → 実走)

| Project | 状態 |
|---|---|
| **AIPL_XinuRazPi_RemoteRPC** | seed=6 gen=20 で実走、Gemini timeout で gen 5 / 11 individuals で停止。**Best: `paradigm=C + actor_messages + capability + gc @ score 0.755`** (I3 と I10 で 2 度独立到達)。実装 (`apps/abcl_xinu_rpc.c` = C + actor_messages + capability) と整合 |
| **Xinu_KernelEvolution_Round1** | `.aice` 設計書済 (`aice-pi-evolution/experiments/2026-05-21_xinu_kernel_evolution/`)、`.aipl` 生成済、seed=6 gen=20 で実走したが Gemini timeout で seed phase 内で停止 (lineage 未生成)。実装は手動で 6 phase 進行中 |

## 2. 既存資産 (Round 1 — AIPL on Xinu) の不変条件

Round 1 で確立した **17 smoke (R1/P1-P4/F1-F4/G1-G3/G5/N1-partial)** +
RemoteRPC の **host_rpc_demo.py (9/9)** + **host_diners.py (50 meals)** +
**`_smoke_backwardcompat.sh` (86/86 typecheck + 73/86 xinu codegen
allowlist)** は **絶対不変条件**。kernel evolution phase が壊したら
roll-back。

直近のフル regression 確認: 全 phase 経て **PASS** 維持中。

## 3. ファイルマップ

```
/Users/kodamay/ocaml-app/abclcp-project/                ← abclcp-project (origin: aios-claude.git)
├── abclc/
│   ├── DiningPhilosophersDistXinu.aipl                    ← Fork×5 + Philosopher×2 (10 meals each)
│   ├── RemoteRpcDemoXinu.aipl                              ← Counter + Greeter
│   ├── DeadlineDemoXinu.aipl                               ← S3 demo (Urgent vs Hoarder)
│   └── (既存 R/P/F/G samples)
├── src/
│   ├── c_translator.ml                                     ← --xinu codegen + runtime accessors
│   │                                                          (abcl_object_field_*, abcl_object_tid,
│   │                                                           abcl_object_class_id, abcl_n_objects)
│   ├── typing_env.ml                                       ← AIPL extern type sigs (G2/G3/G5/F1/F2/RPC/S3)
│   └── python-aipl/
│       └── aipl_interp.py                                  ← Py-I runtime + tcp_* builtins
├── aice-pi-evolution/experiments/
│   ├── 2026-05-20_xinu_razpi_aipl/                         ← AIPL on Xinu Round 1
│   │   ├── AIPL_XinuRazPi_Round1.aice                       (21 phase 設計書)
│   │   ├── _smoke_{r1,p1..p4,f1..f4,g1..g3,g5,n1}.sh        (17 既存 smoke)
│   │   └── _smoke_backwardcompat.sh                         (Gate1/2 + allowlist 13 samples)
│   ├── 2026-05-20_xinu_remote_rpc/                         ← RemoteRPC + dynamic compile
│   │   ├── AIPL_XinuRazPi_RemoteRPC.aice / .aipl / .ga.json (5 phase 設計、seed=6 gen=20)
│   │   ├── host_rpc_demo.{sh,py}                           (9-step PING/SEND/QUERY/LIST テスト)
│   │   ├── host_diners.py                                   (3 PC philosopher Python, 10 meals)
│   │   ├── host_diners_dynamic.py                           (= 上記 + dynamic LOAD/COMPILE/RUN)
│   │   └── host_diners_dynamic.aipl                          ← **pure-AIPL 版** (Python不要、162行)
│   └── 2026-05-21_xinu_kernel_evolution/                   ← Xinu kernel 進化 Round 1
│       ├── Xinu_KernelEvolution_Round1.aice                 (16 phase + 2 cross-cut)
│       ├── Xinu_KernelEvolution_Round1.aipl / .ga.json
│       ├── README.md
│       ├── _smoke_s3_deadline.sh                            (5/5 PASS)
│       └── NEXT_SESSION.md                                  ← この文書
├── aice-evolution-v2/schemas/xinu_kernel.schema.json       ← 7 軸 + 12 coherence rules
└── out/                                                    ← lineage.json 出力先 (gitignore)

/Users/kodamay/projects/xinu-raz/xinu/                  ← xinu-raz (origin: xinu-rpi.git)
├── apps/
│   ├── abcl_xinu_gui.c                                       (G1/G2/G3/G5 + F1 chkpt + F2 lww + S3 set_deadline)
│   ├── abcl_xinu_rpc.c                                       (UART1 dispatcher, PING/SEND/QUERY/LIST/LOAD/COMPILE/RUN)
│   ├── abcl_xinu_str.c                                       (F4 strings + arrays + abcl_array_view)
│   ├── abcl_program.c                                        ← 一時 build slot (毎回 cp で上書き、commit 対象外)
│   └── Makerules
├── system/
│   ├── aging.c                                              ← S1 PriorityAging + S2 MLFQ tick
│   ├── setdeadline.c                                        ← S3 syscall
│   ├── stack_canary.c                                       ← Sec1 stubs
│   ├── measured_boot.c                                      ← Sec3 FNV-1a 64 hash
│   ├── initialize.c                                         (nulluser + S4 unconditional wfi + Sec3 hook)
│   ├── resched.c                                            (+ S1 snap-back + S2 quantum reset + S3 EDF pick)
│   ├── clkhandler.c                                         (aging_tick + mlfq_tick)
│   └── create.c                                             (basepri + deadline_at + quantum_left init)
├── include/thread.h                                         (struct thrent + basepri/deadline_at/quantum_left)
├── compile/
│   ├── Makefile                                             (+ -fstack-protector-strong)
│   └── platforms/arm-qemu/ld.script                         (+ _stext = .)
└── (他 device/system/shell etc, pre-existing)
```

## 4. 再現コマンド集

### 4.1 ビルド (一度だけ)
```sh
# OCaml (aipl2c)
cd /Users/kodamay/ocaml-app/abclcp-project
dune build

# Xinu kernel
cd /Users/kodamay/projects/xinu-raz/xinu/compile
make PLATFORM=arm-qemu COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi- clean
make PLATFORM=arm-qemu COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi- DEBUG=-DAIPL_AUTOSTART
```

### 4.2 既存 AIPL on Xinu smoke (regression gate)
```sh
cd /Users/kodamay/ocaml-app/abclcp-project
# Backward compat: 86/86 typecheck + 73/86 xinu codegen (allowlist 13)
bash aice-pi-evolution/experiments/2026-05-20_xinu_razpi_aipl/_smoke_backwardcompat.sh
# Priority3Xinu (covers S1 + S2 + S3 still good)
bash aice-pi-evolution/experiments/2026-05-20_xinu_razpi_aipl/_smoke_p2.sh
# Deadline demo
bash aice-pi-evolution/experiments/2026-05-21_xinu_kernel_evolution/_smoke_s3_deadline.sh
```

### 4.3 RemoteRPC + Diners (2 terminal)

**Terminal A (どこでも実行可、絶対パス):**
```sh
# まず DiningPhilosophers を baked-in した kernel.elf にしたい場合:
cd /Users/kodamay/ocaml-app/abclcp-project
./_build/default/src/aipl2c.exe abclc/DiningPhilosophersDistXinu.aipl \
    -o /tmp/dp.c --xinu --max-msgs 0
cp /tmp/dp.c /Users/kodamay/projects/xinu-raz/xinu/apps/abcl_program.c
( cd /Users/kodamay/projects/xinu-raz/xinu/compile \
  && make PLATFORM=arm-qemu COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi- DEBUG=-DAIPL_AUTOSTART )

# それから boot
qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
    -kernel /Users/kodamay/projects/xinu-raz/xinu/compile/xinu.elf -nographic \
    -serial mon:stdio \
    -serial tcp:127.0.0.1:5555,server=on,wait=off
```

**Terminal B (必ず abclcp-project ルート):**
```sh
cd /Users/kodamay/ocaml-app/abclcp-project

# 単発 RPC テスト (PING/SEND/QUERY/LIST 9 step) — 要 RemoteRpcDemoXinu kernel
python3 aice-pi-evolution/experiments/2026-05-20_xinu_remote_rpc/host_rpc_demo.py

# Diners (Python script) — 要 DiningPhilosophersDistXinu kernel
python3 aice-pi-evolution/experiments/2026-05-20_xinu_remote_rpc/host_diners.py

# Diners + dynamic compile (Python script)
python3 aice-pi-evolution/experiments/2026-05-20_xinu_remote_rpc/host_diners_dynamic.py

# ★ Pure-AIPL host orchestrator (Python script なし、AIPL のみ)
python3 src/python-aipl/aipl_main.py \
    aice-pi-evolution/experiments/2026-05-20_xinu_remote_rpc/host_diners_dynamic.aipl \
    --timeout 150 --idle-ms 30000
```

### 4.4 進化計算
```sh
cd /Users/kodamay/ocaml-app/abclcp-project
mkdir -p out
export AIPL_AI_PROVIDER=gemini  # GEMINI_API_KEY が設定されていること

# RemoteRPC (seed=6, gen=20)
python3 -u src/python-aipl/aipl_main.py \
    aice-pi-evolution/experiments/2026-05-20_xinu_remote_rpc/AIPL_XinuRazPi_RemoteRPC.aipl \
    --timeout 1800 --idle-ms 600000

# Xinu kernel (seed=6, gen=20)
python3 -u src/python-aipl/aipl_main.py \
    aice-pi-evolution/experiments/2026-05-21_xinu_kernel_evolution/Xinu_KernelEvolution_Round1.aipl \
    --timeout 1800 --idle-ms 600000
```

注意: `.aipl` を `.aice` から再生成する場合は手順全部やる必要あり:
```sh
cd /Users/kodamay/ocaml-app/abclcp-project/aice-evolution-v2
python3 -m src.cli --no-run --abcl \
    -o ../aice-pi-evolution/experiments/2026-05-21_xinu_kernel_evolution/ \
    ../aice-pi-evolution/experiments/2026-05-21_xinu_kernel_evolution/Xinu_KernelEvolution_Round1.aice
# →  .aipl が出る → .aipl にリネーム → use_ai 0→1 patch (python regex)
cd ..
mv aice-pi-evolution/experiments/2026-05-21_xinu_kernel_evolution/Xinu_KernelEvolution_Round1.aipl \
   aice-pi-evolution/experiments/2026-05-21_xinu_kernel_evolution/Xinu_KernelEvolution_Round1.aipl
python3 -c "
import re
p='aice-pi-evolution/experiments/2026-05-21_xinu_kernel_evolution/Xinu_KernelEvolution_Round1.aipl'
s=open(p,encoding='utf-8').read()
s=re.sub(r'(new Reviewer\\(\\\"R_[A-Za-z]+\\\", \\\".*?\\\", )0(, [0-9.]+, util, digits\\))',
         r'\\g<1>1\\g<2>', s, flags=re.DOTALL)
open(p,'w',encoding='utf-8').write(s)
"
```

## 5. 残作業 — 次回の選択肢

### 5A. Xinu kernel evolution Round 1 残 phase (10/16)

| Phase | LOC 想定 | 備考 |
|---|---|---|
| M1 BuddyAllocator | 400-600 | freelist → buddy。AIPL の F4 leak smoke が回帰確認 |
| M2 SlabCache | 200-300 | M1 上に slab。actor object_t / mailbox_t を fixed-size pool で |
| M3 DemandPaging | 600+ | MMU 必要 → A1 後 |
| N1f FixSmc91c111 | 大 | 既存 smc91c111 driver の partial 動作を完成 (TCP send/recv) |
| N2 ZeroCopyBuffers | 中 | network buffer chain |
| N3 SocketSyscalls | 中 | BSD-like socket() API |
| A1 ArmRpi3Port | 大 | versatilepb → rpi3 platform |
| A2 MmuBringup | 中 | A1 後、MMU on + user/kernel split |
| A3 RealRpiGPIO | 小 | A1 後、実機 RPi 必要 |
| Sec2 CapTokens | 中 | A2 + N3 後、syscall に token gate |

最も波及範囲小さく成果が出るのは: **N1f → N3** か **M1 → M2** か **A1**。

### 5B. 進化計算の再走

Gemini API timeout 対策:
- seed を 3 に、gen を 5 に縮小して短時間で完走させる
- もしくは reviewers を 2 に減らして per-individual cost を半減
- 別 provider (OpenAI / Anthropic) に切り替え

### 5C. ImplCost — LOC + binary size まとめ

Round 1 各 phase でどれくらい LOC が増えたか + xinu.elf サイズ推移を
測って `.aice` の ImplCost task の数値を埋める。観察のみ、簡単。

### 5D. ホストプログラム拡張

`host_diners_dynamic.aipl` のパターンを使って:
- 他の Xinu actor 駆動 program (例: framebuffer drawer をホスト指示で)
- 多 actor cluster (`tcp_*` で複数 Xinu に接続して分散 actor)

## 6. 既知の落とし穴 (次回ハマらないように)

1. **`now obj.method()` は c_translator (--xinu) に未実装** — `send sender.X(...)` callback パターンで代替
2. **`var x = -1;` は AIPL parser エラー** — 負数リテラル初期化不可、`var x = 0;` 等で代用
3. **`call` / `int` / `now self.X` (Py-I 再帰) は予約語/未対応** — リネーム or インライン化
4. **`nil` リテラルは Py-I で未対応** — `0` で代用
5. **QEMU `-serial tcp:` は single-client** — 複数 thread で使うときは shared socket + thread.Lock (Python) または coordinator actor (AIPL)
6. **In-kernel VM (aoutRun) は逐次のみ** — class/actor/send は未対応。dynamic load した program は孤立 (kernel actor system と共有しない)
7. **Gemini lineage.json corrupt** — `score:None0,` のような serialization bug。`re.sub(r'None\d*', 'null', s)` で recover
8. **Xinu DEBUG マクロ** — Makefile の `DEBUG=` は C preprocessor の `-DDEBUG` には *ならない* (CFLAGS に append されるだけ)。`#ifndef DEBUG` ガードは常に通る
9. **`xinu-raz/apps/abcl_program.c` は generated file** — 毎回 cp で上書きされる。commit 対象外
10. **`-fstack-protector-strong` が要 `__stack_chk_guard / __stack_chk_fail`** — `system/stack_canary.c` で提供

## 7. リモートリポジトリ状態 (2026-05-21 push 済)

| Repo | Remote | Branch / HEAD |
|---|---|---|
| abclcp-project | `github.com/yaskodama/aios-claude` | `main` @ `12255db` |
| xinu-raz | `github.com/yaskodama/xinu-rpi` | `master` @ `0baaa26` |

## 8. 次回開始時のチェックリスト

```sh
# (1) リポジトリ最新化
cd /Users/kodamay/ocaml-app/abclcp-project && git pull
cd /Users/kodamay/projects/xinu-raz/xinu     && git pull

# (2) ビルド (両方とも)
cd /Users/kodamay/ocaml-app/abclcp-project && dune build
cd /Users/kodamay/projects/xinu-raz/xinu/compile && \
    make PLATFORM=arm-qemu COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi- clean && \
    make PLATFORM=arm-qemu COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi- DEBUG=-DAIPL_AUTOSTART

# (3) Regression gate
cd /Users/kodamay/ocaml-app/abclcp-project
bash aice-pi-evolution/experiments/2026-05-20_xinu_razpi_aipl/_smoke_backwardcompat.sh
bash aice-pi-evolution/experiments/2026-05-20_xinu_razpi_aipl/_smoke_p2.sh
bash aice-pi-evolution/experiments/2026-05-21_xinu_kernel_evolution/_smoke_s3_deadline.sh

# 全部 PASS なら → 残作業 (M1/N1f/A1/etc) から好きなものを選んで着手
```

Happy hacking 次回もよろしく。
