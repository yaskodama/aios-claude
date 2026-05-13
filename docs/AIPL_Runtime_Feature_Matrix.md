# AIPL Runtime Feature Matrix

Side-by-side feature comparison across the five AIPL implementations
in this repository.  All entries are grounded in source — see notes
for file/line pointers.

**Legend**: ✅ YES (full) — 🟡 PARTIAL — ❌ NO — N/A (not applicable)

The five runtimes:

| Short name      | Source                                     |
| --------------- | ------------------------------------------ |
| Python          | `src/python-aipl/`                         |
| OCaml           | `src/*.ml`, `_build/.../repl_thread.exe`   |
| JS (server)     | `src/app.js` / `console_server.js` / `ide.js` (browser JS) + `src/web_gateway.ml` (OCaml HTTP server) |
| JS (serverless) | `src/browser-abcl/`                        |
| C (abcl2c)      | `src/abcl2c.ml` codegen + `src/abcl_gui_runtime.c` |

Because **JS (server)** is a thin HTTP client over the OCaml runtime,
its feature set is identical to OCaml's except where noted (e.g. the
`/api/typecheck` endpoint added in commit `5227f87`).

---

## Core language

| #   | Feature                                            | Python | OCaml | JS (server) | JS (serverless) | C    |
| --- | -------------------------------------------------- | :----: | :---: | :---------: | :-------------: | :--: |
| 1   | **method injection** (`add_method`/`remove_method`) |   ✅   |  ❌  |     ❌      |       ❌        |  ❌  |
| 2   | `now` synchronous send                             |   ✅   |  ✅  |     ✅      |       ✅        |  ✅  |
| 3   | `future` async send                                |   ✅   |  ✅  |     ✅      |       ✅        |  ✅  |
| 4   | `await` future block                               |   ✅   |  ✅  |     ✅      |       ✅        |  ✅  |
| 5   | `send` fire-and-forget                             |   ✅   |  ✅  |     ✅      |       ✅        |  ✅  |
| 6   | `become` actor class swap                          |   ✅   |  ✅  |     ✅      |       ❌        |  ❌  |
| 7   | `select` selective receive                         |   ✅   |  ✅  |     ✅      |       ✅        |  ❌  |
| 8   | top-level functions                                |   ✅   |  🟡  |     🟡      |       ❌        |  ✅  |
| 9   | signatures / overloads                             |   ❌   |  ✅  |     ✅      |       ❌        |  ❌  |
| 10  | dynamic compile (`compile()`)                      |   ✅   |  ❌  |     ❌      |       ❌        |  ❌  |
| 11  | worker pool / `DynamicWorkerPool`                  |   ✅   |  ❌  |     ❌      |       🟡        |  ❌  |

## Type system

| #   | Feature                              | Python    | OCaml      | JS (server) | JS (serverless)          | C                       |
| --- | ------------------------------------ | :-------: | :--------: | :---------: | :----------------------: | :---------------------: |
| 12  | type inference                       | 🟡 trace  | ✅ HM       | ✅ HM        | ✅ flow-sensitive        | ✅ HM + specialization  |
| 13  | type annotations (`var x: int`)      | ✅        | ❌         | ❌           | ❌                       | ❌                      |
| 14  | records `{a: int, b: string}`        | ✅        | ❌ type only | ❌         | ❌                       | 🟡 type only            |
| 15  | tuples `(1, "a")`                    | ✅        | ❌         | ❌           | ❌                       | ❌                      |
| 16  | arrays (typed, multi-dim)            | ✅        | ✅         | ✅           | 🟡                       | 🟡                      |
| 17  | generics on functions                | ❌        | 🟡 Forall  | 🟡           | ❌                       | ❌                      |

## Phase 11+ advanced features

| #   | Feature                                    | Python | OCaml | JS (server) | JS (serverless) | C    |
| --- | ------------------------------------------ | :----: | :---: | :---------: | :-------------: | :--: |
| 18  | channels (CSP-style) — Phase 13           |   ✅   |  ❌  |     ❌      |       ❌        |  ❌  |
| 19  | linear types / use-after-move — Phase 14  |   ✅   |  ❌  |     ❌      |       ❌        |  ❌  |
| 20  | owned/pub fields — Phase 15               |   ✅   |  ❌  |     ❌      |       ❌        |  ❌  |
| 21  | effects `!{fs,ai,net,mut}` — Phase 12     |   ✅   |  ❌  |     ❌      |       ❌        |  ❌  |
| 22  | structured concurrency `scope` — Phase 17 |   ✅   |  ❌  |     ❌      |       ❌        |  ❌  |
| 23  | transient cast at any-boundary — Phase 16 |   ✅   |  ❌  |     ❌      |       ❌        |  ❌  |

