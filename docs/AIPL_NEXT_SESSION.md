# AIPL — Next Session Resume

Resume note for the AIPL implementation work.  For the language-model
training side, see `local-genai/NEXT_SESSION.md` (separate axis,
Stage-13-jp-heavy was the last champion at bpb 1.494).

## Restart prompt to paste into Claude

```
docs/AIPL_NEXT_SESSION.md と docs/AIPL_Runtime_Feature_Matrix.md を
読み込んで現状を把握して下さい。

AIPL は今、7 ランタイム + 7 codegen ターゲットの言語プロジェクト
です:
  ランタイム: Python (annotated) / Python (inferred) /
              OCaml / JS-OCaml(server) / JS-Browser /
              JS-Node(server) / C (abcl2c → runtime variants)
  codegen   : C+pthread / C+SDL2 / Xinu / Python / Pony /
              Erlang / Go / Prolog

最新 commit: 9f4fb15 (gitignore cleanup)
直近作業: WebSocket 統合完了 (全 7 runtime), abcl2c → aipl2c rename,
         ABCL/c+ → AIPL 全置換, self-host 37/37 smoke pass を確認。

次の候補:
  (a) JVM 系 (Kotlin / Scala / Java) codegen
  (b) Swift codegen (Swift 5.5+ の actor model)
  (c) WASM ターゲット (browser でネイティブ実行)
  (d) AIPL 拡張 — Phase 18 prediction (aice-evolution-v2 で次世代)
  (e) 既存ターゲット最適化 (C codegen の become/select/now サポート)
  (f) aipl-self-host を C/Pony/Erlang などにも展開
  (g) /api/typecheck と /ws を OCaml gateway にも統一仕様で整備

推奨と理由を一言で教えて下さい。
```

---

## Current state (2026-05-13 session end)

### Runtimes (7)

| Short | Source                                   | Type system            | Concurrency      |
| ----- | ---------------------------------------- | ---------------------- | ---------------- |
| Py-A  | `src/python-aipl/`                       | annotations (gradual)  | 1:1 OS thread    |
| Py-I  | `src/python-aipl-inferred/`              | HM inference           | 1:1 OS thread    |
| OCaml | `src/*.ml`, `_build/.../repl_thread.exe` | HM inference           | 1:1 OS thread    |
| JS-O  | `src/app.js` + OCaml `web_gateway`       | (= OCaml)              | (= OCaml)        |
| JS-B  | `src/browser-abcl/`                      | flow-sensitive         | cooperative loop |
| JS-N  | `src/node-aipl-server/` (Node HTTP)      | flow-sensitive         | cooperative loop |
| C     | `src/aipl2c.ml` codegen + runtimes       | HM + specialization    | depends on target |

### Codegen targets (7, via `aipl2c`)

| Flag         | Target                          | Concurrency             |
| ------------ | ------------------------------- | ----------------------- |
| (default)    | C + pthread                     | 1:1 OS thread           |
| (default+sdl2) | C + SDL2 GUI binary           | 1:1 OS thread           |
| `--xinu`     | Xinu embedded-OS C              | 1:1 OS process          |
| `--python`   | stand-alone Python              | 1:1 OS thread           |
| `--pony`     | Pony source                     | M:N lightweight         |
| `--erlang`   | Erlang `.erl` module            | M:N BEAM process        |
| `--go`       | Go `main.go`                    | M:N goroutine           |
| `--prolog`   | SWI-Prolog `.pl`                | 1:1 OS thread           |

### Key documents

- **`docs/AIPL_Runtime_Feature_Matrix.{md,tex,pdf}`** — 11-page side-by-side
  comparison: 35+ feature rows × 7 runtimes; sample-count and
  per-sample-feature tables; concurrency-model section; latest at PDF
  92.9 KB.
- `docs/AIPL_Type_Soundness_Report.{tex,pdf}` — older soundness analysis.
- `aipl-self-host/` — AIPL written in AIPL (9 levels, A → C-3, 37/37 smoke pass).
- `AIPL_OVERVIEW.md` — bird's-eye index.
- `USER_MANUAL.md` — language tour.
- `BUILTINS.md` — builtin reference.

---

## What this session changed

Commits this session (most recent first; date 2026-05-13):

