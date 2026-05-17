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
| C (aipl2c)             | `src/aipl2c.ml` codegen + `src/abcl_gui_runtime.c` |

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
`aipl2c`; of the 66 reachable samples, 48 currently pass the
`aipl2c` smoke test (the remaining 9 in `abclc/` have pre-existing
type ambiguities surfaced by our hard-fail policy).

### What each sample exercises

Samples are grouped by the language or infrastructure feature they
demonstrate.  The "Where" column points to the source directory;
the "Target" column lists the runtime(s) and codegen targets that
actually execute the sample.

Target abbreviations: **Py** = python-aipl / python-aipl-inferred;
**OCaml** = OCaml REPL (`abclc`); **C** = `aipl2c` → C + pthread;
**SDL2** = `aipl2c` → C + SDL2 GUI binary;
**Xinu** = `aipl2c --xinu` → Xinu-flavoured C;
**Py-gen** = `aipl2c --python` → stand-alone Python file;
**Pony** = `aipl2c --pony` → Pony actor source;
**Erlang** = `aipl2c --erlang` → Erlang `.erl` module;
**Go** = `aipl2c --go` → Go `main.go` source;
**Prolog** = `aipl2c --prolog` → SWI-Prolog `.pl` (threads + msg queues);
**LLVM** = `aipl2c --llvm` → C with clang `__attribute__((hot/cold))` + LLVM/clang build instructions for native binary or `.ll` IR;
**OpenMP** = `aipl2c --openmp` → C + pthread but the initial actor-spawn loop runs as `#pragma omp parallel for` and message-counter updates use `#pragma omp atomic` (build with `gcc-fopenmp`);
**JS-B** = browser-abcl; **JS-N** = node-aipl-server.

