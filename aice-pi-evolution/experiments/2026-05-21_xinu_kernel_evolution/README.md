# Xinu_KernelEvolution_Round1

Embedded Xinu **kernel 本体** を進化させる Round 1。AIPL を host とした
`AIPL_XinuRazPi_Round1.aice` (2026-05-20) の兄弟ファイル — あちらは
AIPL を変数、Xinu を定数として扱う。こちらは逆で、AIPL を workload
として固定し、Xinu kernel の subsystem を 5 軸で進化させる。

## ファイル

- `Xinu_KernelEvolution_Round1.aice` — 設計書 (v2 C 風 DSL, parser 通過済)
- `Xinu_KernelEvolution_Round1.ga.json` — lower 結果 (18 tasks + 4 reviewers)
- 後続: `_smoke_*.sh`, `report/<phase>.md`, `Xinu_KernelEvolution_Round1.aipl`
  (MAP-Elites orchestrator) は実行時に生成

## 進化軸 (`aice-evolution-v2/schemas/xinu_kernel.schema.json`)

7 axes × 3〜6 value:

| axis | values | ordinal? |
|---|---|---|
| scheduler | round_robin / priority_static / priority_aging / mlfq / edf_soft / cfs_like | ✓ |
| memory_alloc | bump / freelist / buddy / slab / demand_paged / cow | ✓ |
| ipc_primitive | sem_mailbox / channel_typed / capability / tuple_space / actor_lockfree | – |
| isolation | none / user_kernel_split / mmu_per_process / capability_token / container_like | ✓ |
| arch_target | arm_versatilepb / arm_rpi3 / arm_rpi4 / x86_64 / riscv32 / multi_arch | – |
| power_mgmt | always_on / halt_idle / dvfs / deep_sleep | ✓ |
| concurrency_safety | critical_section / spinlock / lock_free / rcu / stm | ✓ |

12 coherence rules で意味のない組合せ (e.g. `arm_versatilepb` + `demand_paged`)
を排除。

## 13 phase + 2 cross-cutting

| dir | phase | dep |
|---|---|---|
| **S** scheduler | S1 PriorityAging / S2 MLFQ / S3 DeadlineHints / S4 IdlePower | baseline → S1 → S2 → S3、S4 並行 |
| **M** memory | M1 Buddy / M2 Slab / M3 DemandPaging | baseline → M1 → M2 → M3 (A1 必要) |
| **N** network | N1f FixSmc91c111 / N2 ZeroCopy / N3 SocketSyscalls | baseline → N1f → N2 → N3 |
| **A** architecture | A1 ArmRpi3Port / A2 MmuBringup / A3 RealRpiGPIO | S1+M1 → A1 → A2/A3 |
| **Sec** security | Sec1 Canaries / Sec2 CapTokens / Sec3 MeasuredBoot | Sec1 並行 / A2+N3 → Sec2 / A1 → Sec3 |
| 横断 | R_AiplBackwardCompat / ImplCost | 毎 phase |

## レビュアー (Gemini)

- **R_KernelSafety** (weight 0.30) — 空間分離 + 安全な並行 + lazy commit
- **R_PerformanceLatency** (0.25) — actor message p99, IRQ→thread dispatch
- **R_ImplementabilityArm** (0.25) — 実 RPi3/4 + arm-qemu の両建て実装容易性
- **R_AiplBackwardCompat** (0.20) — AIPL Round 1 + RemoteRPC smoke を壊さない確率

## 検証ゲート (各 phase 完了時)

1. `xinu.elf` が build (arm-qemu)、必要なら arm-rpi3 も
2. `qemu-system-arm -M versatilepb` で boot → `xsh$` プロンプト到達
3. AIPL Round 1 の 17 smoke (R1/P1-P4/F1-F4/G1-G3/G5/N1部分) + RemoteRPC の
   `host_rpc_demo.py` (9/9) + `host_diners.py` (50 meals) + `_smoke_backwardcompat.sh`
   (Gate1 82/82) が **全 PASS**
4. 該当 phase の `acceptance` 列の assertion を満たす

## 進化計算を回す

```sh
# (1) .aice → .ga.json (parse 確認)
cd aice-evolution-v2
python3 -m src.cli --no-run \
    -o ../aice-pi-evolution/experiments/2026-05-21_xinu_kernel_evolution/ \
    ../aice-pi-evolution/experiments/2026-05-21_xinu_kernel_evolution/Xinu_KernelEvolution_Round1.aice

# (2) .aipl (MAP-Elites orchestrator) を生成
python3 -m src.cli --no-run --abcl \
    -o ../aice-pi-evolution/experiments/2026-05-21_xinu_kernel_evolution/ \
    ../aice-pi-evolution/experiments/2026-05-21_xinu_kernel_evolution/Xinu_KernelEvolution_Round1.aice

# (3) .aipl -> .aipl リネーム + use_ai=0 → 1 patch
cd ..
mv aice-pi-evolution/experiments/2026-05-21_xinu_kernel_evolution/Xinu_KernelEvolution_Round1.aipl \
   aice-pi-evolution/experiments/2026-05-21_xinu_kernel_evolution/Xinu_KernelEvolution_Round1.aipl
python3 -c "
import re
p='aice-pi-evolution/experiments/2026-05-21_xinu_kernel_evolution/Xinu_KernelEvolution_Round1.aipl'
s=open(p,encoding='utf-8').read()
s=re.sub(r'(new Reviewer\(.*?, .*?, )0(, [0-9.]+, util, digits\))', r'\g<1>1\g<2>', s, flags=re.DOTALL)
open(p,'w',encoding='utf-8').write(s)
"

# (4) Gemini で進化計算実行 (~30 分、4 reviewers x 13 tasks x 26 individuals ≈ 1400 LLM calls)
mkdir -p out
AIPL_AI_PROVIDER=gemini python3 -u src/python-aipl/aipl_main.py \
    aice-pi-evolution/experiments/2026-05-21_xinu_kernel_evolution/Xinu_KernelEvolution_Round1.aipl \
    --timeout 1800 --idle-ms 600000

# (5) 結果は out/Xinu_KernelEvolution_Round1.aipl_lineage.json に
```

## 既存資産との関係

- AIPL Round 1 が確立した 17 smoke + RemoteRPC の `host_rpc_demo.py` /
  `host_diners.py` は **不変条件として保持**。kernel 変更で壊れたら phase
  ロールバック。
- `abclcp-project/src/*` (aipl2c) は変更ゼロ原則。kernel ABI が
  動いた場合のみ追従。
- 外部リポ `xinu-raz` (`/Users/kodamay/projects/xinu-raz/xinu`) が
  進化対象本体。コミットは apps/system/device/include の subdir 別
  にバンドル。
