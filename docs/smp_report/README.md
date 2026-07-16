# Raspberry Pi Xinu マルチコア化レポート

`smp_report.pdf` を生成する LaTeX 一式。rpi3 は執筆済み、rpi4 / rpi5 は雛形のみ。

## ビルド

```sh
make            # -> smp_report.pdf
make clean
```

xelatex を使う（日本語 = Hiragino）。★ 目次と `\ref` のため 2 回まわす必要があり、
Makefile がそうしている。

## 構成

| ファイル | 中身 |
|---|---|
| `main.tex` | プリアンブル・共通部（設計 / 測定方法 / 横断比較 / 結論）・`\input` |
| `boards/rpi3.tex` | Pi 3 の実装と実測（**執筆済み。rpi4/rpi5 の雛形でもある**） |
| `boards/rpi4.tex` | Pi 4（未執筆） |
| `boards/rpi5.tex` | Pi 5（未執筆） |

共通部はボードに依存しない。ボード別の事実だけが `boards/` にある。

## ボードを追加する手順

1. `boards/rpi4.tex` を、`boards/rpi3.tex` と**同じ節構成**で埋める
   （対象と前提 → コア起動 → 実測1..3 → 適用判断 → 発見した不具合）。
   節構成を揃えると横断比較表がそのまま使え、ボード間の差分が読者に見える。
2. `main.tex` の「ボード別」にある `\section` と `\input{boards/rpi4}` の
   コメントを外す。
3. `main.tex` の横断比較表（`tab:cross`）の該当列を埋める。
4. `make`。

`\section{}` は `main.tex` 側にあるので、`boards/*.tex` は `\subsection` から始める。

## 測定するときの注意（rpi4 / rpi5 でも同じ罠を踏む）

これらは rpi3 で実際に踏んだもの。数字を採る前に読むこと。

- **`clktime`/`clkticks` を時間測定に使わない。** タイマ割り込みで加算される
  変数で、この環境では発火が安定せず**常に 0 ms** を返した。
  `clkcount()`（System Timer の 1 MHz フリーランニングカウンタ直読）を使う。
- **絶対時間を比較に使わない。** CPU クロックが一定でない（再起動直後の
  1 回目だけ速い。実測比 2.33 = Pi3 B+ の 1.4 GHz ÷ 600 MHz）。
  **速度向上比**は 1 コア測定と 4 コア測定を同一リクエスト内で連続実行するので
  クロックが相殺され、安定する。比を報告すること。
- **アクターを起動したまま測らない。** ロードバランサを動かした状態で測ると
  fill の 1 コアが 5,125 → 11,007 µs と 2 倍に化けた。再起動直後・
  アクター未起動の状態で測る。
- **`agree` を必ず確認する。** 全ベンチは逐次と並列を両方走らせて答えの一致を
  報告する。速いが誤った結果を見逃さないため。

## データの出どころ

すべて実機の HTTP ルート。rpi3 は `http://192.168.3.50:8080`。

```sh
curl 'http://<board>:8080/bench?kind=nqueens&n=12'    # 計算律速
curl 'http://<board>:8080/bench?kind=dining&n=5'      # 純レジスタ演算
curl 'http://<board>:8080/bench?kind=primes&n=200000'
curl 'http://<board>:8080/bench?kind=fill&n=262144'   # メモリ律速(=描画と同性質)
curl 'http://<board>:8080/bench?kind=null'            # プール往復コスト
curl 'http://<board>:8080/nqactor?n=12&col=0'         # AIPLアクターの計算 A/B
curl 'http://<board>:8080/api/mmu'                    # SCTLR: D-cache OFF の確認
```

実装は `~/projects/xinu-raz/xinu` の `include/smp.h`、
`system/platforms/arm-rpi3/smp.c`、`loader/platforms/arm-rpi3/start.S`、
`apps/webactor.c`、`apps/abcl_program.c`。
rpi4 の既存資料は `~/projects/xinu-rpi4/docs/SMP_REPORT_JA.md`。
