# AIPL Runtime Feature Matrix

Side-by-side feature comparison across the seven AIPL implementations
in this repository.  All entries are grounded in source — see notes
for file/line pointers.

**Legend**: ✅ YES (full) — 🟡 PARTIAL — ❌ NO — N/A (not applicable)

The seven runtimes:

| Short name             | Source                                     |
| ---------------------- | ------------------------------------------ |
| Python (annotated)     | `src/python-aipl/`                         |
| Python (inferred)      | `src/python-aipl-inferred/`                |
| OCaml                  | `src/*.ml`, `_build/.../repl_thread.exe`   |
| JS-OCaml (server)      | `src/app.js` / `console_server.js` / `ide.js` (browser JS) + `src/web_gateway.ml` (OCaml HTTP server) |
| JS-Browser (serverless)| `src/browser-abcl/`                        |
| **JS-Node (server)**   | `src/node-aipl-server/` (Node.js HTTP server hosting the browser-abcl runtime) |
| C (abcl2c)             | `src/abcl2c.ml` codegen + `src/abcl_gui_runtime.c` |

Column abbreviations in tables below: **Py-A**, **Py-I**, **OCaml**,
**JS-O** (OCaml-backed), **JS-B** (browser-only), **JS-N** (Node-server), **C**.

### Relationship between the JS runtimes

- **JS-OCaml** is a thin HTTP client over the OCaml runtime; its
  feature set is the OCaml runtime's plus the new `/api/typecheck`
  endpoint.
- **JS-Browser** is the standalone in-browser implementation
  (parser + interpreter + flow-sensitive checker all in JS).
- **JS-Node** wraps the same browser-abcl parser / type-checker /
  interpreter inside a Node.js HTTP server, exposing
  `/api/typecheck` and `/api/run` from a single Node process.
  Runtime feature set therefore mirrors browser-abcl.

### Relationship between the Python runtimes

**Python (inferred)** imports parser, interpreter, AI, remote, and
dashboard from `../python-aipl/`.  All *runtime* features match
Python (annotated); only the **static type-checker** layer differs
(full Hindley-Milner instead of Phase 11+ annotation-driven checks).

---

## Sample programs

Number of `.abcl` sample programs reachable by each runtime
(core directory + AI integration + remote-actor demos):

| Category               | Py-A | Py-I | OCaml | JS-O | JS-B | JS-N | C  |
|------------------------|-----:|-----:|------:|-----:|-----:|-----:|---:|
| core samples           |  33  |  33  |  57   |  57  |   5  |   5  | 57 |
| AI integration samples |  11  |  11  |   8   |   8  |   0  |   0  |  8 |
| remote-actor samples   |   8  |   8  |   1   |   1  |   0  |   0  |  1 |
| **total**              | **52** | **52** | **66** | **66** | **5** | **5** | **66** |

Cross-cutting / not tied to a specific runtime:
- `aipl-self-host/`: 48 AIPL-in-AIPL self-host programs
- `docker/cross/samples/`: 4 cross-language interop samples

The C runtime processes the same `.abcl` files as OCaml via
`abcl2c`; of the 66 reachable samples, 48 currently pass the
`abcl2c` smoke test (the remaining 9 in `abclc/` have pre-existing
type ambiguities surfaced by our hard-fail policy).

### What each sample exercises

Samples are grouped by the language or infrastructure feature they
demonstrate.  The "Where" column points to the source directory;
the "Target" column lists the runtime(s) and codegen targets that
actually execute the sample.

Target abbreviations: **Py** = python-aipl / python-aipl-inferred;
**OCaml** = OCaml REPL (`abclc`); **C** = `abcl2c` → C + pthread;
**SDL2** = `abcl2c` → C + SDL2 GUI binary;
**Xinu** = `abcl2c --xinu` → Xinu-flavoured C;
**Py-gen** = `abcl2c --python` → stand-alone Python file;
**Pony** = `abcl2c --pony` → Pony actor source;
**Erlang** = `abcl2c --erlang` → Erlang `.erl` module;
**Go** = `abcl2c --go` → Go `main.go` source;
**Prolog** = `abcl2c --prolog` → SWI-Prolog `.pl` (threads + msg queues);
**JS-B** = browser-abcl; **JS-N** = node-aipl-server.

