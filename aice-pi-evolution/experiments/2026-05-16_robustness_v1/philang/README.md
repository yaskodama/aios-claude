# PhiLang — Minimal Interpreter

進化計算 (本ディレクトリの REPORT.md §6) が示唆した **Phase Orchestration Language** の最小実装。

## 構成

| ファイル | 役割 | 行数 |
|---|---|---:|
| `philang_parser.py` | `.phi` → `Phase` AST | 188 |
| `philang_interp.py` | AST 実行 + guarantees 検証 | 207 |
| `philang_stdlib.py` | 数値カーネル (現状 Chudnovsky のみ) | 60 |
| `philang_main.py` | CLI エントリ | 26 |
| `compute_pi_10k.phi` | サンプル: π 10,000 桁 | 26 |

## 実行

```bash
/usr/bin/python3 philang_main.py compute_pi_10k.phi
```

期待出力:

```
[phi] running phase 'ComputePi10k'
[phi]   compute: chudnovsky_pi(digits=10000, ckpt_every=1000, ckpt_path='.../pi_10k.partial.txt')
[phi]   wrote 10002 chars → .../pi_10k.txt (1.832s)
[phi] verifying guarantees...
[phi]   digit_count: ✓ (10000 ≥ 10000)
[phi]   starts_with: ✓ (37 char prefix matches)
[phi]   no_silent_death: ✓ (reached verification phase)
[phi]   bounded_wall: ✓ (1.83s ≤ 60.0s)
[phi]   partial_resume_on_kill: ✓ (1 checkpoint clause(s))
[phi] phase 'ComputePi10k': all guarantees satisfied in 1.83s
```

## 言語の意味論

PhiLang プログラムは **1 つの phase + 1 つの guarantees ブロック**で構成される。

```
phase NAME
  within   <duration> and <cost>     # ハード予算
  drains   for <dur> idle <dur>      # actor drain buffer (LLM 用、kernel では未使用)
  caffeine if <cond>                 # Mac sleep 対策
  uses     <provider/model>          # 任意
{
  <key> = <value>                    # 通常パラメタ
  every call has policy { ... }      # LLM コール用 (Phase-1 等)
  after every <N> <unit> { ... }     # チェックポイント / 進捗フック
}
guarantees {
  <predicate>                        # bool 形式
  <predicate> = <value>              # 値付き形式
}
```

### 実装済の compute kernel

`philang_stdlib.COMPUTE_REGISTRY` で参照可能なもの:

| key | 関数 | 用途 |
|---|---|---|
| `chudnovsky_binary_splitting` | `chudnovsky_pi(digits, ckpt_every, ckpt_path)` | π を任意桁計算 |

### 実装済の guarantee

| 名前 | 検証内容 |
|---|---|
| `no_silent_death` | guarantees ブロックに到達できたか (= プロセス生存) |
| `bounded_wall = <dur>` | 実時間が指定値以下か |
| `bounded_cost = <cost>` | (LLM 用、kernel は常に 0) |
| `digit_count = <N>` | 出力の桁数 ≥ N |
| `starts_with = "<prefix>"` | 出力が指定の文字列で始まるか |
| `partial_resume_on_kill` | `after every ... checkpoint` 句が phase 内にあるか |

## 検証実績 (2026-05-16)

| 項目 | 値 |
|---|---|
| 計算桁数 | 10,000 |
| 所要時間 | 1.83 秒 |
| 先頭 102 桁の既知 π との一致 | ✓ |
| Feynman 点 (`999999` の最初の出現) | 位置 762 (既知値と一致) |
| 1000 桁目 | `9` (既知 OEIS A000796 と一致) |
| 出力ファイル | `pi_10k.txt` (10003 bytes), `pi_10k.partial.txt` (中間チェックポイント) |

## 仕様外 / 既知の限界

- **`uses` 句**: 現状は構文上受け取るだけで実際の provider 切替は行わない (kernel が local なので)。
- **`every call has policy`**: LLM コール用の宣言だが、現 stdlib に LLM kernel が無いので未テスト。Phase-1 等の AIPL 連携を将来追加するときに使う。
- **エラー時の partial_resume_on_kill**: `after every ... checkpoint` 句があれば guarantee は OK だが、実際に途中で kill されたときの resume ロジックは未実装。
- **並列実行**: なし。Chudnovsky kernel は単一スレッドで decimal を回す。