```
9f4fb15  gitignore: stop tracking tinyshake_100MB_multi.txt (95 MB)
966dbce  gitignore: stop tracking tinyshake_60MB.txt (57 MB)
1993ce7  Rename abcl2c → aipl2c; replace ABCL/c+ text with AIPL
5f754a9  C codegen: libwebsockets runtime (Phase 4 — WS rollout complete)
4467a35  python-aipl: WebSocket builtins via websockets lib (Phase 3 of WS)
93c18af  node-aipl-server: add WebSocket endpoint (Phase 2 of WS rollout)
8f758f8  docs: correct WebSocket row in feature matrix
b7f667b  AIPL: verify now/future/send+select × ai_call, fix OCaml gaps
31407a3  AIPL: ai_call provider arg — wire 1/2/3 → gemini/anthropic/openai
31a12a3  AIPL: --prolog codegen — class → SWI-Prolog thread + receive
e6c1739  docs: feature matrix — add Actor concurrency model section
543fc71  AIPL: --go codegen — class → struct + goroutine + channel
e1f5d64  AIPL: --erlang codegen — class → spawn + receive loop
d364243  AIPL: --pony codegen — class → actor, capability-secure target
028811b  docs: feature matrix — add session types + protocol traces + AIOS
b11dde1  docs: feature matrix — add Target column to sample table
a5f71d0  docs: feature matrix — add "What each sample exercises" table
5224776  docs: add sample-count row + LaTeX/PDF version of feature matrix
de25b45  docs: add python-aipl-inferred to AIPL runtime feature matrix
270f291  AIPL: add python-aipl-inferred — sixth runtime, HM-typed
adeb0b6  AIPL: add node-aipl-server — seventh runtime, Node HTTP server
5227f87  AIPL: JS server — add /api/typecheck endpoint
60ea659  AIPL: full HM type inference in C/browser-abcl versions
```

### Headline themes

1. **Type inference rollout.**  Added full HM inference to C codegen
   (with specialization) and flow-sensitive inference to browser-abcl.
   Added `python-aipl-inferred` as the HM-typed Python sibling.
   `/api/typecheck` JSON endpoints on OCaml and Node servers.
2. **Three new codegen targets.**  Pony, Erlang, Go, and Prolog (so
   `aipl2c` now has 8 targets total).  Each verifies on Hello.abcl +
   counter.abcl; PingPong xfail-expected.
3. **`ai_call` provider argument** unified across runtimes:
   `ai_call([1|2|3,] prompt)`, 1=gemini / 2=anthropic / 3=openai;
   omitting it auto-selects from env.  Found and fixed two OCaml
   bugs while testing: mock-env precedence over explicit override,
   and top-level `Send` not evaluating its args before delivery.
4. **WebSocket support across all 7 runtimes.**  OCaml already had
   it (verified handshake 101); JS-Node gained `ws` (`/ws?sid=` +
   `/api/broadcast`); Python gained `aipl_websocket.py` (4 builtins);
   C codegen gained `abcl_ws_runtime.c` (libwebsockets).
5. **Rename `abcl2c` → `aipl2c`** and **`ABCL/c+` → `AIPL`** across the
   entire repository (52 files).  Public env-var names like
   `ABCL_AI_PROVIDER` retained (separate concern).
6. **`local-genai/` cleanups.**  Stage-13-jp-heavy (108 MB) was
   already gitignored; this session also added `tinyshake_60MB.txt`
   (57 MB) and `tinyshake_100MB_multi.txt` (95 MB) — both regenerable
   from `build_*.py`.  No history rewrites.

---

## How to verify quickly

```bash
cd /Users/kodamay/ocaml-app/abclcp-project

# 1) Build OCaml side
dune build

# 2) Run every smoke
bash run_all_smoke_tests.sh                      # OCaml + JS + Python + Dist
bash src/test_pony_codegen.sh                    # Pony codegen
bash src/test_erlang_codegen.sh                  # Erlang codegen
bash src/test_go_codegen.sh                      # Go codegen
bash src/test_prolog_codegen.sh                  # SWI-Prolog codegen
bash src/test_c_websocket.sh                     # C + libwebsockets
bash src/python-aipl-inferred/_smoke_test.sh     # HM-typed Python
bash src/node-aipl-server/_smoke_test.sh         # Node HTTP + WS

# 3) Self-host (AIPL in AIPL)
for d in aipl-self-host/level-*; do
  [ -f "$d/smoke.sh" ] && (cd "$d" && bash smoke.sh)
done
```

### Latest known-good smoke results

```
OCaml (run_all_smoke_tests.sh):   48/57 PASS (9 pre-existing Gui/Py/Xinu fails)
browser-abcl:                     syntax 7/7 + parse 4/4 + typeck 4/4
node-aipl-server:                 10/10
python-aipl-inferred:             20/20
Pony codegen:                     2 PASS + 1 xfail
Erlang codegen:                   2 PASS + 1 xfail
Go codegen:                       2 PASS + 1 xfail
Prolog codegen:                   2 PASS + 1 xfail
C + WebSocket:                    1/1 PASS
self-host:                        37/37 PASS (across 9 levels)
```

### Real LLM call (requires API key, run locally)

```bash
# Python: pick provider 2 (Anthropic)
ANTHROPIC_API_KEY=sk-ant-... /usr/bin/python3 \
  src/python-aipl/aipl_main.py /tmp/test_aic.abcl

# OCaml: same via REPL
ANTHROPIC_API_KEY=sk-ant-... \
  printf 'load /tmp/test_aic.abcl\ncompile\n' | \
  _build/default/src/repl_thread.exe -f /dev/stdin
```