| Feature category | Sample(s) | Where | What it checks | Target |
|---|---|---|---|---|
| **Basic actor model** | `Hello`, `Counter`, `PingPong` | py-aipl + abclc | actor creation, `send`, field state, `self`-send | Py, OCaml, C, JS-B, JS-N |
| **now / future / await** | `NowFuture`, `CooperativeNowFuture`, `NowFutureDemo` | py-aipl/samples + samples-ai + abclc/ai-samples | three message-passing forms in one program | Py, OCaml, C, JS-B, JS-N |
| **Bounded mailboxes / select** | `BoundedBuffer`, `bounded_buffer{,_visual}` | py-aipl + abclc + browser-abcl | producer/consumer, selective receive, visualisation | Py, OCaml, C, JS-B, JS-N |
| **Dining philosophers** | `Philosophers`, `philosophers{-1,-2}`, `Philosophers5{,_debug,_trace,Gui,Py,Xinu}` | py-aipl + abclc + browser-abcl | fork as actor, deadlock-free serialisation, SDL/Python/Xinu codegen variants | Py, OCaml, C, SDL2, Py-gen, Xinu, JS-B, JS-N |
| **`become` (class swap)** | `become.abcl`, `bbecome.abcl` | abclc | runtime actor-class replacement | Py, OCaml |
| **`select` / selective receive** | `Channels.abcl`, `Channels2.abcl` | py-aipl/samples | typed channels, worker-pool with request/result | Py |
| **Method injection** | `MethodPatch.abcl` | py-aipl/samples | `add_method` / `remove_method` runtime patching | Py |
| **Dynamic compile** | `Dynamic.abcl`, `DynamicWorkerPool.abcl` | py-aipl/samples | `compile()` builtin → runtime class generation; worker pool driven by it | Py |
| **Top-level functions** | `Functions.abcl`, `Signatures.abcl` | py-aipl/samples | user functions, multiple overload signatures, typeof | Py |
| **Records** | `Records.abcl` | py-aipl/samples | `{a:int, b:string}` literal, dot-field access, structural typeof | Py |
| **Tuples** | `Tuples.abcl` | py-aipl/samples | positional, immutable, mixed slot types, nesting | Py |
| **Arrays** | `Arrays.abcl`, `MultiDimArrays.abcl` | py-aipl/samples | static-sized, multi-dim, dynamic sizes | Py |
| **Gradual type checker** | `Typecheck.abcl`, `Typecheck11{b,c,de}.abcl` | py-aipl/samples | Phase 11 → 11e progression: literals, call-site validation, unions/generics, narrowing, length-tagged arrays | Py |
| **Phase 11 typed counter** | `Phase11_TypedCounter.abcl` | abclc | typed annotations / generics / typeof narrowing | OCaml |
| **Phase 12 effects** | `Effects.abcl`, `Phase12_EffectsLog.abcl` | py-aipl + abclc | capability-based `!{fs,ai,net,mut}` system | Py (static), OCaml (sample) |
| **Phase 13 channels** | `Phase13_Channels.abcl` | abclc | CSP channels (design doc + runtime in Py) | Py (runtime), OCaml (sample) |
| **Phase 14 linear types** | `Linear.abcl`, `Linear2.abcl`, `Phase14_Linear.abcl` | py-aipl + abclc | use-after-move, DB transaction with linear handle | Py (static), OCaml (sample) |
| **Phase 15 owned fields** | `Owned.abcl`, `Owned_violations.abcl`, `Phase15_Owned.abcl` | py-aipl + abclc | `pub` field visibility, intentional violations | Py (static), OCaml (sample) |
| **Phase 16 transient cast** | `Transient.abcl`, `Transient_violation.abcl` | py-aipl/samples | runtime type cast at any-boundary | Py |
| **Phase 17 structured concurrency** | `Phase17_StructuredConc.abcl` | py-aipl/samples | `scope { future ... }` auto-joining | Py |
| **Session types / protocol traces** | `SessionTyped.abcl` | py-aipl/samples-ai | runtime-checked typed session protocols (arg + reply types); order-only protocol traces; AIOS service registry | Py |
| **AI integration (mock + real)** | `AIActor`, `AIChain`, `AIChainReal`, `AIHello`, `MultiProvider` | py-aipl/samples + samples-ai + abclc/ai-samples | LLM-backed actors; multi-provider; chained pipeline | Py, OCaml |
| **AI governance** | `Budgeted.abcl` | py-aipl/samples-ai + abclc/ai-samples | token budget, concurrency cap, fallback chain | Py, OCaml |
| **AI cooperative pattern** | `CooperativeNowFuture{,-jp,-jp-remote}`, `CooperativeSolve{,-jp,Remote,Remote-jp}`, `Reviewer.abcl`, `Fanout.abcl`, `PriorityFanout.abcl` | py-aipl/samples-ai + abclc/ai-samples | Planner→Solver→Reviewer; fan-out aggregator; priority routing | Py, OCaml |
| **Remote actors** | `client / server / coordinator / solver / verifier / reviewer_node*`, `RemoteCalcClient/Server` | py-aipl/samples-remote + abclc/samples-remote + abclc/ai-samples | HTTP cross-machine sends; HMAC-signed coordination | Py, OCaml |
| **Web / dashboard** | `web_calc.abcl`, `SiteGen.abcl` | abclc + py-aipl/samples | embedded HTTP gateway; static-site generator | Py (SiteGen), OCaml (web_calc) |
| **GUI / SDL2** | `Rotate{One,Three,Four}Lines{,Gui}`, `MultiLineSpin`, `Philosophers5Gui`, `BoundedBufferGui`, `DisasterReturnGui`, `LineDrawer`, `window.abcl` | abclc | SDL2-backed GUI codegen via abcl2c | SDL2 (via abcl2c) |
| **Python codegen target** | `BoundedBufferPy`, `Philosophers5Py`, `Rotate4LinesPy` | abclc | `abcl2c --python` emits stand-alone Python | Py-gen |
| **Xinu (embedded OS) target** | `BoundedBufferXinu`, `Philosophers5Xinu`, `Rotate4LinesXinu` | abclc | `abcl2c --xinu` emits Xinu-flavoured C | Xinu |
| **Pony codegen target** | `Hello`, `counter` (verified); `PingPong` (xfail — cross-actor globals not supported) | abclc | `abcl2c --pony` emits Pony source; `class` → `actor`, methods → `be`; two-step `_aipl_init` decouples construction from init body | Pony |
| **Erlang codegen target** | `Hello`, `counter` (verified); `PingPong` (xfail — `sender` not tracked) | abclc | `abcl2c --erlang` emits a single `.erl` module; `class` → spawn + receive loop; fields → loop args with versioned variables on assign; methods → `receive` clauses | Erlang |
| **Go codegen target** | `Hello`, `counter` (verified); `PingPong` (xfail) | abclc | `abcl2c --go` emits a single Go `main.go`; `class` → struct + goroutine `run()`; each method → typed message struct + `Method()` helper that pushes to a buffered `chan any` mailbox; dispatch via type switch in `run()` | Go |
| **Prolog codegen target** | `Hello`, `counter` (verified); `PingPong` (xfail) | abclc | `abcl2c --prolog` emits a single SWI-Prolog `.pl` file using `library(thread)`; `class` → `c_loop(Fields)` thread with `thread_get_message` + `Msg = m(Args) -> body ; ...` dispatch; expressions are hoisted into prolog goals (`X is A + B`, `format(atom(S), "~w~w", [A,B])`) | Prolog |
| **Drone / simulation** | `drone_simulator.abcl` | browser-abcl | obstacle-aware drone swarm with comm + view range | JS-B, JS-N |
| **Trace / minimal** | `H`, `P`, `T*`, `LD*`, `MS`, `AA`, `PP`, `PH`, `line*`, `Philosophers5_{debug,trace}` | abclc | reduced repro cases used during runtime / TLA+ / Spin model-checking | OCaml |

