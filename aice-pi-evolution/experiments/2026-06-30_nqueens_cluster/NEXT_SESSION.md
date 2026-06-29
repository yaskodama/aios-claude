# NEXT SESSION — 分散 N-Queens ベンチ & 3台メッシュ (2026-06-30)

## 完成済み（コミット & push 済み）
- **分散 N-Queens ベンチ + LaTeX/PDF 報告** — 本ディレクトリ、abclcp `021ae20`（branch `feat/xinu-jit-target`, remote `aios-claude`）。
  - `nq_cluster_bench.py` … オーケストレータ（列分割・並行ディスパッチ・wall-clock・OEIS照合・warmup・reps best-of・retry）
  - `gen_report.py` … `results.json` → `report.tex`（xelatex/xeCJK）生成
  - `results.json` … 最終データ 22点（4構成 × N=8..13、全て正当性OK）
  - `report.tex` / `report.pdf` … 3ページ報告（著者=児玉靖司）
- **3ボードに native `/nqpart` ルート実装・焼き込み・実機検証済**：
  - rpi5 `~/projects/xinu-rpi5` (main) commit `786f85d`、SD焼済 `kernel_2712.img`
  - rpi4 `~/projects/xinu-rpi4` (feat/smp-4core-and-basic-graphics) commit `4770a1e`、SD焼済 `kernel8.img`
  - rpi3 `~/projects/xinu-raz/xinu` (arm-rpi3-port) commit `1e93837`、SD焼済 `xinu.boot`→kernel.img
  - md5: rpi5=`0fbd46be` / rpi4=`f53ff69c` / rpi3=`7592c67c`

## ヘッドライン結果
- N=11: Mac AIPL単体 **40.46s** → Mac+rpi3 **0.064s** = **×637高速化**
- 全22点で解数が OEIS A000170 と一致（正当性100%）
- N=12 でクラスタが綺麗な単調減（+rpi3 0.256 → +rpi4 0.234 → +rpi5 0.160s）

## ボード IP / ルート
| board | IP:port | conn | cores | /nqpart |
|---|---|---|---|---|
| rpi3 | 192.168.3.50:8080 | WiFi-LAN | 1 | `GET /nqpart?n=N&c0=A&c1=B` |
| rpi4 | 192.168.3.100:80 | ethernet | 4(SMP) | 同上(smp_parallel_sum) |
| rpi5 | 192.168.3.101:80 | ethernet | 4(SMP) | 同上 |
- 応答形式: `nqueens-partial n=.. c0=.. c1=.. solutions=.. ms=.. cores=..`
- iPhone=192.168.3.219(lockdownd確定) / Windows=192.168.3.32(Defenderが受信8080遮断・ベンチ対象外)

## 再実行コマンド
```
cd ~/ocaml-app/abclcp-project/aice-pi-evolution/experiments/2026-06-30_nqueens_cluster
python3 -u nq_cluster_bench.py --nmin 8 --nmax 13 --mac-nmax 11 --reps 3 --out results.json
python3 gen_report.py
export PATH="/Library/TeX/texbin:$PATH"; xelatex -interaction=nonstopmode report.tex; xelatex -interaction=nonstopmode report.tex
```
※実行前に各ボードの健全性は `curl -v http://<ip>/nqpart?n=4&c0=0&c1=4` で `HTTP/1.0 200 OK` を確認（`curl -s` は connection-close待ちで空に見えるが urllib は正常）。

## ★落とし穴（再発防止メモ）
1. **rpi3 単一スレッド webactor の wedge**（初回最大35s・連投で停止）→ コードに warmup＋reps間 `time.sleep(0.5)`＋`board_nqpart` retries=4 で対策済。`wifi off` 等を汎用シェル(/run,/shell)で叩くと HTTP wedge → **禁止**（rpi5 を一度 wedge させ電源再投入で復旧した）。
2. **Mac の DHCP IP 変化**（mac単体N=11の40s CPU中に .217→.218 へ変わり全ボードへ Errno51 "Network unreachable"で失敗）→ retry で耐性化済。再走時もたまに起きるので retry 前提。
3. Mac AIPL template `cols[12]` 固定 → N≤12、mac単体は実用上 N≤11（N=12=247s）。
4. `smoke.json` は初期テスト残骸（未追跡・無視可）。

## 未完 / 次にやると良いこと
- **メッシュ（10.0.0.x IBSS MANET）**: rpi3↔rpi4 の1hop疎通は確立済。**rpi5 が別セルで未merge**（コールドブートIBSS merge問題）。
  - 確実化には rpi5 を含め3台を順次コールドブート後、安全な `GET /wifi-adhoc?ssid=MANET&ch=6&n=N`(n: rpi3=1/rpi4=2/rpi5=3) で投入し、約70s待って `wifi aodv 10.0.0.X` で検証。**rpi3 は無線1つ＝mesh参加で home AP(.50)離脱**（rpi4/5 は ethernet維持で両立）。
  - 注: ベンチは LAN(192.168.3.x)使用なのでメッシュ不要。両立させるなら rpi3 をLAN復帰させてからベンチ。
- 報告の改善余地: 速度比例の重み付き列分割（現状は等分割で rpi3 がボトルネック）、N=13 +rpi5 のジッタ低減、図(speedupグラフ)追加。
- Windows sim をベンチに入れる場合: Defender受信8080許可 → `http://192.168.3.32:8080/api/console` 疎通確認。

## 関連メモリ
project_nqueens_cluster_bench / project_xinu_mesh_and_control_center / project_xinu_rpi5_live_and_kernel_evo / reference_xinu_rpi3_real_repo