| Feature category | Sample(s) | Where | What it checks | Target |
|---|---|---|---|---|
| **Basic actor model** | `Hello`, `Counter`, `PingPong` | py-aipl + abclc | actor creation, `send`, field state, `self`-send | Py, OCaml, C, JS-B, JS-N |
| **now / future / await** | `NowFuture`, `CooperativeNowFuture`, `NowFutureDemo` | py-aipl/samples + samples-ai + abclc/ai-samples | three message-passing forms in one program | Py, OCaml, C, JS-B, JS-N |
| **Bounded mailboxes / select** | `BoundedBuffer`, `bounded_buffer{,_visual}` | py-aipl + abclc + browser-abcl | producer/consumer, selective receive, visualisation | Py, OCaml, C, JS-B, JS-N |
| **Dining philosophers** | `Philosophers`, `philosophers{-1,-2}`, `Philosophers5{,_debug,_trace,Gui,Py,Xinu}` | py-aipl + abclc + browser-abcl | fork as actor, deadlock-free serialisation, SDL/Python/Xinu codegen variants | Py, OCaml, C, SDL2, Py-gen, Xinu, JS-B, JS-N |
| **`become` (class swap)** | `become.abcl`, `bbecome.abcl` | abclc | runtime actor-class replacement | Py, OCaml |
| **`select` / selective receive** | `Channels.abcl`, `Channels2.abcl` | py-aipl/samples | typed channels, worker-pool with request/result | Py |
| **Method injection** | `MethodPatch.abcl` | py-aipl/samples + abclc/ | `add_method` / `remove_method` runtime patching | Py, OCaml |
| **Dynamic compile** | `Dynamic.abcl`, `DynamicWorkerPool.abcl` | py-aipl/samples + abclc/ | `compile()` builtin → runtime class generation; worker pool driven by it | Py, OCaml |
| **Top-level functions** | `Functions.abcl`, `Signatures.abcl` | py-aipl/samples + abclc/ | user functions, multiple overload signatures, typeof | Py, OCaml |
| **Records** | `Records.abcl` | py-aipl/samples + abclc/ | `{a:int, b:string}` literal, dot-field access, structural typeof | Py, OCaml |
| **Tuples** | `Tuples.abcl` | py-aipl/samples + abclc/ | positional, immutable, mixed slot types, nesting | Py, OCaml |
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
| **GUI / SDL2** | `Rotate{One,Three,Four}Lines{,Gui}`, `MultiLineSpin`, `Philosophers5Gui`, `BoundedBufferGui`, `DisasterReturnGui`, `LineDrawer`, `window.abcl` | abclc | SDL2-backed GUI codegen via aipl2c | SDL2 (via aipl2c) |
| **Python codegen target** | `BoundedBufferPy`, `Philosophers5Py`, `Rotate4LinesPy` | abclc | `aipl2c --python` emits stand-alone Python | Py-gen |
| **Xinu (embedded OS) target** | `BoundedBufferXinu`, `Philosophers5Xinu`, `Rotate4LinesXinu` | abclc | `aipl2c --xinu` emits Xinu-flavoured C | Xinu |
| **Pony codegen target** | `Hello`, `counter` (verified); `PingPong` (xfail — cross-actor globals not supported) | abclc | `aipl2c --pony` emits Pony source; `class` → `actor`, methods → `be`; two-step `_aipl_init` decouples construction from init body | Pony |
| **Erlang codegen target** | `Hello`, `counter` (verified); `PingPong` (xfail — `sender` not tracked) | abclc | `aipl2c --erlang` emits a single `.erl` module; `class` → spawn + receive loop; fields → loop args with versioned variables on assign; methods → `receive` clauses | Erlang |
| **Go codegen target** | `Hello`, `counter` (verified); `PingPong` (xfail) | abclc | `aipl2c --go` emits a single Go `main.go`; `class` → struct + goroutine `run()`; each method → typed message struct + `Method()` helper that pushes to a buffered `chan any` mailbox; dispatch via type switch in `run()` | Go |
| **Prolog codegen target** | `Hello`, `counter` (verified); `PingPong` (xfail) | abclc | `aipl2c --prolog` emits a single SWI-Prolog `.pl` file using `library(thread)`; `class` → `c_loop(Fields)` thread with `thread_get_message` + `Msg = m(Args) -> body ; ...` dispatch; expressions are hoisted into prolog goals (`X is A + B`, `format(atom(S), "~w~w", [A,B])`) | Prolog |
| **LLVM codegen target** | `Hello`, `counter` (verified) | abclc | `aipl2c --llvm` emits the same C as the default backend with clang-specific `__attribute__((hot))` / `__attribute__((cold))` annotations + a header banner listing `clang -O2 -pthread`, `clang -emit-llvm -S` (text IR), and `clang -emit-llvm -c` + `lli` flows | LLVM |
| **OpenMP codegen target** | `Hello`, `counter` (verified) | abclc | `aipl2c --openmp` emits C + `<omp.h>`; the initial spawn loop becomes `#pragma omp parallel for schedule(dynamic)` and `messages_processed++` uses `#pragma omp atomic` instead of the dedicated mutex.  Build with `gcc-15 -fopenmp` or `clang -fopenmp`.  pthreads still drive per-actor message loops (compatible with OpenMP) | OpenMP |
| **Drone / simulation** | `drone_simulator.abcl` | browser-abcl | obstacle-aware drone swarm with comm + view range | JS-B, JS-N |
| **Trace / minimal** | `H`, `P`, `T*`, `LD*`, `MS`, `AA`, `PP`, `PH`, `line*`, `Philosophers5_{debug,trace}` | abclc | reduced repro cases used during runtime / TLA+ / Spin model-checking | OCaml |

---

## Core language

