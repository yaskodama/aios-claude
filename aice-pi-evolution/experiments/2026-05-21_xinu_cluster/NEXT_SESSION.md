# NEXT_SESSION — 2026-05-21 終了時点のハンドオフ

最終更新: 2026-05-21 (本セッション終了時)
最終 commit: `b683529` (origin/main と完全同期)

## 0. 起動時にまずこれを読む

このセッションで進めたのは **3 つの独立した track + 1 つの cross-cutting 修正**：

1. **N3 multi-Pi cluster Phase A — host 側完成** (`4a509c5`)
2. **JS-B/JS-N HM port** — OCaml `infer.ml` パリティ (`a1a9394`)
3. **Py-I HM 修正** — 同じ緩和規則を Python 側にも適用 (`84a2a40`)
4. 雑修正: dining philosophers meals 3→10 (`bcab5ed`)

## 1. 今セッションで完了したこと

### 1-A. dining philosophers meals 3→10 (`bcab5ed`)
- `abclc/DiningPhilosophersDistXinu.aipl`: `meals = 10`
- `aice-pi-evolution/experiments/2026-05-20_xinu_remote_rpc/host_diners.py`:
  - `MEALS_PER_PHILOSOPHER` を env 変数 `MEALS` で上書き可 (default 10)
  - `DINERS_TIMEOUT` env で join timeout 上書き可 (default 300s)
- 完食合計 3 PC × 10 + 2 Xinu × 10 = **50 食 deadlock-free**

### 1-B. JS-B / JS-N の完全 HM 化 (`a1a9394`)
OCaml `src/infer.ml` パリティの完全 HM に書き換え。
- 新規 `src/browser-abcl/src/types.js` (~480 LOC) — tvar / repr / unify / generalize / instantiate / scheme / record-rowpoly / refinement / レジストリ
- 新規 `src/browser-abcl/src/infer.js` (~580 LOC) — 2 phase walker (preinferAllClasses → checkProgram) / 効果収集
- 既存 `src/browser-abcl/src/typecheck.js` を 691 → 30 行のファサードに置換
- 新規 `src/browser-abcl/src/_test_types.mjs` (24 unit test, 全 PASS)

**緩和規則 2 件** (重要 — `feedback_js_hm_port.md` に詳細):
- sentinel widening: 例 `var lowFork = ""; lowFork = lo;` (lo は param) のフィールド型を TAny に
- construct-then-init idiom: `new C()` を 0 引数で呼ぶときは init の arity check を skip

検証: nextgen 14/14 + lww 10/10 + browser-abcl 15/15 + node-aipl 14/14 + /api/typecheck 11/11 = **全 64 assertion green**.

### 1-C. N3 multi-Pi cluster Phase A — host 側 (`4a509c5`)

**完成した host 側**:
- `abclc/ClusterPingPongXinu.aipl` — Pinger / Ponger / Bootstrap
- `aice-pi-evolution/experiments/2026-05-21_xinu_cluster/`:
  - `cluster_bridge.py` — N node の host router (XSEND → SEND 書換)
  - `_test_bridge.py` — fake-QEMU で routing 7 assertion (no Xinu)
  - `_smoke_n3.sh` — aipl2c --check + --xinu + bridge test (5/5)
  - `README.md` — xinu-raz cluster.c の統合 runbook + sketch ~120 LOC

**deferred (重要)**: xinu-raz の `apps/abcl_xinu_cluster.c` (~120 LOC) と
`apps/abcl_xinu_rpc.c` への wrapper +2 行 + `apps/Makerules` +1 行。
並行プロジェクト `Xinu_KernelEvolution_Round1.aice` が xinu-raz の
system/mem/device/arch を高頻度に編集中なので、衝突回避のため待機.
**完了後の統合手順は `README.md` の "Integration runbook" 節に詳細記載 —
30 分作業**.

### 1-D. Py-I HM 修正 (`84a2a40`)

JS でやった同じ緩和を Python 側 (`src/python-aipl/aipl_inference.py`) にも:
1. `_parse_annotation` を case-insensitive (`"int"` 等 lowercase 注釈が
   `TCon("int")` という bogus class type を作って unify 失敗していたバグ)
2. `_infer_binop` で `+` を独立 case にして Str+Int → Str
3. unknown var/func/actor を `[unbound]` でなく fresh tvar で gradual
4. Sentinel widening — Assign で LHS と RHS が異なる concrete TCon なら field を T_DYN

