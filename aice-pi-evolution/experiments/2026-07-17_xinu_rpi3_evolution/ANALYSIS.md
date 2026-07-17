# rpi3 設計空間 GA — 予測 vs 実機実測 (2026-07-17)

この Round の独自価値は、レビュアー rubric を**このセッションで得た実機実測**に
基づいて書いたこと。ゆえに GA の champion を「実測で分かっている事実」と
突き合わせられる。以下がその照合。

## GA 完走結果

- seed=4 / gen=10、Gemini レビュアー 4 本 (gemini-2.5-flash-lite)、14 個体。
- MAP-Elites セル (smp_model 軸):

| smp_model | best score | n | 内訳 |
|---|---|---|---|
| **worker_pool** | **0.6221** (champion I13) | 9 | sched=round_robin conc=lock_free |
| full_smp | 0.3968 | 5 | sched=mlfq conc=lock_free |
| single_core | (出現せず) | 0 | — |

**champion I13 (0.622)** の 8 軸:
`worker_pool / lock_free / arm_rpi3 / dvfs / slab / round_robin / capability(ipc) / mmu_per_process(isolation)`

## 照合: GA 予測 vs 実機実測

### ✅ 一致した (GA の信頼できるシグナル)

| 軸 | GA champion | 実機実測 | 判定 |
|---|---|---|---|
| **smp_model** | worker_pool (0.62 > full_smp 0.40) | worker_pool を実装し dining ×3.99 / nqueens ×3.66 実証 | **一致**。GA の見出しは実測が裏付ける |
| **concurrency_safety** | lock_free (12/14 個体) | volatile + dsb で成立 (D-cache OFF、実機 SCTLR C=0) | **一致** |
| **arch_target** | arm_rpi3 (12/14) | 実機は BCM2837 Cortex-A53 | **一致** |
| power_mgmt | dvfs (9/14) | firmware がクロック変動 (2.33比)、DVFS 制御は妥当な方向 | 概ね一致 |

**worker_pool > full_smp** は rpi5 Round (0.507 vs 0.371) に続く再現であり、
かつ rpi3 では**実機実測がこれを裏付けた**。設計空間 GA の「方向性」は信頼できる。

### ❌ アーティファクト (実測と食い違う = 要人手フィルタ)

| 軸 | GA champion | 実測が示す正解 | 問題 |
|---|---|---|---|
| **isolation** | mmu_per_process (全 14 個体) | none / user_kernel_split (flat identity map を壊さない) | シード増殖アーティファクト。rubric は減点したが全個体に固着 |
| **ipc_primitive** | capability / tuple_space (12/14) | sem_mailbox (AIPL mailbox 保護) | 実測では AIPL/JIT/メッシュ全滅リスク。rubric で 0.0 にしたが champion に残存 |

これは rpi5 kernel evolution でも見た**「小規模 GA は方向性まで信頼、全遺伝子詳細は
アーティファクト混入」**パターンの再現。champion の主軸 (smp_model) は信頼できるが、
副軸 (isolation/ipc) は人手で実測に合わせて上書きすべき。

### ★ 最大の発見: 支配変数が schema に無い

このセッションの実測で最も効いた変数は **D-cache** (単一コア 8.8 倍、メモリ律速の
スケール可否を決める) だった。しかし `xinu_kernel.schema.json` の 8 軸に
**キャッシュ構成の軸は存在しない**。D-cache は memory_alloc / power_mgmt を通じて
間接的にしか表現されず、GA は**経験的に最重要と判明した変数を構造的に探索できない**。

→ 具体的提言: schema に `cache_policy` 軸 (dcache_off / dcache_on_bounce_usb /
dcache_on_no_dma 等) を追加すべき。そうすれば GA が D-cache のトレードオフ
(8.8倍 vs USB DMA の壁) を直接探索できる。

## 結論: 設計空間 GA の価値と限界

- **価値**: 「worker_pool を磨け、full_smp に走るな」という方向性を、実機実測の
  前に(そして独立に)正しく示す。rpi3/rpi5 で再現し、rpi3 では実測が裏付けた。
- **限界1**: 全遺伝子の詳細 (isolation/ipc) はアーティファクト混入。主軸のみ信頼。
- **限界2**: 経験的な支配変数 (D-cache) が schema に無ければ、GA はそれを見つけられない。
  実機実測が GA を補完する不可欠な役割を持つ。

これが「設計空間 GA の予測 vs 実機実測」の答え: **GA は方向を、実測は真実を語る。**

## 再現手順

```
# 生成
cd aice-evolution-v2 && python3 -m src.cli --no-run --abcl \
  -o ../aice-pi-evolution/experiments/2026-07-17_xinu_rpi3_evolution/ \
  ../aice-pi-evolution/experiments/2026-07-17_xinu_rpi3_evolution/Xinu_RPi3_InternalEvolution.aice
# use_ai パッチ (第3引数 0→1)
perl -i -pe 's/, 0, (0\.(?:28|24)), util, digits\)/, 1, $1, util, digits)/g' *.abcl
# 実行 (数分)
AIPL_AI_PROVIDER=gemini AIPL_GEMINI_MODEL=gemini-2.5-flash-lite \
  ABCL_AI_FALLBACK_MODELS=gemini-2.0-flash-lite,gemini-2.5-flash \
  python3 -u src/python-aipl/aipl_main.py <abcl> --timeout 1800 --idle-ms 600000
# 解析
python3 analyze_lineage.py lineage.json
```

★落とし穴: `out/` はリポジトリルート直下の**共有**出力ディレクトリ (他実験の
lineage も入る、git 追跡下)。lineage は実験ディレクトリに cp して保全し、
`out/` は消さない。