| #   | Feature                                             | Py-A | Py-I | OCaml | JS-O | JS-B | JS-N | C    |
| --- | --------------------------------------------------- | :--: | :--: | :---: | :--: | :--: | :--: | :--: |
| 1   | **method injection** (`add_method`/`remove_method`) |  ✅  |  ✅  |  ✅   |  ✅  |  ❌  |  ❌  |  ❌  |
| 2   | `now` synchronous send                              |  ✅  |  ✅  |  ✅   |  ✅  |  ✅  |  ✅  |  ✅  |
| 3   | `future` async send                                 |  ✅  |  ✅  |  ✅   |  ✅  |  ✅  |  ✅  |  ✅  |
| 4   | `await` future block                                |  ✅  |  ✅  |  ✅   |  ✅  |  ✅  |  ✅  |  ✅  |
| 5   | `send` fire-and-forget                              |  ✅  |  ✅  |  ✅   |  ✅  |  ✅  |  ✅  |  ✅  |
| 6   | `become` actor class swap                           |  ✅  |  ✅  |  ✅   |  ✅  |  ❌  |  ❌  |  ❌  |
| 7   | `select` selective receive                          |  ✅  |  ✅  |  ✅   |  ✅  |  ✅  |  ✅  |  ❌  |
| 8   | top-level functions                                 |  ✅  |  ✅  |  ✅   |  ✅  |  ❌  |  ❌  |  ✅  |
| 9   | signatures / overloads                              |  ❌  |  ❌  |  ✅   |  ✅  |  ❌  |  ❌  |  ❌  |
| 10  | dynamic compile (`compile()`)                       |  ✅  |  ✅  |  ✅   |  ✅  |  ❌  |  ❌  |  ❌  |
| 11  | worker pool / `DynamicWorkerPool`                   |  ✅  |  ✅  |  ✅   |  ✅  |  🟡  |  🟡  |  ❌  |
| 12a | text file I/O (`read_file`/`write_file`/`append_file`/`file_exists`) |  ✅  |  ✅  |  ✅   |  ✅  |  ✅¹  |  ✅¹  |  ❌  |
| 12b | image I/O (`image_create`/`image_load`/`image_save`/`image_size`/`image_pixel`/`image_set_pixel`) |  ✅²  |  ✅²  |  ✅³  |  ✅³  |  ✅¹³  |  ✅¹³  |  ❌  |

¹ JS-B/JS-N expose the I/O builtins through the runtime, but they only
work when the host injects Node's `fs` (server.mjs does this
automatically; in the browser the calls throw "not available").

² Py-A/Py-I use Pillow → PNG/JPEG/GIF/WebP via magic bytes.

³ OCaml / JS-O / JS-B / JS-N use a pure-runtime PPM (P6) backend (RGBA
in memory, alpha dropped on save, viewable in Preview.app / GIMP /
ImageMagick).  PNG would require an external decoder library.

## Type system

| #   | Feature                              | Py-A      | Py-I       | OCaml      | JS-O       | JS-B                       | JS-N                       | C                       |
| --- | ------------------------------------ | :-------: | :--------: | :--------: | :--------: | :------------------------: | :------------------------: | :---------------------: |
| 12  | type inference                       | 🟡 trace  | ✅ HM       | ✅ HM       | ✅ HM       | ✅ flow-sensitive          | ✅ flow-sensitive          | ✅ HM + specialization  |
| 13  | type annotations (`var x: int`)      | ✅        | 🟡 ignored  | ✅         | ✅         | ❌                         | ❌                         | ❌                      |
| 14  | records `{a: int, b: string}`        | ✅        | ✅          | ✅         | ✅         | ❌                         | ❌                         | 🟡 type only            |
| 15  | tuples `(1, "a")`                    | ✅        | ✅          | ✅         | ✅         | ❌                         | ❌                         | ❌                      |
| 16  | arrays (typed, multi-dim)            | ✅        | ✅          | ✅         | ✅         | ✅                         | ✅                         | 🟡                      |
| 17  | generics on functions                | ❌        | ✅ Forall   | ✅ Forall  | ✅         | ❌                         | ❌                         | ❌                      |

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

## Phase C–E2 type inference (Python annotated only, added 2026-05-17/18)

Phase 11–17 の checker layer に加え、Python (annotated) ランタイムは
別モジュール `aipl_inference.py` (~1255 LOC) に **constraint-based
Hindley–Milner + Z3 refinement** 推論系を持つ。Py-I (`python-aipl-inferred/`)
は依然 trace-based HM のままで、これらの新 phase は **取り込まれていない**。