---

## Core language

| #   | Feature                                             | Py-A | Py-I | OCaml | JS-O | JS-B | JS-N | C    |
| --- | --------------------------------------------------- | :--: | :--: | :---: | :--: | :--: | :--: | :--: |
| 1   | **method injection** (`add_method`/`remove_method`) |  ✅  |  ✅  |  ❌   |  ❌  |  ❌  |  ❌  |  ❌  |
| 2   | `now` synchronous send                              |  ✅  |  ✅  |  ✅   |  ✅  |  ✅  |  ✅  |  ✅  |
| 3   | `future` async send                                 |  ✅  |  ✅  |  ✅   |  ✅  |  ✅  |  ✅  |  ✅  |
| 4   | `await` future block                                |  ✅  |  ✅  |  ✅   |  ✅  |  ✅  |  ✅  |  ✅  |
| 5   | `send` fire-and-forget                              |  ✅  |  ✅  |  ✅   |  ✅  |  ✅  |  ✅  |  ✅  |
| 6   | `become` actor class swap                           |  ✅  |  ✅  |  ✅   |  ✅  |  ❌  |  ❌  |  ❌  |
| 7   | `select` selective receive                          |  ✅  |  ✅  |  ✅   |  ✅  |  ✅  |  ✅  |  ❌  |
| 8   | top-level functions                                 |  ✅  |  ✅  |  🟡   |  🟡  |  ❌  |  ❌  |  ✅  |
| 9   | signatures / overloads                              |  ❌  |  ❌  |  ✅   |  ✅  |  ❌  |  ❌  |  ❌  |
| 10  | dynamic compile (`compile()`)                       |  ✅  |  ✅  |  ❌   |  ❌  |  ❌  |  ❌  |  ❌  |
| 11  | worker pool / `DynamicWorkerPool`                   |  ✅  |  ✅  |  ❌   |  ❌  |  🟡  |  🟡  |  ❌  |

