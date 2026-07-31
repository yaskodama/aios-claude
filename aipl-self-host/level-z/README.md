# Level Z — Full Self-Host (integrated)

ブートストラップの **最上位レベル**.下位の Level C (lexer + parser + eval) を
1 つのドライバに統合し、ホスト Python は **18 行の bootstrap loader** だけに縮退.
さらに `io_bridge.aipl` で fs / ai / net プリミティブを CE-11 capability check
ごしに再エクスポートし、self-host された AIPL コードが capability 境界を越えて
ホスト権限にアクセスする経路を確立.

## ファイル

```
bootstrap.py       — 18-line Python loader (≤20 lines per spec)
driver_head.aipl   — Bootstrap actor (tokenize → parse → eval を順に呼ぶ)
io_bridge.aipl     — IoBridge actor (capability-checked fs/ai/net)
samples/
  HelloLevelZ.aipl    — hello world + 算術
  ArithLevelZ.aipl    — 算術 + if/else
  LoopLevelZ.aipl     — while ループ + accumulate
  SampleIoBridge.aipl — IoBridge を介した fs/ai 呼出 (host-level)
smoke.sh           — 4 sample × 10 アサーション
out/               — sample 実行ログ
```

## 起動の流れ

```sh
$ python3 bootstrap.py samples/HelloLevelZ.aipl
[level-z] lex   : 18 tokens
[level-z] parse : 3 stmts
[level-z] eval  :
Hello from Level Z
5
[level-z] done
```

`bootstrap.py` 内部:

1. `sys.argv[1]` の AIPL ソースを読む
2. `../level-c/{lexer,parser,eval}.aipl` を concat
3. `driver_head.aipl` を append (Bootstrap actor 定義)
4. trailer (`var __USER_SRC = read_file("..."); var __B = new Bootstrap(); send __B.run(__USER_SRC);`) を append
5. 結合済みファイルを `/tmp/_aipl_level_z.aipl` に保存
6. ホスト AIPL に渡して実行

ステップ 2-4 はファイル連結だけ.分析 / 解釈は一切ホスト側で行わない.

## IO bridge — capability 境界の実物

`io_bridge.aipl` は 6 メソッドを公開:

| メソッド | 必要 cap | ホスト primitive |
|---|---|---|
| `read(path)`       | fs       | read_file |
| `write(path, c)`   | fs       | write_file |
| `append(path, c)`  | fs       | append_file |
| `exists(path)`     | fs       | file_exists |
| `ai_simple(prompt)` | ai, net | ai_call |
| `ai_chat(sys, prompt)` | ai, net | ai_call_with_system |

各メソッドは `check_capability("...")` を最初に通過させるので、

- `AIPL_CAP_STRICT=1` + grant 無し → `[actor X.method] error: capability denied`
  で停止 (smoke の IoBridgeStrict ケースで確認済)
- 既定の advisory モード + grant 無し → `cap_violation` を NDJSON ログに記録し、
  メソッド本体は続行 (CE-11 仕様通り)

注: `io_bridge.aipl` は **ホスト AIPL** から直接 source 読込される
(Level Z パーサは class 構文を解さないため self-hosted 側からは呼べない).
self-host を class 構文まで広げるなら `level-c/parser.aipl` の拡張が必要.

## smoke

```
$ bash smoke.sh
[Phase 1] AIPL-side lexer + parser + eval
  PASS  HelloLevelZ          | Hello from Level Z
  PASS  HelloLevelZ          | [level-z] done
  PASS  ArithLevelZ          | 45
  PASS  ArithLevelZ          | [level-z] done
  PASS  LoopLevelZ           | 10
  PASS  LoopLevelZ           | [level-z] done

[Phase 2] IoBridge + capability gating
  PASS  IoBridge             | [io] write done
  PASS  IoBridge             | [io] read = hello self-host
  PASS  IoBridge             | [io] ai_simple =
  PASS  IoBridgeStrict       | capability denied

==== Level Z (full self-host) smoke summary ====
  pass=10  fail=0
```

## .aice 出自

`aice-evolution-v2/examples/AIPLSelfHost_C_FullHost.aice` の以下 2 タスクを
実装に落としたもの:

- **task Bootstrap** — "ホスト loader が AIPL ソースを読んで eval を呼ぶ最小コード (20 行以下) で全機能が立ち上がる"
- **task IO_Bridge** — "file_read/write, ai_call, image_load などのホスト bridge を, AIPL から見える capability actor (Fs/Net/Ai/Mut) として再エクスポート"

残タスク (Level Z scope 外):

- `task Scheduler` (Level C-2/C-3 が部分実装、上位段はまだホストが担当)
- `task Mailbox` (host 側に常駐)
- `task Future` (now/future/await の AIPL-side 再実装は Level C-3 部分まで)
- `task Phase16_Transient` (transient cast の自己反映実装)

これらは追加レイヤ (`level-c4` 以降) として将来拡張可能.
