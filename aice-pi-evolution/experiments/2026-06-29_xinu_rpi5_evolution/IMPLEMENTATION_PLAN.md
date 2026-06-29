# rpi5 worker_pool 強化 実装計画 (2026-06-29)

設計空間GA Round の champion (`I14`, score 0.507, **smp_model=worker_pool**) を
`~/projects/xinu-rpi5` の実カーネルへ手実装するための、ファイル単位の計画。

## GA が正当化したこと / しないこと

GA の信頼できるシグナル（小規模run=14個体ゆえ方向性まで）:

| 採用する (高信頼) | 根拠 |
|---|---|
| **worker_pool を磨く（full_smp 全面書換はしない）** | worker_pool 0.507 > full_smp 0.371。full_smp は A76 実装コスト＋core0専有のライブ機能(WM/SDIO/AODV)破壊リスクが上限メリットを上回る |
| arch=arm_rpi5 / ipc=sem_mailbox / isolation=flat 据置 | ライブ機能(メッシュ/WM/JIT/VM)を壊さない |
| memory=**buddy**, power=**dvfs** + halt_idle | 高評価かつ実コードにフック有り |

| 採用しない (アーティファクト) | 理由 |
|---|---|
| concurrency_safety=**stm** | 12/14 と支配的だがシード増殖。rubric はむしろ減点。ベアメタルXinuにSTMは過大 |
| isolation=**capability_token** | 13/14 だが同上。flat identity map + demand-paging を壊すと WM/mesh の MMIO マップが危険 |

## 前提（実コードマップ）

- SMP: `system/smp.c` — core0=OS / core1-3=WFEワーカー。`smp_parallel_sum(smp_range_fn fn, long n, int ncores)`(L147-189) が cores1..n-1 に work を post、chunk0 は core0 inline。同期は volatile 配列 `smp_job_*[]` + `dsb_sev()`(L39)。`smp_worker_loop`(L76-90)。起動=PSCI CPU_ON(L50-63)、コア識別=MPIDR Aff1 `smp_core_id()`(L66-74)。
- アクター: `system/actor.c actor_message()`(L53-80) は**同期**(field[0]にbump/add/set/get/reset)。8体上限(`include/actor.h`)。JIT 経路 `cc/cc.c cc_actor_send()`(L152)。HTTP `/send`(tcp_server.c L572)・`/actor/send`(L800)。GC `cc_actor_gc()`(L696)。
- メモリ: `mem/memory.c` first-fit `getmem/freemem`(L32/L63)、`memlist_head`(L9)。`mem/kmalloc.c`(magic 0xC0FFEE…, L6) per-block 32B header。heap `mem_init`、`HEAP_END=0x40000000`(main.c L597)。demand-paging `system/mmu.c vm_fault()`(L194)。
- idle/timer/mbox: NULLPROC=boot/shell文脈、ready空で `proc_resched()` 戻り(proc.c L178)。timer=ARM generic CNTP 100Hz(`device/timer/timer.c timer_init` L58、`timer_tick_hook()`)。**firmware mailbox=`device/mbox/mbox.c mbox_call()`(channel8 property tag, MBOX_BASE 0x107C00B880)**、既に WiFi クロック設定(wifi.c L383)・FB確保(video.c L77)で使用実績。
- ビルド/メッシュ: `make pi5` → `compile/kernel_2712.img`。メッシュ(`wifi.c wifi_adhoc/keep_eth/wifi_net_poll`、`tcp_server.c /wifi-adhoc + wifi_adhoc_poll_pending`)は kernel_2712.img に linked=**再焼きで温存**。

> ★要確認: メモリ `project_xinu_rpi5_multicore_actors`(焼済 add356dc) が「par_safe クラスのアクターメッセージを smp_parallel_sum で分散」を既に実装済みと示唆。本計画 #1 着手前に現 HEAD に par_safe 実装が既にあるか grep 確認し、二重実装を避ける。

---

## 実装項目（依存順）

