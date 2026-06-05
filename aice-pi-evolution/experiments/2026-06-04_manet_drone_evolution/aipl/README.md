# M-006 災害避難ミッション — AIPL アクター (UAV1=Xinu1 / UAV2=Xinu2)

M-006 (FIT2023 関口/加藤/神林)「移動エージェントを搭載した UAV による山間部
災害避難支援システム」を **AIPL アクター**として実装。UAV を Xinu ノード上の
自律アクターとし、MANET (ZRP/AODV ルーティング) 越しに連携させる。

## プログラム構成

| ファイル | 役割 | 配備先 |
|---|---|---|
| `UAV1_Xinu1.abcl` | **情報収集** UAV1。P1..P20 の被災状況を保持し、M-006 優先度式で最高優先度点を計算して返す (`best_target`/`survivors_at`/`px_at`/`py_at`/`clear`/`set_ref`)。 | **Xinu1** |
| `UAV2_Xinu2.abcl` | **避難誘導** UAV2。`dispatch(pid,x,y,surv)` で被災点へ飛び、最寄り避難所(A/B)へ誘導、救助数を返す。累計・現在地を保持。 | **Xinu2** |
| `GroundStation_Mission.abcl` | **統括 + 統合実行**。GS が UAV1 から pull → UAV2 へ dispatch → UAV1 を clear、8 試行で集計。3 アクターを 1 ランタイムで結線した**検証版**。 | (検証) |
| `Deploy_Xinu.abcl` | **実機ランチャ**。UAV1 を Xinu1 に、UAV2 を Xinu2 に SPAWN し、`uart1://` (UART1/TCP RPC) 越しにミッションを駆動。 | Mac→2-Xinu |

## 優先度式 (M-006 / drone-hil 準拠)

```
priority = (1.2·dd + 0.05·t + 0.7·dhc) · sqrt(1 + survivors)
  dd  = 1 - y                  標高プロキシ (高所優先)
  t   = UAV2 現在地からの距離 ×0.01    移動時間プロキシ
  dhc = dd · |x - x_B|         標高 × 海岸距離
```
※ AIPL ランタイムに `log` が無いため、人数重みは劣線形の `sqrt(1+survivors)` で代替。
※ `int`/`float` は予約語のため数値キャストに使えない。救助は「1 試行 = その点を全救助」モデル
   (整数のまま、floor 不要)。

## 実行 / 検証

```bash
cd ~/ocaml-app/abclcp-project
# 統合ミッション (3 アクター結線、end-to-end)
python3 src/python-aipl/aipl_main.py .../aipl/GroundStation_Mission.abcl --timeout 25 --idle-ms 800
# 各ノード単体の自己点検
python3 src/python-aipl/aipl_main.py .../aipl/UAV1_Xinu1.abcl --timeout 10 --idle-ms 600
python3 src/python-aipl/aipl_main.py .../aipl/UAV2_Xinu2.abcl --timeout 10 --idle-ms 600
# 実機ランチャの配線確認 (HW 無しは parse/型のみ)
python3 src/python-aipl/aipl_main.py .../aipl/Deploy_Xinu.abcl --ast
```

検証結果 (統合ミッション): 8 試行で **P12→P5→P2→P1→P18→P6→P9→P8** を救助、
**累計 195 名 / 残存 154 名** (M-006 Round 0 ≈ 201 名と整合)。

## 実機配備 (2-Xinu over MANET)

`dining_mac_xinu` と同方式。UAV1/UAV2 のロジックを各 Xinu カーネルに `"UAV1"`/`"UAV2"`
クラスとして pre-link し、各 Pi が `apps/abcl_xinu_rpc.c` の TCP RPC を :5555 で公開。
`Deploy_Xinu.abcl` が `uart1://10.0.0.1:5555` (Xinu1/Pi4) と `uart1://10.0.0.2:5555`
(Xinu2/Pi3) に `remote_now`/`remote_call` でミッションを駆動。UAV1↔GS↔UAV2 の制御
メッセージは実機 MANET (このプロジェクトで進化させた **hybrid_ZRP** / AODV) が運ぶ。

落とし穴: `now self.X()` は Py-I で自己デッドロックする → 自己処理は field 直読で
インライン化 (UAV1 `self_scan` 参照)。`uart1://` は単一クライアント占有。