## Type system

| #   | Feature                              | Py-A      | Py-I       | OCaml      | JS-O       | JS-B                       | JS-N                       | C                       |
| --- | ------------------------------------ | :-------: | :--------: | :--------: | :--------: | :------------------------: | :------------------------: | :---------------------: |
| 12  | type inference                       | 🟡 trace  | ✅ HM       | ✅ HM       | ✅ HM       | ✅ flow-sensitive          | ✅ flow-sensitive          | ✅ HM + specialization  |
| 13  | type annotations (`var x: int`)      | ✅        | 🟡 ignored  | ❌         | ❌         | ❌                         | ❌                         | ❌                      |
| 14  | records `{a: int, b: string}`        | ✅        | ✅          | ❌ type only | ❌       | ❌                         | ❌                         | 🟡 type only            |
| 15  | tuples `(1, "a")`                    | ✅        | ✅          | ❌         | ❌         | ❌                         | ❌                         | ❌                      |
| 16  | arrays (typed, multi-dim)            | ✅        | ✅          | ✅         | ✅         | 🟡                         | 🟡                         | 🟡                      |
| 17  | generics on functions                | ❌        | ✅ Forall   | 🟡 Forall  | 🟡         | ❌                         | ❌                         | ❌                      |

## Phase 11+ advanced features

The Python (inferred) variant runs HM only; the annotation-driven
Phase 11+ static checks that Python (annotated) performs are **not**
re-implemented.  Programs still execute at runtime via the inherited
interpreter, but the static guarantees from Phase 12 / 14 / 15 / 16
are lost.  Phase 13 (channels), Phase 17 (structured concurrency),
and the session-type / protocol-trace / AIOS-registry families are
runtime features, so they remain available in Py-I.

Session types here are **runtime-checked** and explicitly *separate
from* HM inference: they observe values flowing over the wire at
runtime and validate them against a declared protocol spec
(`"actor.method(arg_t1, ...) ! ret_type -> ..."`).  Violations are
recorded in `session_events()` and counted; the program does not
abort.

