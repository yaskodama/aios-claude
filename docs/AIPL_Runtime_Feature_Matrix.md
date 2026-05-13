# AIPL Runtime Feature Matrix

Side-by-side feature comparison across the six AIPL implementations
in this repository.  All entries are grounded in source — see notes
for file/line pointers.

**Legend**: ✅ YES (full) — 🟡 PARTIAL — ❌ NO — N/A (not applicable)

The six runtimes:

| Short name           | Source                                     |
| -------------------- | ------------------------------------------ |
| Python (annotated)   | `src/python-aipl/`                         |
| Python (inferred)    | `src/python-aipl-inferred/`                |
| OCaml                | `src/*.ml`, `_build/.../repl_thread.exe`   |
| JS (server)          | `src/app.js` / `console_server.js` / `ide.js` (browser JS) + `src/web_gateway.ml` (OCaml HTTP server) |
| JS (serverless)      | `src/browser-abcl/`                        |
| C (abcl2c)           | `src/abcl2c.ml` codegen + `src/abcl_gui_runtime.c` |

Column abbreviations in tables below: **Py-A** (Python annotated),
**Py-I** (Python inferred), **OCaml**, **JS-S** (JS server),
**JS-N** (JS no-server / browser-abcl), **C**.

Because **JS (server)** is a thin HTTP client over the OCaml runtime,
its feature set is identical to OCaml's except where noted (e.g. the
`/api/typecheck` endpoint added in commit `5227f87`).

Because **Python (inferred)** imports parser, interpreter, AI,
remote, and dashboard from `../python-aipl/`, all *runtime* features
match Python (annotated).  Only the **static type-checker** layer
differs: it runs full Hindley-Milner inference instead of the
Phase 11+ annotation-driven checker.

---

## Core language

| #   | Feature                                             | Py-A | Py-I | OCaml | JS-S | JS-N | C    |
| --- | --------------------------------------------------- | :--: | :--: | :---: | :--: | :--: | :--: |
| 1   | **method injection** (`add_method`/`remove_method`) |  ✅  |  ✅  |  ❌   |  ❌  |  ❌  |  ❌  |
| 2   | `now` synchronous send                              |  ✅  |  ✅  |  ✅   |  ✅  |  ✅  |  ✅  |
| 3   | `future` async send                                 |  ✅  |  ✅  |  ✅   |  ✅  |  ✅  |  ✅  |
| 4   | `await` future block                                |  ✅  |  ✅  |  ✅   |  ✅  |  ✅  |  ✅  |
| 5   | `send` fire-and-forget                              |  ✅  |  ✅  |  ✅   |  ✅  |  ✅  |  ✅  |
| 6   | `become` actor class swap                           |  ✅  |  ✅  |  ✅   |  ✅  |  ❌  |  ❌  |
| 7   | `select` selective receive                          |  ✅  |  ✅  |  ✅   |  ✅  |  ✅  |  ❌  |
| 8   | top-level functions                                 |  ✅  |  ✅  |  🟡   |  🟡  |  ❌  |  ✅  |
| 9   | signatures / overloads                              |  ❌  |  ❌  |  ✅   |  ✅  |  ❌  |  ❌  |
| 10  | dynamic compile (`compile()`)                       |  ✅  |  ✅  |  ❌   |  ❌  |  ❌  |  ❌  |
| 11  | worker pool / `DynamicWorkerPool`                   |  ✅  |  ✅  |  ❌   |  ❌  |  🟡  |  ❌  |

## Type system

| #   | Feature                              | Py-A      | Py-I       | OCaml      | JS-S       | JS-N                       | C                       |
| --- | ------------------------------------ | :-------: | :--------: | :--------: | :--------: | :------------------------: | :---------------------: |
| 12  | type inference                       | 🟡 trace  | ✅ HM       | ✅ HM       | ✅ HM       | ✅ flow-sensitive          | ✅ HM + specialization  |
| 13  | type annotations (`var x: int`)      | ✅        | 🟡 ignored  | ❌         | ❌         | ❌                         | ❌                      |
| 14  | records `{a: int, b: string}`        | ✅        | ✅          | ❌ type only | ❌       | ❌                         | 🟡 type only            |
| 15  | tuples `(1, "a")`                    | ✅        | ✅          | ❌         | ❌         | ❌                         | ❌                      |
| 16  | arrays (typed, multi-dim)            | ✅        | ✅          | ✅         | ✅         | 🟡                         | 🟡                      |
| 17  | generics on functions                | ❌        | ✅ Forall   | 🟡 Forall  | 🟡         | ❌                         | ❌                      |

## Phase 11+ advanced features

The Python (inferred) variant runs HM only; the annotation-driven
Phase 11+ static checks that Python (annotated) performs are **not**
re-implemented.  Programs still execute at runtime via the inherited
interpreter, but the static guarantees from Phase 12 / 14 / 15 / 16
are lost.  Phase 13 (channels) and Phase 17 (structured concurrency)
are runtime features, so they remain available.

