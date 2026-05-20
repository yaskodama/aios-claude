# AIPL_XinuRazPi_RemoteRPC

Host PC (macOS) から QEMU 上の Embedded Xinu / AIPL ランタイムへ、
QEMU の `-serial tcp:` 機能を使ったテキスト行プロトコルで
リモート actor を spawn / send する機能の設計書 (.aice) と
将来生成される sample 実装の置き場所。

## ファイル

- `AIPL_XinuRazPi_RemoteRPC.aice`  — 設計書 (C 風 DSL, v2 dialect)
  - 5 phase (H1 UART1 driver / H2 RPC line protocol / H3 dispatcher
    thread / H4 sample programs / H5 smoke + regression) + 2
    cross-cutting (H_BackwardCompat / ImplCost)
- `out/AIPL_XinuRazPi_RemoteRPC.ga.json` — `.aice` の lower 結果
  (parser に通った確認用)
- (TBD) `host_rpc_demo.sh` / `host_rpc_demo.py` / `_smoke_*.sh` /
  `abclc/RemoteRpcDemoXinu.abcl` — 各 phase 実装で追加。

## パイプライン

```sh
# .aice -> .ga.json (parser を通すだけ、実行しない)
cd aice-evolution-v2
python3 -m src.cli --no-run \
    ../aice-pi-evolution/experiments/2026-05-20_xinu_remote_rpc/AIPL_XinuRazPi_RemoteRPC.aice
# → out/AIPL_XinuRazPi_RemoteRPC.ga.json
```

## 物理経路 (decision: channel_topology)

QEMU を以下のように起動する:

```sh
qemu-system-arm \
    -M versatilepb -cpu arm1176 -m 256M \
    -kernel xinu.elf \
    -nographic \
    -serial mon:stdio \
    -serial tcp:127.0.0.1:5555,server=on,wait=off
```

- UART0 → stdio (= 既存 xsh プロンプト).変更なし。
- UART1 → host TCP socket 127.0.0.1:5555.Xinu 側 `rpc_dispatcher_main`
  thread が独占的に read/write、host からは `nc localhost 5555` か
  Python socket でアクセス。

## プロトコル (decision: protocol_format)

LF 終端のテキスト行。1 行 = 1 命令 / 1 応答。

| 命令                                  | 応答                                       |
|---------------------------------------|--------------------------------------------|
| `PING`                                | `OK pong=1`                                |
| `SPAWN <class>`                       | `OK actor_id=N class=<class>`              |
| `SEND <actor_id> <method> [<arg>...]` | `OK queued method=<method>`                |
| `QUERY <actor_id> <field_idx>`        | `OK value=N`                               |
| `LIST`                                | `OK n_actors=N`                            |
| (parser error)                        | `ERR <reason>`                             |

引数は decimal int のみ (Phase H2 では文字列引数を保留)。

## サンプル `RemoteRpcDemoXinu.abcl`

H4 で生成する AIPL 側のサンプル。起動時は actor 数 0。

```abcl
class Counter {
  var n = 0;
  method bump() { n = n + 1; print(7000 + n); }
  method dump() { print(8000 + n); }
}

class Greeter {
  var who_tag = 0;
  method set_who(t) { who_tag = t; print(9000 + t); }
  method hello()     { print(10000 + who_tag); }
}

// 起動時 instance なし - host からの SPAWN を待つ
```

Host bash クライアント (`host_rpc_demo.sh` 抜粋):

```sh
{ echo PING
  echo "SPAWN Counter"
  echo "SEND 0 bump"
  echo "SEND 0 bump"
  echo "SEND 0 dump"
  echo "SPAWN Greeter"
  echo "SEND 1 set_who 42"
  echo "SEND 1 hello"
  echo LIST
} | nc -q 1 127.0.0.1 5555
```

期待される kernel digest (UART0/stdio 側):
`7001 → 7002 → 8002 → 9042 → 10042`

## 実装順序

`H1 → H2 → H3 → H4 → H5 → H_BackwardCompat`.
詳細 dep は `.aice` の `implementation_order` ブロック参照。

## 既存資産との関係

- F1 で導入した `abcl_object_field_{get,set,count,class_id}` を流用
- N1 (TCP/IP via smc91c111) は partial の問題があるので、敢えて
  NIC 経由ではなく `-serial tcp:` を選択 (decision: channel_topology)
- 既存 17 smoke (R1〜F2 + R_BackwardCompat) を壊さない点が
  `H_BackwardCompat` の合格条件