| #   | Feature                                    | Py-A | Py-I       | OCaml | JS-O | JS-B | JS-N | C    |
| --- | ------------------------------------------ | :--: | :--------: | :---: | :--: | :--: | :--: | :--: |
| 18  | channels (CSP-style) — Phase 13            |  ✅  |  ✅        |  ❌   |  ❌  |  ❌  |  ❌  |  ❌  |
| 19  | linear types / use-after-move — Phase 14   |  ✅  |  ❌ static  |  ❌   |  ❌  |  ❌  |  ❌  |  ❌  |
| 20  | owned/pub fields — Phase 15                |  ✅  |  ❌ static  |  ❌   |  ❌  |  ❌  |  ❌  |  ❌  |
| 21  | effects `!{fs,ai,net,mut}` — Phase 12      |  ✅  |  ❌ static  |  ❌   |  ❌  |  ❌  |  ❌  |  ❌  |
| 22  | structured concurrency `scope` — Phase 17  |  ✅  |  ✅        |  ❌   |  ❌  |  ❌  |  ❌  |  ❌  |
| 23  | transient cast at any-boundary — Phase 16  |  ✅  |  ❌ static  |  ❌   |  ❌  |  ❌  |  ❌  |  ❌  |
| 24  | **session types** (runtime-checked typed protocols) |  ✅  |  ✅        |  ❌   |  ❌  |  ❌  |  ❌  |  ❌  |
| 25  | protocol traces (order-only)               |  ✅  |  ✅        |  ❌   |  ❌  |  ❌  |  ❌  |  ❌  |
| 26  | AIOS service registry (alias-resolved send) |  ✅  |  ✅        |  ❌   |  ❌  |  ❌  |  ❌  |  ❌  |

## Networking / AI / infrastructure

| #   | Feature                                       | Py-A                       | Py-I                | OCaml         | JS-O          | JS-B         | JS-N                          | C        |
| --- | --------------------------------------------- | :------------------------: | :-----------------: | :-----------: | :-----------: | :----------: | :---------------------------: | :------: |
| 27  | remote actors (HTTP)                          | ✅                          | ✅                   | 🟡 no WS      | 🟡            | ❌           | 🟡 server itself, no client   | ✅ (via OCaml) |
| 28  | WebSocket                                     | ❌                          | ❌                   | ❌            | ❌            | ❌           | ❌                            | ❌       |
| 29  | AI integration (`ai_call`)                    | ✅ (stream, image)          | ✅                   | ✅            | ✅            | ✅ mock only | ✅ mock only                  | ✅       |
| 29a | `ai_call([provider,] prompt)` — int 1/2/3 = gemini/anthropic/openai (default: gemini auto) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ (via OCaml) |
| 29b | `now actor.m(...)` + `ai_call(...)` inside method  → reply gets blocking reply | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ (no `reply()` in C runtime) |
| 29c | `future actor.m(...)` + `await(f)` + `ai_call(...)` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ (no future slot in C runtime) |
| 29d | `send` + callback pattern (`send a.ask(rcv); ...; send rcv.got(reply)`) with `ai_call(...)` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| 30  | AI governance (budget / concurrent / fallback)| ✅                          | ✅                   | ✅            | ✅            | ❌           | ❌                            | ✅       |
| 31  | HMAC-signed remote send                       | ✅                          | ✅                   | ❌            | ❌            | ❌           | ❌                            | ✅       |
| 32  | persistent actor state                        | ✅ (`ABCL_NODE_STATE_FILE`) | ✅                   | ❌            | ❌            | ❌           | ❌                            | ❌       |
| 33  | live dashboard (SSE)                          | ✅                          | ✅                   | 🟡 polling    | 🟡            | ❌           | ❌                            | ✅       |
| 34  | `/api/typecheck` JSON endpoint                | ❌                          | ❌                   | ✅            | ✅            | ❌           | ✅                            | N/A      |
| 35  | `/api/run` JSON endpoint                      | ❌                          | ❌                   | ❌            | ❌            | ❌           | ✅                            | N/A      |

## Actor concurrency model

Every AIPL implementation runs each actor as a separate concurrent
unit, but the kind of unit differs by 3-4 orders of magnitude in
weight.  This affects how many actors a program can usefully
spawn, how messages interleave, and whether blocking I/O in one
actor stalls the whole runtime.

