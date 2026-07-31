# NEXT_SESSION — xinu-razpi-aipl Round 1

最終更新: 2026-05-20  (セッション終了時点のスナップショット)

## 1. 現在の到達点

Round 1 implementation_order の **R0 → R1 → P1 → P2 → P3 → P4 → G1 →
N1(partial) → F4 → F3** までが green。

| Phase | 状態 | コミット | 備考 |
|-------|------|----------|------|
| R0 typecheck 修復     | ✅ | `e80769e` + `5e46fa7` + `232b655` | 3 sample 全て type-check 通過 |
| R1 smoke 自動化       | ✅ | `a69308c` | `_smoke_r1.sh` 9/9 |
| P1 actor↔Xinu thread | ✅ | `f5d902c` | `_smoke_p1.sh` 12/12 |
| P2 priority 3 段      | ✅ | `c5f74ee` | `_smoke_p2.sh` 4/4 |
| P3 LockFreeMailbox    | ✅ | `31413b8` | MPSC CAS ring, `_smoke_p3.sh` 4/4 |
| P4 SchedVisualizer    | ✅ | `9ac1e64` / `68dd717` | `_smoke_p4.sh` 3/3 |
| G1 fb primitives      | ✅ | `55a88a1` / `40a20f6` | 8 builtin, `_smoke_g1.sh` 4/4 |
| N1 TCP/IP             | 🟡 | `763c7a7` / `26b0899` | net_init only, ARP 上流停止 |
| F4 Strings+Arrays     | ✅ | `36d5465` | AIPL 側 |
| **F3 Effect+Type parity** | 🟡 **未コミット** | (work in progress) | smoke 8/8 PASS, 詳細↓ |

## 2. 未コミットの変更 (セッションを越えて引き継ぐもの)

### 2-a. `src/c_translator.ml` — 修正済み、未コミット

```diff
   | Return None -> emitf "%sreturn;\n" ind
-  | Return (Some e) -> emitf "%sreturn /* %s */ 0;\n" ind (gen_expr ~ctx e)
+  | Return (Some e) ->
+      (* Xinu/POSIX method dispatch is void-typed (return value goes
+         elsewhere via send/reply), so we evaluate the expression for
+         side effects and discard it instead of emitting a typed
+         return that the C compiler would reject under -Wreturn-type. *)
+      emitf "%s(void)(%s); return;\n" ind (gen_expr ~ctx e)
```

理由: F3 の対象サンプル (`ce_int_refine`, `ce_where`, `dr_10` など) が
非 void method の `return expr;` を含むと、Xinu の `-Wreturn-type` で
ビルドが落ちていた.値そのものはこのコードパスでは使われない (struct
slot や send/reply で別経路) ので、`(void)(expr); return;` に書き換え
て副作用は評価しつつ戻り値を捨てる形にした.

### 2-b. `aice-pi-evolution/experiments/2026-05-20_xinu_razpi_aipl/_smoke_f3.sh` — 新規、未追跡

F3 acceptance (parity matrix Xinu 列 ≥ 6/13) を検証する smoke。
代表 8 sample (`ce_10/11/12/int_refine/where`, `dr_10/12/13`) を
順に aipl2c → Xinu build → QEMU で起動し、panic 無し +
dispatch marker observed をカウント.

実行結果 (この session 最終 run):

```
[ce_10] PASS (no-actor — codegen+link+boot clean)
[ce_11] PASS (actor dispatch, msgs=2)
[ce_12] PASS (no-actor — codegen+link+boot clean)
[ce_int_refine] PASS (actor dispatch, msgs=1)
[ce_where] PASS (actor dispatch, msgs=1)
[dr_10] PASS (actor dispatch, msgs=2)
[dr_12] PASS (actor dispatch, msgs=2)
[dr_13] PASS (actor dispatch, msgs=2)
========
PASS=8/8, parity matrix Xinu 列 8/13 (threshold 6 → ✅)
F3 ✅
```

## 3. 次セッション最初にやること

1. **F3 を 1 コミットでまとめる**:
   ```sh
   git add src/c_translator.ml \
           aice-pi-evolution/experiments/2026-05-20_xinu_razpi_aipl/_smoke_f3.sh
   git diff --cached --stat   # 確認
   git commit -m "xinu-razpi-aipl F3: effect/type parity — Xinu 列 8/13 (≥6 閾値超え)"
   ```
   コミット後、memory `project_xinu_razpi_aipl.md` の F3 行を 🟡 → ✅ に
   書き換え + コミット SHA を追記.

2. **再 smoke 確認 (sanity)**:
   ```sh
   bash aice-pi-evolution/experiments/2026-05-20_xinu_razpi_aipl/_smoke_f3.sh
   ```
   → 再現性チェック.PASS=8/8 のままなら ✅.

3. **次の phase 選択 — 推奨は G2 BitmapFontText**:
   - G1 が既に揃っており、G2 は依存的に直結
   - 8x16 ASCII bitmap font をリンクし `fb_text x y "hello" color`
     builtin を追加
   - acceptance: `_smoke_g2.sh` で "hello" + "AIPL" の 2 文字列描画
     を framebuffer dump で検証
   - 代替候補: F1 DistCheckpoint (F4 に依存、actor state を hex dump
     して replay)、または G4 RealPiGPIO (実機 Pi が必要).

## 4. 環境 / 起動コマンド (再掲)

```sh
# build
dune build src/aipl2c.exe

# .aipl → C → Xinu → QEMU (非 GUI)
./_build/default/src/aipl2c.exe abclc/<sample>.aipl \
    -o /tmp/x.c --xinu --max-msgs 30
cp /tmp/x.c /Users/kodamay/projects/xinu-raz/xinu/apps/abcl_program.c
( cd /Users/kodamay/projects/xinu-raz/xinu/compile &&
  make PLATFORM=arm-qemu COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi- \
       DEBUG=-DAIPL_AUTOSTART )
timeout 8 qemu-system-arm -M versatilepb -cpu arm1176 -m 128M \
    -nographic -semihosting -no-reboot \
    -kernel /Users/kodamay/projects/xinu-raz/xinu/compile/xinu.boot

# GUI 確認時
sh aice-pi-evolution/experiments/2026-05-20_xinu_razpi_aipl/run_<sample>.sh
```

## 5. 参考リンク

- 設計書: `AIPL_XinuRazPi_Round1.aice`
- 進化計算結果: `out/`, `out_ai/`
- README + 進捗表: `README.md`
- 関連 memory:
  - `project_xinu_razpi_aipl.md` — このトラックの中心メモリー
  - `project_aipl_nextgen_parity.md` — CE/DR 26 feature の他ランタイム parity
  - `project_drone_simulator.md` — N2 で再利用予定の WS bridge
  - `project_web_spreadsheet.md` — F2 で再利用予定の LWW 意味論
