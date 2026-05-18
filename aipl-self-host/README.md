# AIPL Self-Host Bootstrap (10 levels, complete)

`AIPL は AIPL 自身を書いている.`  本ディレクトリは、進化計算で探索した
`aice-evolution-v2/examples/AIPLSelfHost*.aice` の設計を実装に落とした
10 層ブートストラップ.最下層 (Level C) で「AIPL ソースを AIPL でパース」、
中段 (Level B-1〜B-5) で「AIPL 検査器を AIPL で書く」、上段 (Level A) で
「AIPL を解釈する AIPL eval」を実現し、Level Z で全部をまとめて
**≤20 行の Python bootstrap loader** から起動できる状態に到達.

## 構成 (下→上)

| Level | 役割 | 主要ファイル | サンプル |
|---|---|---|---|
| **C**     | 字句解析 + 構文解析 + eval パイプライン | `lexer.abcl` (185) + `parser.abcl` (318) + `eval.abcl` (101) | 3 |
| **C-2**   | アクタースケジューラ (Phase 11+) | `scheduler.abcl` | 6 |
| **C-3**   | スケジューラ + now/future | `scheduler.abcl` | 1 |
| **B-1**   | Phase 11 型検査 | `typeck.abcl` | 6 |
| **B-2**   | Phase 12 効果検査 | `typeck.abcl` | 4 |
| **B-3**   | Phase 13 チャネル検査 | `typeck.abcl` | 5 |
| **B-4**   | Phase 14 linear 検査 | `typeck.abcl` | 4 |
| **B-5**   | Phase 15 owned 検査 | `typeck.abcl` | 4 |
| **A**     | メタサーキュラ評価器 | `metacircular.abcl` (216) | 4 |
| **Z**     | **統合: Level C + IO bridge + 最小 bootstrap** | `driver_head.abcl` + `io_bridge.abcl` + `bootstrap.py` (18) | 4 |

合計 **37 サンプル全 PASS** (各 level の `smoke.sh` で確認可能).

## Level Z = self-host complete の証明

`bootstrap.py` は **18 行** (.aice 仕様の ≤20 行制約内) で、

1. ユーザの `.abcl` ファイルを読み
2. `level-c/lexer.abcl` + `parser.abcl` + `eval.abcl` + `driver_head.abcl` を連結
3. ホスト AIPL に渡す

…だけ.この時点で **構文解析と評価は全て AIPL 側で完結** している.
ホスト Python ランタイムが残るのは

- AIPL 言語の組込みプリミティブ実装 (read_file / ai_call 等)
- アクタースケジューラ (Level C-2/C-3 が AIPL 側のスケジューラを
  書いているが、ホスト側のスケジューラに「乗る」設計)
- bootstrap.py 自体 (18 行)

のみ.IO bridge (`io_bridge.abcl`) はそのうち AI / FS / NET プリミティブを
**CE-11 capability check ごし** に再エクスポートするので、ホスト権限と
ユーザコードの間に capability 境界が立つ.

```sh
$ bash aipl-self-host/level-z/smoke.sh
[Phase 1] AIPL-side lexer + parser + eval
  PASS  HelloLevelZ          | Hello from Level Z
  PASS  HelloLevelZ          | [level-z] done
  PASS  ArithLevelZ          | 45
  ...
[Phase 2] IoBridge + capability gating
  PASS  IoBridge             | [io] read = hello self-host
  PASS  IoBridgeStrict       | capability denied
==== Level Z (full self-host) smoke summary ====
  pass=10  fail=0
```

## 全レベルの smoke を一気に回す

```sh
bash aipl-self-host/_smoke_all.sh
```

期待値:

```
level-c       3 pass / 0 fail
level-c2      6 pass / 0 fail
level-c3      1 pass / 0 fail
level-b       6 pass / 0 fail
level-b2      4 pass / 0 fail
level-b3      5 pass / 0 fail
level-b4      4 pass / 0 fail
level-b5      4 pass / 0 fail
level-a       4 pass / 0 fail
level-z      10 pass / 0 fail
total: 47 / 47
```

## AIPL の構文サブセット (level-z bootstrap 経由で動くもの)

`level-c/parser.abcl` がサポートする最小サブセット:

```
program  := stmt*
stmt     := var_decl | assign | print | if | while | block | call_stmt
var_decl := "var" IDENT "=" expr ";"
assign   := IDENT "=" expr ";"
print    := "print" "(" expr ")" ";"
if       := "if" "(" expr ")" stmt ("else" stmt)?
while    := "while" "(" expr ")" "do" stmt
block    := "{" stmt* "}"
call_stmt:= IDENT "(" args? ")" ";"
expr     := add_expr (rel_op add_expr)?
add_expr := mul_expr (add_op mul_expr)*
mul_expr := unary    (mul_op unary)*
unary    := "-" unary | primary
primary  := INT | STR | IDENT ("(" args? ")")? | "(" expr ")"
```

クラス / アクター / select / saga / generic / linear / owned 等の
上位機能はホスト AIPL のみで扱う (`io_bridge.abcl` のように
ホスト側スクリプトとして書く).self-host サブセットを広げるなら
`level-c/parser.abcl` を拡張するか、別レイヤとして `level-c4` 等を
追加する.

## 進化計算による設計の経緯

10 レベルの分割は、

- `aice-evolution-v2/examples/AIPLSelfHost.aice`           — 全体設計
- `aice-evolution-v2/examples/AIPLSelfHost_A_Metacircular.aice` — Level A
- `aice-evolution-v2/examples/AIPLSelfHost_B_PhaseChase.aice`   — Level B-1〜B-5
- `aice-evolution-v2/examples/AIPLSelfHost_B1_TypeOnly.aice`    — Level B-1 詳細
- `aice-evolution-v2/examples/AIPLSelfHost_B2_EffectsOnly.aice` — Level B-2 詳細
- `aice-evolution-v2/examples/AIPLSelfHost_C_FullHost.aice`     — Level C / Z

を MAP-Elites で探索した結果から得た.各 `.aice` には設計軸 (parser 流儀, AST 表現,
環境のデータ構造, スケジューラ実装の所在) と reviewer persona (SelfHostFeasibility,
PhaseMonotonicity, HostMinimality 等) が記録されている.

`Level Z` の **20 行 bootstrap** + capability-checked IO bridge は、
`AIPLSelfHost_C_FullHost.aice` の Bootstrap タスク
("ホスト loader が AIPL ソースを読んで eval を呼ぶ最小コード") を
実装に落とした最終形.