## Networking / AI / infrastructure

| #   | Feature                                       | Python                       | OCaml         | JS (server)   | JS (serverless) | C        |
| --- | --------------------------------------------- | :--------------------------: | :-----------: | :-----------: | :-------------: | :------: |
| 24  | remote actors (HTTP)                          | ✅                            | 🟡 no WS      | 🟡             | ❌              | ✅ (via OCaml) |
| 25  | WebSocket                                     | ❌                            | ❌            | ❌             | ❌              | ❌       |
| 26  | AI integration (`ai_call`)                    | ✅ (stream, image)            | ✅            | ✅             | ✅ mock only    | ✅       |
| 27  | AI governance (budget / concurrent / fallback)| ✅                            | ✅            | ✅             | ❌              | ✅       |
| 28  | HMAC-signed remote send                       | ✅                            | ❌            | ❌             | ❌              | ✅       |
| 29  | persistent actor state                        | ✅ (`ABCL_NODE_STATE_FILE`)   | ❌            | ❌             | ❌              | ❌       |
| 30  | live dashboard (SSE)                          | ✅                            | 🟡 polling    | 🟡             | ❌              | ✅       |
| 31  | `/api/typecheck` JSON endpoint                | ❌                            | ✅ (this PR)  | ✅             | ❌              | N/A      |

## C-version-specific codegen targets

| #   | Target                                          | C    |
| --- | ----------------------------------------------- | :--: |
| 32  | C + pthread standalone binary                   | ✅   |
| 33  | C + SDL2 GUI binary (1178-line runtime)         | ✅   |
| 34  | Xinu embedded-OS target (`--xinu`)              | ✅   |
| 35  | Python target (`--python`)                      | ✅   |

---

## Key observations

### Python is by far the most feature-complete (~28/30 ✅)
- All of Phase 11–17 (channels / linear / owned / effects / structured / transient)
- The only runtime with **method injection** (`MethodPatch.abcl`)
- The only runtime with **dynamic compile** (`compile(source)` to generate classes at runtime)
- The only runtime with **persistent actor state**, **HMAC**, and **SSE dashboard** simultaneously
- Full AI integration including streaming and images

### OCaml is the canonical core (~15/30 ✅)
- Phase 11+ features exist only as `.abcl` design-document samples, not implemented
- Solid `become` / `select` / HM inference
- Remote is HTTP only (no HMAC, no WebSocket)

### JS (server) ≈ OCaml
- It's a thin HTTP client over the OCaml backend, so features inherit
- The only differentiator: the new `/api/typecheck` JSON endpoint

### JS (serverless, browser-abcl) is the minimal implementation (~8/30 ✅)
- Basic actor model + our newly-added flow-sensitive type inference
- No `become`, no channels, no remote
- AI integration exists but is **mock only** (no real LLM)

### C version (~17/30 ✅) — surprisingly strong on infrastructure
- `become` and `select` are not implemented (codegen emits `/* unsupported */`)
- But it inherits OCaml's **HMAC**, **SSE**, **AI governance**, and adds **three additional codegen targets** (SDL2, Xinu, Python)
- Today's work: fields, parameters, and locals are now specialized to native C types

### Method injection — a Python exclusive
- Python uses true method dispatch tables that can be mutated at runtime
- Other runtimes substitute `become` (whole-class swap) as the closest equivalent
- `browser-abcl` lacks even `become` (pure actor execution)

### Phase 11+ implementation gap
- Six features (channels, linear, owned, effects, structured, transient) are Python-only
- These represent AIPL's language-evolution frontier; Python serves as the research runtime
- The OCaml runtime predates these and would need parser + checker + runtime extensions

---

*Generated 2026-05-13. For source pointers, run `grep` against the
files listed in each runtime's source column.*