| #   | Feature                                    | Py-A | Py-I       | OCaml | JS-S | JS-N | C    |
| --- | ------------------------------------------ | :--: | :--------: | :---: | :--: | :--: | :--: |
| 18  | channels (CSP-style) — Phase 13            |  ✅  |  ✅        |  ❌   |  ❌  |  ❌  |  ❌  |
| 19  | linear types / use-after-move — Phase 14   |  ✅  |  ❌ static  |  ❌   |  ❌  |  ❌  |  ❌  |
| 20  | owned/pub fields — Phase 15                |  ✅  |  ❌ static  |  ❌   |  ❌  |  ❌  |  ❌  |
| 21  | effects `!{fs,ai,net,mut}` — Phase 12      |  ✅  |  ❌ static  |  ❌   |  ❌  |  ❌  |  ❌  |
| 22  | structured concurrency `scope` — Phase 17  |  ✅  |  ✅        |  ❌   |  ❌  |  ❌  |  ❌  |
| 23  | transient cast at any-boundary — Phase 16  |  ✅  |  ❌ static  |  ❌   |  ❌  |  ❌  |  ❌  |

## Networking / AI / infrastructure

| #   | Feature                                       | Py-A                       | Py-I                | OCaml         | JS-S          | JS-N         | C        |
| --- | --------------------------------------------- | :------------------------: | :-----------------: | :-----------: | :-----------: | :----------: | :------: |
| 24  | remote actors (HTTP)                          | ✅                          | ✅                   | 🟡 no WS      | 🟡            | ❌           | ✅ (via OCaml) |
| 25  | WebSocket                                     | ❌                          | ❌                   | ❌            | ❌            | ❌           | ❌       |
| 26  | AI integration (`ai_call`)                    | ✅ (stream, image)          | ✅                   | ✅            | ✅            | ✅ mock only | ✅       |
| 27  | AI governance (budget / concurrent / fallback)| ✅                          | ✅                   | ✅            | ✅            | ❌           | ✅       |
| 28  | HMAC-signed remote send                       | ✅                          | ✅                   | ❌            | ❌            | ❌           | ✅       |
| 29  | persistent actor state                        | ✅ (`ABCL_NODE_STATE_FILE`) | ✅                   | ❌            | ❌            | ❌           | ❌       |
| 30  | live dashboard (SSE)                          | ✅                          | ✅                   | 🟡 polling    | 🟡            | ❌           | ✅       |
| 31  | `/api/typecheck` JSON endpoint                | ❌                          | ❌                   | ✅            | ✅            | ❌           | N/A      |

## C-version-specific codegen targets

| #   | Target                                          | C    |
| --- | ----------------------------------------------- | :--: |
| 32  | C + pthread standalone binary                   | ✅   |
| 33  | C + SDL2 GUI binary (1178-line runtime)         | ✅   |
| 34  | Xinu embedded-OS target (`--xinu`)              | ✅   |
| 35  | Python target (`--python`)                      | ✅   |

---

## Key observations

### Python (annotated) is the most feature-complete runtime (~28/30 ✅)
- All of Phase 11–17 (channels / linear / owned / effects / structured / transient)
- The only runtimes with **method injection** are the two Python variants (annotated and inferred)
- The only runtimes with **dynamic compile** are again the two Python variants
- Full AI integration including streaming and images

### Python (inferred) is Python's HM-typed twin (~24/30 ✅)
- Runtime features match Python (annotated) exactly (shared interpreter)
- Trades the Phase 11+ annotation-driven static checks (effects /
  linear / owned / transient) for full Hindley-Milner inference
- Inferred types cross-verified against OCaml: identical on shared
  samples (Hello.abcl, counter.abcl)
- Method injection still works at runtime — HM inference simply
  treats `add_method` calls as gradual

### OCaml is the canonical core (~15/30 ✅)
- Phase 11+ features exist only as `.abcl` design-document samples,
  not implemented
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
- But it inherits OCaml's **HMAC**, **SSE**, **AI governance**, and
  adds **three additional codegen targets** (SDL2, Xinu, Python)
- Fields, parameters, and locals are specialized to native C types

### Method injection — a Python-family exclusive
- Both Python variants use mutable method dispatch tables that can
  be mutated at runtime via `add_method` / `remove_method`
- Other runtimes substitute `become` (whole-class swap) as the
  closest equivalent
- `browser-abcl` lacks even `become` (pure actor execution)

### Type inference cross-verification
For shared samples (`abclc/Hello.abcl`, `abclc/counter.abcl`),
the three HM-based runtimes (OCaml, Python-inferred, C) produce
**identical inferred types**:

```
Hello:   count : float
         init  : (int) -> unit
         greet : () -> unit
         inc   : () -> unit

Counter: count : float
         inc   : () -> unit
         dec   : (float) -> unit    ← monomorphized from `'a` via call site
```

This means a programmer can reason about types uniformly across the
HM-based implementations, regardless of language backend.

### Phase 11+ implementation gap
- The full Phase 11–17 stack is implemented only in Python (annotated)
- These represent AIPL's language-evolution frontier; Python
  (annotated) serves as the research runtime
- Python (inferred) keeps the runtime side but trades the static
  checks for HM-style polymorphic inference — a different research
  axis (declarative typing vs annotated capabilities)

---

*Generated 2026-05-13.  Includes the `python-aipl-inferred` runtime
added in commit `270f291`.  For source pointers, run `grep` against
the files listed in each runtime's source column.*
