# AIPL × Embedded Xinu × Raspberry Pi 5

新規プラットフォーム **`arm-rpi5`** (BCM2712 / Cortex-A76 / AArch64)
への Xinu 移植 Round 1.

## 経緯

既存 `xinu-raz` (arm-qemu / arm-rpi 32-bit) は十分稼働しているが、
Pi 5 は AArch64 only + 新 MMIO 配置 + RP1 I/O hub と相違が大きいため、
**別 git repo `yaskodama/xinu-rpi5`** に分離して進める。Boot 方式は
[radlyeel/leex](https://github.com/radlyeel/leex) の AArch64 Pi 4 stub
を Pi 5 向けに調整する形で踏襲。

## ハードウェア対照

|              | Pi 4 (leex baseline) | **Pi 5 (this round)** |
|--------------|----------------------|-----------------------|
| SoC          | BCM2711              | **BCM2712**           |
| Cores        | Cortex-A72 ×4        | **Cortex-A76 ×4**     |
| MMIO base    | 0xFE000000           | **0x107C000000**      |
| I/O hub      | direct on SoC        | **RP1 (PCIe 別チップ)** |
| Firmware img | kernel8.img          | **kernel_2712.img**   |
| IRQ          | GIC-400              | GIC-400 + RP1 IRQ     |
| GPIO         | on-SoC               | via RP1               |

## Round 1 設計 (40 assertion、12 phase / 6 軸)

| 方向 | phase | 概要 |
|---|---|---|
| **B** Boot | B0-B2 | aarch64 toolchain / leex 由来 boot stub / kernel_2712.img |
| **U** UART | U0-U1 | PL011 UART0 (header pin 8/10) / kprintf |
| **M** Memory | M0-M1 | MMU flat ID map / kernel heap |
| **S** Scheduler | S0-S1 | AArch64 ctxsw / GIC + generic timer |
| **X** Userland | X0-X1 | xsh on Pi5 / AIPL hello |
| **N** Network (stretch) | N0-N1 | RP1 discover / VC mailbox FB |
| 横断 | R_LegacyPlatformsUnchanged, ImplCost | 既存 arm-qemu / arm-rpi3 smoke 不変 |

## 進化計算 reviewer (Gemini)

| reviewer | weight |
|---|---|
| R_BootBringup | 0.30 |
| R_AArch64SchedulerImpl | 0.25 |
| R_Pi5HardwareReality | 0.25 |
| R_LegacyBackwardCompat | 0.20 |

## ファイル

| | |
|---|---|
| `AIPL_XinuRPi5_Round1.aice` | 設計書 |
| `AIPL_XinuRPi5_Round1.ga.json` | lowered IR (mock evaluator) |
| (next) `AIPL_XinuRPi5_Round1_ai.ga.json` | AI evaluator IR (gen/seed 抑え) |
| (next) `AIPL_XinuRPi5_Round1.aipl` | MAP-Elites orchestrator (`--abcl` で生成 + `use_ai=1` patch) |

## 次のアクション

1. **GitHub repo 作成**: `gh repo create yaskodama/xinu-rpi5 --public --description "Embedded Xinu port for Raspberry Pi 5 (BCM2712, AArch64). Bootstrapped from xinu-raz/arm-qemu + leex-style AArch64 boot."`
2. ローカル clone: `git clone yaskodama/xinu-rpi5 /Users/kodamay/projects/xinu-rpi5`
3. `xinu-raz` から必要なディレクトリ (system/, include/, shell/, mem/, network/, apps/, lib/) を選択的にコピー
4. `compile/platforms/arm-rpi5/` を新規 (loader.S / link.ld / platformVars / config.txt)
5. `arch/aarch64/` を新規 (start.S / ctxsw.S / exception_vectors.S / mmu.c)
6. **B0 → B1 → B2 → U0 → U1 → M0 → M1 → S0 → S1 → X0 → X1** の implementation_order で着手

## 実 hardware 必要物

- Raspberry Pi 5 (4GB or 8GB)
- microSD card (16GB+, FAT32 bootfs)
- USB-Serial UART cable (FTDI 等、GPIO14 TXD / GPIO15 RXD / GND)
- ホスト Mac で `screen /dev/tty.usbserial-xxxx 115200`

QEMU の Pi 5 公式サポートが上流に来るまでは **smoke は実機 USB-Serial 経由のみ**。
arm-qemu / arm-rpi3 は regression anchor として継続。

## 不変条件 (各 phase 完了時 PASS 必須)

arm-qemu / arm-rpi3 の **Round 2 累積 smoke** が全部 PASS:
- backwardcompat Gate1 88/88, Gate2 75/88
- N1 TCP echo 4/4
- host_rpc_demo 9/9
- Xinu 直接 HTTP
- diners 3 variants (Python / pure-AIPL / bootstrap)
- kernel-evo S1-S4/Sec1 + memfs/make