Where `/tmp/test_aic.abcl`:
```aipl
class T {
  method run() {
    var r = ai_call(2, "Say hi in 5 words.");
    print(r);
  }
}
var t = new T();
send t.run();
```

---

## Known limitations and open items

### C codegen feature gaps
The `aipl2c` standalone-C path generates working code for Hello /
counter / many actor samples, but the runtime doesn't include:
- `become` (codegen emits `/* become unsupported */`)
- `select` (codegen emits `/* select unsupported */`)
- `now` reply slot (no future table in `abcl_gui_runtime.c`)
- `ai_call` (no libcurl integration; would need to be added to
  the C runtime same way `abcl_ws_runtime.c` adds WebSocket)

The OCaml runtime has all of these; C codegen is best-effort.

### Pre-existing OCaml type errors (9 samples)
`abclc/BoundedBufferGui.abcl`, `Philosophers5Gui.abcl`,
`Rotate4LinesGui.abcl` (and their `*Py` / `*Xinu` variants) declare
fields as numeric defaults (`var partner = 0`) but later assign
actor references.  Our hard-fail Typecheck.run surfaces these as
errors during `aipl2c` invocations.  Three pragmatic options:
1. Rewrite the samples to use a sentinel actor literal.
2. Relax the hard-fail to a warn-and-continue per the OCaml-REPL behavior.
3. Add a sentinel-aware widening pass.  Option (3) is what
   browser-abcl's flow-sensitive checker already does internally.

### `ai_call(N, prompt)` and explicit provider
When `ABCL_AI_PROVIDER=mock` is set, that wins over an explicit
provider argument (mirrors Python).  Without that env var, a
`ai_call(2, ...)` without `ANTHROPIC_API_KEY` will fail hard —
which is the expected "user explicitly asked for Anthropic"
behaviour.

---

## Possible next directions

| Option | Description | Effort |
|---|---|---|
| (a) **JVM family codegen** (Kotlin / Scala / Java) | Coroutines or virtual threads; large user base | ~600-1000 LOC |
| (b) **Swift codegen** | Apple native `actor`; Phase 17 structured concurrency map | ~800 LOC |
| (c) **WASM codegen** | Browser-native AOT; complements browser-abcl interpreter | ~1500 LOC |
| (d) **AIPL Phase 18 prediction** via `aice-evolution-v2` | Run MAP-Elites on current Phase 17 stack | research |
| (e) **C codegen feature parity** | become / select / now / ai_call in `abcl_gui_runtime.c` | medium |
| (f) **Self-host on other backends** | Run aipl-self-host Level A on Pony or Go output | small |
| (g) **OCaml `web_gateway` standardisation** | Mirror `/api/typecheck` + `/api/run` + `/ws` shape so JS-OCaml has parity with JS-Node | small |

Earlier in the session the user expressed interest in Pony first
(done), then Erlang (done), Go (done), Prolog (done).  Tier-2
candidates from that conversation: **JVM (Kotlin/Java)** and
**Swift**.

---

## Repository layout (quick reference)

```
abclcp-project/
├── src/
│   ├── aipl2c.ml             — codegen entry (was abcl2c.ml)
│   ├── c_translator.ml       — emitters for C/Xinu/Python/Pony/Erlang/Go/Prolog
│   ├── ai.ml, repl_thread.ml — OCaml runtime
│   ├── web_gateway.ml        — HTTP + WebSocket server
│   ├── abcl_gui_runtime.c    — C runtime (SDL2 GUI builtins)
│   ├── abcl_ws_runtime.c     — C runtime extension (libwebsockets)
│   ├── browser-abcl/         — JS-Browser runtime
│   ├── node-aipl-server/     — JS-Node HTTP+WS server (uses browser-abcl)
│   ├── python-aipl/          — Python (annotated) runtime + aipl_websocket.py
│   ├── python-aipl-inferred/ — Python (HM-inferred) sibling
│   └── test_*_codegen.sh     — per-target smoke tests
├── abclc/                    — OCaml-side .abcl samples (115 files)
├── aipl-self-host/           — AIPL in AIPL (9 levels)
├── docs/
│   ├── AIPL_NEXT_SESSION.md  — (this file)
│   ├── AIPL_Runtime_Feature_Matrix.md / .tex / .pdf
│   ├── AIPL_OVERVIEW.md      (in repo root)
│   └── AIPL_Type_Soundness_Report.{tex,pdf}
├── docker/cross/             — cross-language interop demo
└── local-genai/              — language model training (separate axis;
                                 NEXT_SESSION.md there for the LM side)
```

---

*Generated 2026-05-13.  Up-to-date through commit `9f4fb15`.*