副次効果: `_smoke_test.sh` の pre-existing typo (`abcl_main.py` → `aipl_main.py`) も修正。

成果: HM clean度 25/70 → **61/70 (87%)**.残る 9 件はすべて意図的負例
(Typecheck/Transient/MethodPatch/Records/disjoint_rejected).

## 2. 5 runtime × HM パリティ最終確認 (2026-05-21 終了時)

| Runtime | HM クリーン | 検証 |
|---------|-------------|------|
| **OCaml (`infer.ml`)** | ✅ 85/85 abclc native | `aipl2c --check` |
| **JS-O** (= OCaml gateway) | ✅ 85/85 (上と同 engine) | |
| **JS-B / JS-N** (`types.js + infer.js`) | ✅ 11/11 browser-abcl | `a1a9394` |
| **Py-I** (`aipl_inference.py`) | ✅ 61/70 (残 9 は意図的負例) | `84a2a40` |
| **C 9 backends** (POSIX/Xinu/Python/Pony/Erlang/Go/Prolog/LLVM/OpenMP) | ✅ 0 type-fail × 9 | 共通 OCaml HM |

**型推論レイヤーは全 runtime / 全 backend で OCaml `infer.ml` パリティの HM クリーン状態に揃った**.

## 3. 次セッションで最初にやることの候補

### 候補 A: N3 cluster.c を land (xinu-raz 並行作業の状況次第)