| ID    | Feature                                            | Py-A | Py-I | OCaml | JS-O | JS-B | JS-N | C   | 関連レポート                          |
| ----- | -------------------------------------------------- | :--: | :--: | :---: | :--: | :--: | :--: | :-: | ------------------------------------- |
| CE-1  | Phase C: constraint-based HM + Z3 refinement (Int) |  ✅  |  ❌  |  ❌   |  ❌  |  ❌  |  ❌  | ❌  | `PHASE_C_REPORT.md`                   |
| CE-2  | Phase D-1: cross-class inference                   |  ✅  |  ❌  |  ❌   |  ❌  |  ❌  |  ❌  | ❌  | `PHASE_D_REPORT.md`                   |
| CE-3  | Phase E-α: `where` 句 in AIPL grammar              |  ✅  |  ❌  |  ❌   |  ❌  |  ❌  |  ❌  | ❌  | `PHASE_E_REPORT.md`                   |
| CE-4  | Phase E-β: actor field 共有 (method 横断)         |  ✅  |  ❌  |  ❌   |  ❌  |  ❌  |  ❌  | ❌  | `PHASE_E_BETA_REPORT.md`              |
| CE-5  | Phase E-γ: record structural typing                |  ✅  |  ❌  |  ❌   |  ❌  |  ❌  |  ❌  | ❌  | `PHASE_E_GAMMA_REPORT.md`             |
| CE-6  | Phase E-γ-R: Real / Rat refinement (Z3 Real)       |  ✅  |  ❌  |  ❌   |  ❌  |  ❌  |  ❌  | ❌  | `PHASE_E_GAMMA_R_REPORT.md`           |
| CE-7  | Phase E-2: typeck × inference 統合 CLI `--check`   |  ✅  |  ❌  |  ❌   |  ❌  |  ❌  |  ❌  | ❌  | `PHASE_E_2_REPORT.md`                 |
| CE-8  | `--infer` standalone CLI                           |  ✅  |  ❌  |  ❌   |  ❌  |  ❌  |  ❌  | ❌  | (Phase D-4)                           |
| CE-9  | refinement vacuously-false detection (declaration-time) | ✅ |  ❌  |  ❌   |  ❌  |  ❌  |  ❌  | ❌  | E-α §2.3 (Z3 unsat check on declared type) |

サンプル: `aice-pi-evolution/experiments/2026-05-17_aipl_v2_type_inference/samples/feature_{a..g}/` (7 feature × 3 = 21 demo + 27/27 unit tests).

