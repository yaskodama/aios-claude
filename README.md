# aios-claude — AIPL as an AI-OS scripting layer

**AIPL** (Actor-based Intelligent Parallel Language; formerly AIPL)
is a small actor language descended from
the [ABCL/1](https://en.wikipedia.org/wiki/Actor-Based_Concurrent_Language)
family. See [USER_MANUAL.md](USER_MANUAL.md) for the language reference.  This project ships three wire-compatible runtimes for it
and uses the language as the scripting surface of an "AI-OS":
classes are agents, messages are prompts, and the runtime governs
token budgets, concurrency, persistence, and cross-machine
coordination.

```
+------------------+    HTTP / JSON     +-------------------+
| coordinator.abcl |  ----------------> | solver.abcl       |
| (Python)         |  <---------------- |   ai_call(...)    |
|                  |                    |   (Gemini)        |
|                  |                    +-------------------+
|                  |    HTTP / JSON     +-------------------+
|                  |  ----------------> | verifier.abcl     |
|                  |  <---------------- |   ai_call(...)    |
|                  |                    |   (Claude / GPT)  |
+------------------+                    +-------------------+
```

## Implementations

| Runtime | Source | Best for |
|---|---|---|
| OCaml AIPL | `src/*.ml`, `_build/.../repl_thread.exe` | the canonical interpreter; SDL/Xinu/Python codegen via `aipl2c`; minimal native binary |
| Browser AIPL | `src/browser-abcl/` | WebGL canvas demos in any browser |
| Python AIPL | `src/python-aipl/` | the AI-OS surface — every AI provider, every governance knob, distributed mode |

All three speak the same wire protocol: `POST /api/json/send`
(fire-and-forget) and `POST /api/json/call` (synchronous reply).
A coordinator on one runtime can drive workers on the other two
without a translation shim.

## Quick start (Python)

```sh
# 1. system Python 3.9 has the stdlib we need; install the deps
/usr/bin/python3 -m pip install --user -r src/python-aipl/requirements.txt

# 2. run a sample
/usr/bin/python3 src/python-aipl/aipl_main.py src/python-aipl/samples/Hello.abcl

# 3. or open the REPL
/usr/bin/python3 src/python-aipl/aipl_main.py
abcl> class H { method hi(n) { print("hello " + n); } }
abcl> var h = new H();
abcl> send h.hi("world");
abcl> :exit
```

To call an AI provider, set one of the keys before running:

```sh
GEMINI_API_KEY=...    src/python-aipl/aipl_main.py samples-ai/AIChainReal.abcl
ANTHROPIC_API_KEY=... src/python-aipl/aipl_main.py samples-ai/AIChainReal.abcl
OPENAI_API_KEY=...    src/python-aipl/aipl_main.py samples-ai/AIChainReal.abcl
```

`ABCL_AI_PROVIDER=mock` runs every `ai_call` against a built-in mock
so the distributed smoke and CI work without burning tokens.

## Three send types (Python)

```abcl
send target.method(args);                  // past — fire and forget
var x = now target.method(args);           // now — block, return reply
var f = future target.method(args);        // future — non-blocking
var v = await(f);                          //   ... await later
```

Replies come from the receiver via `reply(value)`.

## AI-OS governance knobs

All optional, all env-var driven:

| Variable | Effect |
|---|---|
| `ABCL_AI_PROVIDER` | `gemini` / `anthropic` / `openai` / `mock` |
| `ABCL_AI_TOKEN_BUDGET` | hard token cap; over-budget calls raise `BudgetExceeded` |
| `ABCL_AI_MAX_CONCURRENT` | semaphore on in-flight AI calls |
| `ABCL_AI_FALLBACK_MODELS` | comma-separated chain to retry on rate-limit / 5xx |
| `ABCL_AI_USAGE_FILE` | persist token / cost counters across sessions |
| `ABCL_NODE_STATE_FILE` | persist actor fields **and** undelivered mailbox messages |
| `ABCL_REMOTE_SECRET` | HMAC-SHA256 sign every remote send (X-ABCL-Sig) |
| `ABCL_PEER_DASHBOARDS` | `host:port,...` for the dashboard's cluster view |

## Distributed actors

Three nodes that cooperate via HTTP/JSON.  Provider can be
different on each.

```sh
# Terminal 1
GEMINI_API_KEY=...   /usr/bin/python3 src/python-aipl/aipl_main.py src/python-aipl/samples-remote/solver.abcl
# Terminal 2
ANTHROPIC_API_KEY=.. /usr/bin/python3 src/python-aipl/aipl_main.py src/python-aipl/samples-remote/verifier.abcl
# Terminal 3
/usr/bin/python3 src/python-aipl/aipl_main.py src/python-aipl/samples-remote/coordinator.abcl
```

Same pattern works with an OCaml worker — `web_listen(8080)` on
the OCaml side and the Python coordinator can `remote_now` into
it.  See `abclc/samples-remote/client.abcl` for the OCaml-side
view.

## Compiling actors to a binary (`.avm`) and sending them to other computers

An AIPL program is just text, but it can be **compiled to a compact
binary actor module** — an `.avm` file (magic `AVM1`) — with the
OCaml code generator:

```sh
# X.abcl  ->  X.avm   (integer-only actor bytecode; classes + methods + sends)
aipl2c.exe --avm --no-typecheck abclc/Rotate4Lines.abcl -o Rotate4Lines.avm
```

The `.avm` is a small, self-contained bytecode image: its classes,
methods, and `send` instructions are serialized into a fixed format
that any AIPL **dynamic VM** can load and run.  Because it carries no
host-specific code, the same binary can be **sent over the network to
another computer and executed there without recompiling anything** —
including a bare-metal **Xinu** kernel running on a Raspberry Pi, which
embeds a small actor VM:

```sh
# Send the actor binary to a running Xinu (Pi); it loads the classes,
# spawns the first actor, and kicks it with tick() — no kernel rebuild.
curl --data-binary @Rotate4Lines.avm http://<pi-ip>:8080/actor/loadvm?ask=0
```

Xinu accepts three actor payloads over HTTP, all the same way:

| Route | Payload | What runs |
|---|---|---|
| `POST /actor/loadvm`   | `.avm` actor bytecode (`AVM1`) | spawns the actor on the kernel's dynamic VM |
| `POST /actor/loadmesh` | 3-D mesh binary (`MK3D`)        | shaded 3-D model shown by the native viewer |
| `POST /actor/loadrig`  | skeletal rig binary (`MKR1`)    | articulated walking character |

So an actor is portable as **data**: write it as `.abcl`, compile it
to `.avm`, and ship it to any machine with an AIPL VM — phone, browser,
server, or a Pi running Xinu.

---

### アクターをバイナリ（`.avm`）に変換し、他のコンピュータへ送る（日本語）

AIPL プログラムはテキストですが、**コンパクトなバイナリのアクターモジュール**
＝ `.avm` ファイル（マジック `AVM1`）に**コンパイル**できます（OCaml コード生成器）:

```sh
# X.abcl  ->  X.avm （整数のみのアクターバイトコード。class + method + send を内包）
aipl2c.exe --avm --no-typecheck abclc/Rotate4Lines.abcl -o Rotate4Lines.avm
```

`.avm` はクラス・メソッド・`send` 命令を固定フォーマットに直列化した、
小さく自己完結したバイトコードイメージです。ホスト依存のコードを含まないため、
**同じバイナリをネットワーク経由で別のコンピュータへ送り、何も再コンパイル
せずにそのまま実行**できます。これには、Raspberry Pi 上でベアメタル動作する
**Xinu**（カーネルに小さなアクター VM を内蔵）も含まれます:

```sh
# 動作中の Xinu（Pi）へアクターバイナリを送信。クラスを読み込み、最初のアクターを
# spawn して tick() で起動する。カーネルの再ビルドは不要。
curl --data-binary @Rotate4Lines.avm http://<pi-ip>:8080/actor/loadvm?ask=0
```

Xinu は 3 種類のアクター・ペイロードを HTTP で同じ要領で受け取れます:

| ルート | ペイロード | 実行内容 |
|---|---|---|
| `POST /actor/loadvm`   | `.avm` アクターバイトコード（`AVM1`） | カーネルの動的 VM 上でアクターを spawn |
| `POST /actor/loadmesh` | 3D メッシュバイナリ（`MK3D`）         | ネイティブビューアでシェーディング表示 |
| `POST /actor/loadrig`  | スケルトンリグバイナリ（`MKR1`）       | 関節歩行キャラクターを表示 |

つまりアクターは**データとして可搬**です。`.abcl` で書き、`.avm` にコンパイルし、
AIPL VM を持つ任意のマシン（スマホ・ブラウザ・サーバ・Xinu 上の Pi）へ送れます。

## Live dashboard

```sh
/usr/bin/python3 src/python-aipl/aipl_main.py --dashboard 8800 samples-ai/Budgeted.abcl
```

Open <http://127.0.0.1:8800/> for the live counters, observed
traffic table, and SSE event stream.  Set
`ABCL_PEER_DASHBOARDS=host:port,...` on the coordinator's dashboard
to fold every worker's numbers into a TOTAL row.

## Smoke tests

```sh
make smoke           # OCaml + JS + Python + 3-node mock distributed
make smoke-dynamic   # also opens the JS demos in headless Chrome
```

Latest run:

```
ABCL  : 52/52   (OCaml REPL + aipl2c + cc/SDL2)
JS    : syntax 7/7 + parse 4/4
Python: 7/7
Dist  : 8/8     (3-node distributed mock)
```

## Reference

- Language tour and grammar: [USER_MANUAL.md](USER_MANUAL.md)
  - §6 Phase C–E2 type inference (`--check` / `--infer` for HM + Z3 refinement)
  - §7 AIPL v2 Distributed Runtime (`aipl_dist`) — 8 opt-in features
    (env_var_routing / structured_log / token_budget / checkpoint /
    quarantine_and_skip / quorum_replicate / subtree_quarantine /
    integration) for hang-resilience and rate control
- Builtin reference: [BUILTINS.md](BUILTINS.md)
- Sample index: `samples/` and `samples-ai/` and `samples-remote/`
  under `src/python-aipl/`; `abclc/*.abcl` and `abclc/ai-samples/`,
  `abclc/samples-remote/` for the OCaml side

## Related

This project descends from earlier AIPL work; the goal here is
to make the language useful as the orchestration layer of an
AI-OS — a small DSL where actors are agents, messages are prompts,
and the runtime is responsible for keeping cost, concurrency,
and reliability under control.