**前提**: `Xinu_KernelEvolution_Round1.aice` の進捗を確認.
彼らは `system/` `mem/` `device/` `arch/` を編集中.
**apps/** は彼らの `file_impact.untouched` に明記されている**ので、
そこに新規ファイル `apps/abcl_xinu_cluster.c` を追加するのは安全**.

確認コマンド:
```sh
cd /Users/kodamay/projects/xinu-raz/xinu
git log --oneline -10                  # kernel evo 側の commit を見る
git status                              # 編集中のファイルを見る
```

`apps/abcl_xinu_*.c` が編集中でなければ即 land 可:

```sh
# README.md の "Integration runbook" 節をそのまま実行
bash /Users/kodamay/ocaml-app/abclcp-project/aice-pi-evolution/experiments/2026-05-21_xinu_cluster/_smoke_n3.sh
# B1 が DEFERRED → 必要なら手動で 2-node QEMU 起動
```

統合 sketch (cluster.c の本体):
```c
// /Users/kodamay/projects/xinu-raz/xinu/apps/abcl_xinu_cluster.c
#include <kernel.h>
extern void abcl_uart1_puts(const char *s);   // +2 行 wrapper を rpc.c に
static int g_node_id = NODE_ID;               // -DNODE_ID=n at make time

value_t cluster_send(int n, value_t *a) {
    if (n < 3) return v_int(0);
    char line[128];
    snprintf(line, sizeof line, "XSEND %ld %ld %s %ld\n",
             a[0].i, a[1].i, a[2].s, n >= 4 ? a[3].i : 0);
    abcl_uart1_puts(line);
    return v_int(1);
}
value_t cluster_node_id(int n, value_t *a) { return v_int(g_node_id); }
value_t cluster_size(int n, value_t *a)    { return v_int(2); }
```

### 候補 B: N3 Phase B (actor migration via F1)
~270 LOC, 4 assertion.`README.md` の "Future phases" 節参照.

### 候補 C: ImplCost Round 1 まとめ
xinu-raz Round 1 の全 14 phase の LOC / binary size / smoke 時間
集計レポート.host 側で完結.

### 候補 D: Drone-sim Round 2 (browser-abcl)
JS HM port の実装検証にもなる.進化計算で次世代要素を決める.

## 4. 環境 / 起動コマンド (再掲)

### よく使う smoke
```sh
# JS-B/JS-N
node --test src/browser-abcl/src/_test_types.mjs       # 24/24
bash src/browser-abcl/_smoke_nextgen.sh                # 14/14
bash src/browser-abcl/_smoke_lww.sh                    # 10/10
bash src/browser-abcl/_smoke_test.sh                   # 15/15
bash src/node-aipl-server/_smoke_test.sh               # 14/14

# Py-I
bash src/python-aipl/_smoke_test.sh                    # 40/40 runtime
# HM cleanness 検査
for f in src/python-aipl/samples/*.aipl; do
  python3.13 src/python-aipl/aipl_main.py --infer "$f" 2>&1 | tail -1
done

# Xinu-raz Round 1 (smoke が動くものだけ — N1 等は QEMU/NIC 制約)
bash aice-pi-evolution/experiments/2026-05-20_xinu_razpi_aipl/_smoke_p1.sh   # 12/12
bash aice-pi-evolution/experiments/2026-05-20_xinu_razpi_aipl/_smoke_g3.sh   # 6/6
# 全リストは memory project_xinu_razpi_aipl.md 参照

# N3 cluster (本セッションの新規)
bash aice-pi-evolution/experiments/2026-05-21_xinu_cluster/_smoke_n3.sh      # 5/5
python3 aice-pi-evolution/experiments/2026-05-21_xinu_cluster/_test_bridge.py  # 7/7

# 分散哲学者
# (ターミナル A) QEMU 起動 (cd ocaml-app/abclcp-project)
dune build src/aipl2c.exe
./_build/default/src/aipl2c.exe abclc/DiningPhilosophersDistXinu.aipl \
    -o /tmp/dpd.c --xinu --max-msgs 0
cp /tmp/dpd.c /Users/kodamay/projects/xinu-raz/xinu/apps/abcl_program.c
( cd /Users/kodamay/projects/xinu-raz/xinu/compile && \
  make PLATFORM=arm-qemu \
       COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi- \
       DEBUG=-DAIPL_AUTOSTART )
qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
    -kernel /Users/kodamay/projects/xinu-raz/xinu/compile/xinu.elf \
    -nographic -serial mon:stdio \
    -serial tcp:127.0.0.1:5555,server=on,wait=off -no-reboot
# (ターミナル B)
cd aice-pi-evolution/experiments/2026-05-20_xinu_remote_rpc
python3 host_diners.py    # MEALS=20 etc で長くも回せる
```

## 5. リスクと注意点

### 5-A. xinu-raz は並行作業中 — 触らない
`Xinu_KernelEvolution_Round1.aice` が xinu-raz の以下を編集中:
- `system/resched.c, ksched.c, clkinit.c, clkint.c, mmu.c, socket.c, syscall.c`
- `mem/getmem.c, freemem.c, kmalloc.c`
- `device/smc91c111/*`
- `compile/platforms/arm-rpi3/*`
- `arch/arm/mmu_*.S`
- `include/socket.h`

彼らの `untouched`:
- `abclcp-project/src/*` (aipl2c)
- `abclcp-project/abclc/*Xinu.aipl`
- `browser-abcl / spreadsheet / drone-sim`

私の N3 cluster の `apps/abcl_xinu_cluster.c` は **彼らの primary scope の外** (apps/ は untouched 領域) なので land しても衝突しない.ただし `apps/Makerules` への 1 行追加だけは additive merge.

### 5-B. JS HM port の緩和規則は触らない
JS-B/JS-N の `infer.js` には 2 つの gradual escape (sentinel widening + construct-then-init) が入っている.これらは drone_simulator や spreadsheet を green に保つために必須.外すと多数 smoke が落ちる.詳細は `feedback_js_hm_port.md`.

### 5-C. Py-I HM の Z3 hook は有効化していない
`AIPL_REFINE_Z3=1` を立てると refinement subset check が z3 にシェルアウトする.この経路は CE-12 nextgen で動作確認済み.今回の修正は影響しない.

## 6. メモリ参照

セッション横断の状態保存先:
- [[project_xinu_razpi_aipl]] — Round 1 メイン track (R0 → F1/F2/F3/F4 + G1-3,5 + P1-4 + N1 部分)
- [[project_xinu_cluster]] — N3 multi-Pi cluster (このトラック)
- [[project_aipl_nextgen_parity]] — CE/DR 26-feature parity matrix
- [[feedback_js_hm_port]] — HM 緩和規則 (JS + Py-I 共通)
- [[reference_aice_pipeline]] — .aice → .ga.json → .aipl の三段パイプライン

## 7. 残タスク tracking

```
#8.  [pending]   [DEFERRED] N3-A1: cluster.c in xinu-raz (post kernel-evo)
#9.  [completed] N3-A2: ClusterPingPongXinu.aipl sample
#10. [completed] N3-A3: cluster_bridge.py host router
#11. [completed] N3-A4: _smoke_n3.sh gate
```

次セッションでは task #8 を確認、kernel evo の状況次第で land or 続き保留.