| Runtime / codegen target | Model                          | Per-actor unit                       | Source pointer |
|---|---|---|---|
| Python (annotated)       | **1:1 OS thread**              | `threading.Thread(daemon=True)`      | `aipl_runtime.py:92` |
| Python (inferred)        | **1:1 OS thread**              | (inherits from python-aipl)          | (re-uses interp) |
| OCaml                    | **1:1 OS thread**              | `Thread.create`                      | `eval_thread.ml:~1168` |
| JS-OCaml (server)        | **1:1 OS thread**              | (= OCaml backend threads)            | (= OCaml) |
| JS-Browser (browser-abcl)| **cooperative event loop**     | `setTimeout`-driven mailbox drain    | `runtime.js:~233` |
| JS-Node (node-aipl-server)| **cooperative event loop**    | (= browser-abcl runtime)             | `server.mjs` re-export |
| C (default)              | **1:1 OS thread**              | `pthread_create`                     | `c_translator.ml:~721,790` |
| C + SDL2                 | **1:1 OS thread**              | `pthread_create`                     | (same as default C) |
| C + Xinu                 | **1:1 OS process** (kernel-level) | Xinu `create()` + `ready()`       | `c_translator.ml:~1077` |
| C → Python codegen       | **1:1 OS thread**              | `threading.Thread` (`o._spawn()`)    | `c_translator.ml:~1847` |
| C → Pony codegen         | **M:N lightweight (runtime-scheduled)** | Pony actor (work-stealing)   | implicit in generated `actor` |
| C → Erlang codegen       | **M:N lightweight (BEAM)**     | BEAM process (`spawn(fun()->...end)`)| `c_translator.ml:~2413` |
| C → Go codegen           | **M:N lightweight (Go runtime)** | goroutine (`go c.run()`)           | `c_translator.ml:~2728` |
| C → Prolog codegen       | **1:1 OS thread**              | SWI thread (`thread_create/3`)        | `c_translator.ml:~3060` |

### Three concurrency tiers

- **1:1 OS thread / process** (Python, OCaml, C, C-SDL2, Xinu,
  C→Python, C→Prolog): each actor is a kernel-scheduled thread.
  Simple mental model; blocking I/O in one actor doesn't stall
  others.  Scales to ~100–1000 actors before kernel overhead
  dominates.