### #1 par_safe アクターのマルチコア分散（worker_pool の本丸）
**狙い**: 計算専用(WAIT/描画なし)アクターの一括処理を core1-3 に分散。
**変更**:
- `system/smp.c`: `smp_parallel_sum` を一般化した `void smp_parallel_for(smp_range_fn fn, long n, int ncores)`（戻り値集約なし版）を追加。既存 sum は薄いラッパに。
- `include/actor.h` / `system/actor.c`: アクターに `par_safe` フラグ追加（WAIT/描画メソッドを持たない＝純計算）。`actor_message_batch(ids[], methods[], args[], n)` を新設し、par_safe な範囲を `smp_parallel_for` で core 分散、非par_safe は従来 core0 同期パス。
- `cc/cc.c`: JIT 経路 `cc_actor_send` のバッチ版を追加し、AIPL `spawn` 連発＋compute を par_safe 判定で分散。
**検証**: par_safe アクター群(例: 各自で素数カウント)を N体 spawn→4コア並列実行で約3倍、描画アクターは core0 維持で映像不変。`/actor/send` の単発は順序保証維持。
**リスク**: 描画/WAIT を持つアクターを誤って par_safe 判定しない（保守的デフォルト=par_safe 0）。

### #2 buddy allocator（per-core キャッシュは #1 後）
**狙い**: first-fit の断片化解消＋O(log) alloc。
**変更**:
- `mem/buddy.c`(新) + `include/buddy.h`: heap 領域上に 2^k ブロックの buddy。`buddy_alloc/buddy_free`。
- `mem/kmalloc.c`: `kmalloc/kfree` を buddy 経由へ（magic/二重free検出・live統計は維持）。`getmem/freemem` は互換 fallback として残す。
- per-core magazine（core1-3 が par_safe アクターで alloc する場合のみ）。当面 core0 集中なら後回しで可。
**検証**: alloc/free が first-fit より速い・leak/二重free検出維持・demand-paging VM(`vmstat`/`vmdemand`)と共存。
**リスク**: heap レイアウト変更で起動初期 alloc が壊れない（mem_init 後に buddy_init、それ以前は bump）。

### #3 DVFS（firmware mailbox）
**狙い**: 負荷に応じ A76 クロックを変動、idle で省電力。
**変更**:
- `device/mbox/dvfs.c`(新): `mbox_call()` + property tag **0x00038002 SET_CLOCK_RATE**(clock id 3=ARM) / 0x00030002 GET / 0x00030004 GET_MAX。`dvfs_set_arm_hz(hz)` / `dvfs_max_hz()`。
- `device/timer/timer.c timer_tick_hook`: 簡易ガバナ。ready-list 深さ＋worker busy で hi/lo 2段（または線形）スケール。idle 継続で min へ。
**検証**: 高負荷で max、idle で低下（消費/温度）。DVFS 中もメッシュ(AODV)・WM・/fb が安定（mailbox 競合に注意=video/wifi の mbox_call とシリアライズ）。
**リスク**: mailbox は単一資源。DVFS 呼出を低頻度(例 100ms)に制限し WiFi/FB と衝突させない。

### #4 halt_idle（WFI）
**狙い**: 本当に何もない時だけ core0 を WFI（workers は既に WFE=低電力）。
**変更**:
- core0 メインポーリングループ（main.c の genet_rx_tick / wifi_net_poll / gc_drive を回す箇所）で、数イテレーション連続で「処理なし & I/O保留なし」なら `wfi`。timer 100Hz が ≤10ms で必ず復帰。
- #3 と連動: idle 突入時に DVFS min。
**検証**: idle で消費低下・タイマ/割込で即復帰・**HTTP/メッシュ応答が遅延しない**（ポーリング停止しすぎない＝WFI は I/O 静穏時のみ）。
**リスク**: ポーリング駆動の HTTP/mesh を WFI で止めると応答が死ぬ。保守的に「I/O 完全静穏かつ ready 空」のみ WFI。

---

## ビルド & 実機投入（再焼き=rpi5のみ・最後にまとめて）

1. 上記を `~/projects/xinu-rpi5` に実装 → `make pi5` → `compile/kernel_2712.img`。
2. ★メッシュ版コード(poll/keep_eth)は linked のまま＝温存。bench ルート(#task5)も同時に入れるなら一緒に。
3. 投入: rpi5 電源OFF → SD を Mac へ → `cp compile/kernel_2712.img /Volumes/bootfs/`（**config.txt 厳禁・`make install_pi5` 厳禁**）→ eject → コールドブート。
4. 再投入でライブメッシュは消える → rpi3アンカー→順次再形成（[[project_xinu_mesh_and_control_center]] 手順）。
5. 実測: `/smp-bench?n=N`（par_safe分散後の素数/アクター並列）・DVFS時の安定性・idle消費。

## 未確定（ユーザ確認したい点）
- #1 の par_safe 既存実装(add356dc)との関係（再実装 vs 拡張）。
- DVFS ガバナの段数（2段 hi/lo で十分か、線形か）。
- 再焼きのタイミング（実装完了後に #task5 bench と同時 or 個別）。
