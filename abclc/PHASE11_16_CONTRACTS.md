# OCaml AIPL samples — Phase 11+ contract reference

The OCaml AIPL runtime predates Phase 11–16's typed surface (parameter
annotations, `pub` modifier, capability effects, `linear T`, transient
cast at any-boundary).  The samples in this directory therefore use
the original gradually-typed syntax.

For each OCaml sample listed below, the **typed equivalent** in current
AIPL spec lives under `src/python-aipl/samples/` (or
`src/python-aipl/samples-ai/`, `samples-remote/`).  Both implementations
share the same wire format and runtime semantics — only the surface
syntax differs.

## Mapping table

| OCaml sample (this dir)            | Python AIPL equivalent (current spec)                | Phase 11+ feature illustrated |
| ---                                | ---                                                   | --- |
| `Hello.aipl`                       | `samples/Hello.aipl`                                  | typed `var count: int`, `init(n: int)` |
| `counter.aipl`                     | `samples/Counter.aipl`                                | typed field, transient-cast clean |
| `PingPong.aipl`                    | `samples/PingPong.aipl`                               | typed `init(n: int)`, actor refs |
| `bounded_buffer.aipl`              | `samples/BoundedBuffer.aipl`                          | `pub var size: int` (Phase 15), typed init |
| `Philosophers5.aipl`               | `samples/Philosophers.aipl`                           | typed `init(my_id: int, l, r, n: int)`, `pub var meals` |
| `philosophers.aipl`                | `samples/Philosophers.aipl`                           | same |
| `Phase11_TypedCounter.aipl`        | `samples/Counter.aipl`                                | already current |
| `Phase12_EffectsLog.aipl`          | `samples/Effects.aipl`                                | `!{fs, net, ai, mut}` declarations |
| `Phase13_Channels.aipl`            | `samples/Channels.aipl`                               | `channel(N, "T")`, `channel_send`, `channel_recv` |
| `Phase14_Linear.aipl`              | `samples/Linear.aipl`                                 | `linear T` use-after-move |
| `Phase15_Owned.aipl`               | `samples/Owned.aipl`                                  | `pub` field modifier |
| `web_calc.aipl`                    | `samples-remote/server.aipl`                          | `web_listen`, `web_expose`, remote actor |
| `ai-samples/AIHello.aipl`          | `samples-ai/CooperativeNowFuture.aipl` (similar pattern) | typed AI calls |
| `ai-samples/CooperativeNowFuture.aipl` | `samples-ai/CooperativeNowFuture.aipl`            | typed AI calls + `!{ai, net}` |
| `ai-samples/RemoteCalcServer.aipl` | `samples-remote/server.aipl`                          | typed remote server |
| `ai-samples/RemoteCalcClient.aipl` | `samples-remote/client.aipl`                          | typed remote client |

## Why two implementations?

1. **OCaml**: native runtime, focused on actor scheduling and the
   shape of the program.  The HM-style inferer in `src/infer.ml` does
   simple type inference but does not parse Phase 11–16 surface syntax.
2. **Python**: research / iterating runtime where the Phase 11–16
   features (gradual typing, capability effects, CSP channels, linear
   ownership, symbol_owned, transient cast) are first implemented.

When in doubt about a sample's *intent* in current AIPL terms, read
the Python version — the OCaml version expresses the same actor
program but cannot annotate with the Phase 11+ surface.

## Running

```sh
# OCaml side
make ocaml
echo 'load Hello.aipl' >  /tmp/_run.bat
echo 'compile'          >> /tmp/_run.bat
_build/default/src/repl_thread.exe -f /tmp/_run.bat

# Python side (same program logic, typed surface)
python3 src/python-aipl/aipl_main.py src/python-aipl/samples/Hello.aipl --type-check
```

The Python form additionally accepts `--transient` to enable runtime
type checks at every annotated `any -> T` boundary (Phase 16).