- **M:N lightweight** (Pony, Erlang, Go): actors are scheduled
  by the language runtime onto a small pool of OS threads.
  Scales to ~10⁵–10⁷ actors.  Blocking syscalls in one actor
  may stall its scheduler unless the runtime intercepts them
  (Erlang's BEAM intercepts; Go's runtime intercepts via
  `netpoll`; Pony's runtime requires non-blocking idioms).
- **Cooperative event loop** (browser-abcl, node-aipl-server):
  single OS thread; mailboxes are drained turn-by-turn through
  `setTimeout(0)` re-entry into the event loop.  No real
  parallelism, but message-level interleaving is preserved.
  A long synchronous computation in one actor *will* stall all
  others — by design, since this is the only concurrency model
  the browser DOM allows.

### Cross-cutting implication

The AIPL programming model (`send` / `now` / `future` / `await`)
is preserved across all three tiers — the choice of target
picks a point on the cost/scale curve without changing the
program text.  The same `.abcl` file:
- runs ~1000 actors fine on Python / OCaml / C (OS-thread tier);
- scales to millions of actors on Erlang / Go / Pony codegen;
- runs in a browser sandbox via JS-Browser at the cost of
  single-threaded execution.

---

## C-version-specific codegen targets

| #   | Target                                          | C    |
| --- | ----------------------------------------------- | :--: |
| 36  | C + pthread standalone binary                   | ✅   |
| 37  | C + SDL2 GUI binary (1178-line runtime)         | ✅   |
| 38  | Xinu embedded-OS target (`--xinu`)              | ✅   |
| 39  | Python target (`--python`)                      | ✅   |
| 40  | **Pony target (`--pony`)** — `class` → `actor`, methods → `be`, two-step `_aipl_init` | ✅   |
| 41  | **Erlang target (`--erlang`)** — `class` → spawn+receive loop, fields → loop args (versioned vars) | ✅   |
| 42  | **Go target (`--go`)** — `class` → struct + goroutine, methods → typed message structs + type-switch dispatch | ✅   |
| 43  | **Prolog target (`--prolog`)** — `class` → SWI thread + receive loop, methods → `Msg = m(...)` patterns, expressions hoisted to goals (`is/2`, `format(atom(...))`) | ✅   |

---

## Key observations

### Python (annotated) is the most feature-complete runtime (~28/30 ✅)
- All of Phase 11–17 (channels / linear / owned / effects / structured / transient)
- The only runtimes with **method injection** are the two Python variants
- The only runtimes with **dynamic compile** are again the two Python variants
- Full AI integration including streaming and images

### Python (inferred) is Python's HM-typed twin (~24/30 ✅)
- Runtime features match Python (annotated) exactly (shared interpreter)
- Trades the Phase 11+ annotation-driven static checks (effects /
  linear / owned / transient) for full Hindley-Milner inference
- Inferred types cross-verified against OCaml: identical on shared
  samples (Hello.abcl, counter.abcl)
- Method injection still works at runtime — HM inference treats
  `add_method` calls as gradual

### OCaml is the canonical core (~15/30 ✅)
- Phase 11+ features exist only as `.abcl` design-document samples,
  not implemented
- Solid `become` / `select` / HM inference
- Remote is HTTP only (no HMAC, no WebSocket)

### JS-OCaml (server) ≈ OCaml
- It's a thin HTTP client over the OCaml backend, so features inherit
- The only differentiator: the new `/api/typecheck` JSON endpoint

### JS-Browser (serverless, browser-abcl) is the minimal implementation (~8/30 ✅)
- Basic actor model + flow-sensitive type inference
- No `become`, no channels, no remote
- AI integration exists but is **mock only** (no real LLM)

### JS-Node (Node-server, NEW)
- Wraps the browser-abcl runtime inside a Node.js HTTP server
- Exposes `/api/typecheck` (matching the OCaml endpoint's JSON shape)
  and `/api/run` (executes a snippet and returns stdout)
- Runtime feature set is identical to browser-abcl; the value-add is
  having both the *type-checker* and the *interpreter* reachable
  from any HTTP client without spinning up a browser
- Uses the same flow-sensitive type inference as browser-abcl

### C version (~17/30 ✅) — surprisingly strong on infrastructure
- `become` and `select` are not implemented (codegen emits `/* unsupported */`)
- But it inherits OCaml's **HMAC**, **SSE**, **AI governance**, and
  adds **three additional codegen targets** (SDL2, Xinu, Python)
- Fields, parameters, and locals are specialized to native C types

### Method injection — a Python-family exclusive
- Both Python variants use mutable method dispatch tables that can
  be mutated at runtime via `add_method` / `remove_method`
- Other runtimes substitute `become` (whole-class swap)
- `browser-abcl` / `node-aipl-server` lack even `become` (pure actor
  execution)

### Type inference cross-verification

For shared samples (`abclc/Hello.abcl`, `abclc/counter.abcl`),
the three HM-based runtimes (**OCaml**, **Python-inferred**, **C**)
produce **identical inferred types**:

```
Hello:   count : float
         init  : (int) -> unit
         greet : () -> unit
         inc   : () -> unit

Counter: count : float
         inc   : () -> unit
         dec   : (float) -> unit    ← monomorphized from `'a` via call site
```

The flow-sensitive variants (**JS-Browser**, **JS-Node**) reach the
same answers on the same samples within the limits of their algorithm
— field types match, but they do not produce method signature
schemes the same way.

### Phase 11+ implementation gap
- The full Phase 11–17 stack is implemented only in Python (annotated)
- These represent AIPL's language-evolution frontier; Python
  (annotated) serves as the research runtime
- Python (inferred) keeps the runtime side but trades the static
  checks for HM-style polymorphic inference — a different research
  axis (declarative typing vs annotated capabilities)

---

*Generated 2026-05-13.  Includes the `python-aipl-inferred` runtime
(commit `270f291`) and the `node-aipl-server` runtime (this commit).
For source pointers, run `grep` against the files listed in each
runtime's source column.*