OCaml ランタイムも HM 推論を持つが (#12 で ✅)、refinement (`where` 句) と
Z3 backend には対応していない。OCaml への移植は今後の課題。

## AIPL v2 Distributed runtime (`aipl_dist`, added 2026-05-18)

進化計算 (MAP-Elites 8 seed × 30 gen × 2 run) で発見された分散ランタイム
設計 (I0003 balanced / I0023 hang-resilience / I0036 Erlang OTP の 3 候補)
を `aipl_dist.py` (591 LOC) として実装。AIPL 言語仕様は不変、既存サンプル
は無改変で同じ挙動。**`AIPL_DIST_ENABLE=1` で全機能 opt-in**。

| ID    | Feature                                              | Py-A | Py-I | OCaml | JS-O | JS-B | JS-N | C   | env var                                       |
| ----- | ---------------------------------------------------- | :--: | :--: | :---: | :--: | :--: | :--: | :-: | --------------------------------------------- |
| DR-1  | I-1 `env_var_routing` (actor → tag table)            |  ✅  |  ❌  |  ✅   |  ✅  |  ❌  |  ❌  | ❌  | `AIPL_ROUTE="Name:tag,..."`                   |
| DR-2  | I-2 `structured_log` (ND-JSON / event)               |  ✅  |  ❌  |  ✅   |  ✅  |  ❌  |  ❌  | ❌  | `AIPL_DIST_LOG_FILE=/path`                    |
| DR-3  | I-3 `token_budget_aware` (sliding RPM/TPM gate)      |  ✅  |  ❌  |  ✅   |  ✅  |  ❌  |  ❌  | ❌  | `AIPL_DIST_RPM` / `AIPL_DIST_TPM`             |
| DR-4  | I-4 `checkpoint_and_resume` (atomic save/restore)    |  ✅  |  ❌  |  ✅   |  ✅  |  ❌  |  ❌  | ❌  | `AIPL_DIST_CHECKPOINT_DIR`                    |
| DR-5  | IQ `quarantine_and_skip` (auto-isolate failures)     |  ✅  |  ❌  |  ✅   |  ✅  |  ❌  |  ❌  | ❌  | `AIPL_DIST_QUARANTINE_TTL=60`                 |
| DR-6  | IM-1 `quorum_replicate` (parallel multi-provider)    |  ✅  |  ❌  |  ✅   |  ✅  |  ❌  |  ❌  | ❌  | `AIPL_DIST_QUORUM_PROVIDERS="o,a,g"`          |
| DR-7  | IM-2 `subtree_quarantine` (Erlang OTP blast-radius)  |  ✅  |  ❌  |  ✅   |  ✅  |  ❌  |  ❌  | ❌  | `AIPL_DIST_SUBTREE_QUARANTINE=1`              |
| DR-8  | spawn-tree tracking (parent inference, TLS-auto)     |  ✅  |  ❌  |  ✅   |  ✅  |  ❌  |  ❌  | ❌  | (auto, AIPL_DIST_ENABLE=1)                    |
| DR-9  | runtime hooks (interp / actor / call_ai) — opt-in    |  ✅  |  ❌  |  ✅   |  ✅  |  ❌  |  ❌  | ❌  | (auto)                                        |

OCaml は Phase O-1.5 で全 9 機能 ✅ 達成 (DR-3/6 の auto-wiring
into `Ai.call_gemini` 完了, DR-8 は per-thread `current_actor` TLS
で parent を自動取得).  JS-O はこれを継承.

**実装位置**:
- `src/python-aipl/aipl_dist.py` (591 LOC, 新規)
- `src/python-aipl/aipl_interp.py` (+27 行, spawn hook)
- `src/python-aipl/aipl_runtime.py` (+13 行, error hook)
- `src/python-aipl/aipl_ai.py` (+13 行, budget hook)

**サンプル**: `aice-pi-evolution/experiments/2026-05-17_aipl_v2_type_inference/IMPL_I0003_MVP/samples/` (8 feature × 3 = 24 demo + 27/27 unit tests).

**設計探索の出自**: 同 dir の `AIPL_v2_Distributed.{aice,ga.json,schema.json}` を
MAP-Elites で 24 min × 2 run。詳細は `IMPL_I0003_MVP/IMPL_DESIGN.md` 〜
`IMPL_I0036_REPORT.md` 参照。

> なお Py-I (inferred) ランタイムは `aipl_dist` を import しないが、import
> しても `AIPL_DIST_ENABLE=0` 時の no-op パスが効くので副作用ゼロ。将来的に
> Py-I 側で env var を ON にすれば同じ機能群を共有できる構造。
> OCaml 側への移植は run-time hooks 層を別途設計する必要があり、今後の課題。

## Networking / AI / infrastructure

| #   | Feature                                       | Py-A                       | Py-I                | OCaml         | JS-O          | JS-B         | JS-N                          | C        |
| --- | --------------------------------------------- | :------------------------: | :-----------------: | :-----------: | :-----------: | :----------: | :---------------------------: | :------: |
| 27  | remote actors (HTTP)                          | ✅                          | ✅                   | ✅¹           | ✅¹           | ❌           | 🟡 server itself, no client   | ✅ (via OCaml) |
| 28  | WebSocket                                     | ✅ (`websockets` lib + `ws_listen` / `ws_send` / `ws_close` builtins) | ✅ (= Py-A; HM prelude registered) | ✅ (built-in `web_gateway.ml`, 40+ LOC, verified handshake 101) | ✅ (via OCaml backend) | ✅ (browser-native `WebSocket`) | ✅ (`ws` lib, `/ws?sid=` endpoint + `/api/broadcast`) | ✅ (`abcl_ws_runtime.c` + libwebsockets, `ws_listen` / `ws_send` / `ws_close` extern) |
| 29  | AI integration (`ai_call`)                    | ✅ (stream, image)          | ✅                   | ✅            | ✅            | ✅ mock only | ✅ mock only                  | ✅       |
| 29a | `ai_call([provider,] prompt)` — int 1/2/3 = gemini/anthropic/openai (default: gemini auto) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ (via OCaml) |
| 29b | `now actor.m(...)` + `ai_call(...)` inside method  → reply gets blocking reply | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ (no `reply()` in C runtime) |
| 29c | `future actor.m(...)` + `await(f)` + `ai_call(...)` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ (no future slot in C runtime) |
| 29d | `send` + callback pattern (`send a.ask(rcv); ...; send rcv.got(reply)`) with `ai_call(...)` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| 30  | AI governance (budget / concurrent / fallback)| ✅                          | ✅                   | ✅            | ✅            | ❌           | ❌                            | ✅       |
| 31  | HMAC-signed remote send                       | ✅                          | ✅                   | ✅²           | ✅²           | ❌           | ❌                            | ✅       |

¹ OCaml's remote actor client (`src/remote_client.ml`) supports all
three send forms — `send` (fire-and-forget), `now` (blocking, returns
reply), and `future` (parallel; await for value) — and recovers
gracefully from ECONNREFUSED/timeouts (logged to stderr, calling
actor stays alive).  Verified end-to-end by `src/test_remote_actor.sh`.
JS-O inherits this through the OCaml backend.

² Pure-OCaml HMAC-SHA256 (`src/hmac_sha256.ml`, verified against
RFC 6234 / RFC 4231 test vectors) protects cross-process traffic
when `ABCL_REMOTE_SECRET` is set on both sides.  Every outgoing
POST carries `X-ABCL-Sig: <hex>`; `verify_hmac_or_reject` in
`web_gateway.ml` returns 401 on missing / mismatched signatures.
Wire-compatible with `python-aipl/aipl_remote.py` and the C
runtime.  The previous fork-an-openssl receiver implementation is
replaced by the in-process pure-OCaml version (no subprocess
overhead per request).
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

### Python (annotated) — the research frontier (≈28/32 ✅)
- All of Phase 11–17 (channels / linear / owned / effects / structured / transient)
- Full AI integration including streaming and multimodal images
- Pillow-backed image I/O (PNG/JPEG/GIF/WebP via magic-byte detection)

### Python (inferred) — Python's HM-typed twin (≈25/32 ✅)
- Runtime features match Python (annotated) exactly (shared interpreter)
- Trades Phase 11+ annotation-driven static checks (effects /
  linear / owned / transient) for full Hindley-Milner inference
- Cross-verified against OCaml: identical inferred types on shared
  samples (Hello.abcl, counter.abcl)

### OCaml — feature parity with Python on the core (≈24/32 ✅)
- Recently caught up on **method injection** (`add_method`/`remove_method`),
  **dynamic compile** (`compile()` + `spawn()`), **top-level functions**
  (`function f(...) -> T { return ...; }`), **generics** (`function id(x: T) -> T`),
  **type annotations** (`var x: int`), **records & tuples**, **sized
  arrays** (`var x[N][M]`), **text/image file I/O** (PPM backend for images).
- Phase 11+ effect/linear/owned/transient features still only exist as
  `.abcl` design-document samples — not enforced statically.
- Solid `become` / `select` / WebSocket (built into `web_gateway.ml`)
  and HTTP remote actor calls (send / now / future, error-tolerant)
  with **HMAC-signed traffic** (`ABCL_REMOTE_SECRET` env, pure-OCaml
  HMAC-SHA256 in `src/hmac_sha256.ml`, wire-compatible with Python
  and C).

### JS-OCaml (server) ≈ OCaml
- A thin HTTP client (`src/app.js` etc.) over the OCaml backend
  exposed by `web_gateway.ml`. **Every OCaml-side feature is reachable
  via `/api/repl`**, so method injection / dynamic compile / top-level
  functions / generics / type annotations / file & image I/O all work
  from a browser or `curl` without code changes.
- The OCaml-specific differentiator: the `/api/typecheck` JSON endpoint.

### JS-Browser (serverless, browser-abcl) — minimal in-browser engine (≈12/32 ✅)
- Basic actor model + flow-sensitive type inference
- Plus **sized arrays** (`var x[N]`), **text & image file I/O**
  (host-injected `fs`; throws in browsers)
- No `become`, no channels, no remote, no method injection
- AI integration exists but is **mock only** (no real LLM)

### JS-Node (Node-server) ≈ JS-Browser + fs
- Wraps the browser-abcl runtime inside a Node.js HTTP server
  (`src/node-aipl-server/server.mjs`); auto-injects Node's `fs` so text
  & image I/O builtins work
- Exposes `/api/typecheck` and `/api/run` for headless use
- Same flow-sensitive type inference as browser-abcl

### C codegen — broadest target diversity (≈19/32 ✅)
- `become` and `select` are codegen-unsupported (emit `/* unsupported */`)
- But it inherits OCaml's **HMAC**, **SSE**, **AI governance**
- **9 backends** from one front-end:
  - C + pthread (default)
  - **C + LLVM/clang** (`--llvm`, attaches `__attribute__((hot/cold))`
    + headers for `clang -emit-llvm`)
  - **C + OpenMP** (`--openmp`, `#pragma omp parallel for` spawn loop +
    `#pragma omp atomic` counter)
  - C + SDL2 (GUI demos)
  - Xinu / Python / Pony / Erlang / Go / SWI-Prolog
- Fields, parameters, and locals are specialised to native C types
  via HM inference + per-class field-type registry

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

### Post-Phase-11 (added 2026-05-17/18)

| 領域 | Py-A 達成 | 他ランタイム | 関連セクション |
|---|---|---|---|
| Phase C–E2 型推論 (HM + Z3 refinement) | 9/9 | 0/9 | CE-1 〜 CE-9 |
| AIPL v2 Distributed (`aipl_dist`) | 9/9 | **OCaml 9/9 完全達成** (= JS-O も同等) | DR-1 〜 DR-9 |

OCaml は Phase O-1 + O-1.5 で 9/9 完了。詳細は
[`docs/OCAML_PORT_ROADMAP.md`](./OCAML_PORT_ROADMAP.md) §2. 残るは
Phase C-E2 (CE-1〜9, O-2.a〜O-2.f, ~5 セッション想定).

**Py-A 単独で進化計算由来の 18 機能が opt-in 利用可能** (両方とも
`AIPL_DIST_ENABLE=1` または `--check` / `--infer` で発火、デフォルトは
従来挙動と同一)。OCaml 側への移植は今後の課題:

- 型推論側: `--infer` の HM-with-refinement を OCaml HM 推論 (`src/infer.ml`)
  に統合できれば CE-1, CE-2, CE-4 あたりは取り込み可能。`where` 句 (CE-3)
  は OCaml lexer / parser の修正が必要。Z3 backend (CE-1, CE-6, CE-9) は
  OCaml から呼び出すなら ZMQ 越し or 別プロセス via JSON が現実的。
- ランタイム側: DR-1 / DR-2 / DR-4 / DR-5 / DR-8 / DR-9 は OCaml `eval_thread.ml`
  + `aipl_remote.ml` への hook 追加 (~200 LOC) で実装可能。DR-3 (token budget)
  と DR-6 (quorum) は AI client 層が必要。DR-7 (subtree) は spawn-tree
  registry が要る。

---

*Generated 2026-05-14, updated 2026-05-18.*  Cumulative through:

- OCaml feature catch-up (records / tuples / dynamic compile / method
  injection / top-level functions / generics / type annotations / sized
  arrays / text & image I/O).
- C-codegen LLVM / OpenMP targets.
- The `python-aipl-inferred` runtime (commit `270f291`).
- The `node-aipl-server` runtime.
- **Phase C–E2 constraint-based HM + Z3 refinement** (`aipl_inference.py`,
  1255 LOC; sections CE-1..CE-9).
- **AIPL v2 Distributed runtime** (`aipl_dist.py`, 591 LOC; sections
  DR-1..DR-9), discovered by MAP-Elites GA + MVP-implemented for
  I0003 / I0023 / I0036 winners.

For source pointers, run `grep` against the files listed in each
runtime's source column.
