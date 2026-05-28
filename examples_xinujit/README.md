# --xinu-jit : AIPL → C → xinu-rpi5 /compile (JIT on real Pi 4)

`aipl2c --xinu-jit` emits a self-contained, **integer-only** C program that the
on-device compiler in `xinu-rpi5/cc/` accepts (no value_t / threads / libc):

- objects live in `struct Obj { int cls; int f[N]; } g_obj[64];`
- fields are array slots; a message send is `dispatch(to, methodId, a0..a3)`
- each method → `int m_<Class>_<method>(int self,int a0..a3)`
- top-level `var x = new C(); now ...; print ...;` → `main()`

Scope: int values only (floats truncated, strings only as a literal `print` arg).

## Workflow
```sh
dune exec src/aipl2c.exe -- examples_xinujit/Counter.abcl --xinu-jit --no-typecheck -o /tmp/Counter.c
curl --data-binary @/tmp/Counter.c http://192.168.3.100/compile
# or:
examples_xinujit/run.sh examples_xinujit/Counter.abcl
```

## Verified on real Pi 4 (2026-05-28)
- Counter.abcl  → `5 / 42 / 42`   (fields, params, return, now)
- Summer.abcl   → `5050`          (while loop)
- Multi.abcl    → `123`           (two actors, cross-actor now, new)

## value_t update (2026-05-28)
Values are now tagged (int | string), so AIPL strings and concatenation work:
- String.abcl → `count = 5` / `count = 42` / `done`  (string literals + `"..." + int`)
Integer programs (Counter/Summer/Multi) still pass. Float is still truncated to int.

## Resident actors (2026-05-28)
`POST /actor/load` (body = --xinu-jit C) keeps the program resident: main()
spawns the actors and they stay alive.  `GET /actor/send?to=N&m=METHOD&arg=X`
messages them; state persists across calls.  See actor_server.sh.
Also on the serial shell: `aload <file.c>` / `amsg <actor> <method> [arg]`.

## select + synchronous now (2026-05-28)
- Select.abcl → `add 10 / add 20 / stopping`  (selective receive: each actor is
  a Xinu process that blocks on its mailbox until a named message arrives)
- Rpc.abcl    → `got 50`  (in-method `now` is a real synchronous call between
  actor processes: the caller blocks for the callee's return value)

## saga — compensating transactions (2026-05-28)
AIPL's `saga { step {..} compensate {..} ... }` runs on the Pi.  Steps run in
order (each a synchronous `now` to a collaborator); a step calls `fail()` to
abort, and the already-committed steps are then compensated in reverse (LIFO).
- Saga.abcl → `hotel/flight reserved`, `payment DECLINED`, then
  `flight CANCELLED` / `hotel CANCELLED` (rollback in reverse; refund is skipped
  because payment never committed).  Make Payment.charge return 1 to commit with
  no compensation.
(int-only backend has no exceptions, so failure is signalled by `fail()` rather
than a raise; nested sagas are not supported.)

## let-it-crash + supervision (2026-05-28)
An actor handler that hits a transient fault calls `crash()`: the kernel
abandons just that handler and returns the actor to its receive loop (the
process stays ALIVE — the crash is isolated, it does not halt the system).
A synchronous `now` caller is then unblocked with a crash sentinel, which
`crashed()` yields, so a supervisor can `if (r == crashed())` detect it and
retry / restart.
- Supervised.abcl → worker crashes on try 1, supervisor retries, worker
  recovers on try 2 (`recovered, result = 2`).  If the worker keeps crashing
  the supervisor reports `gave up` — no infinite loop, no wedge.
Implementation: per-actor `__builtin_setjmp` frame in actorproc.c (no
exception-handler or scheduler changes); `crash()`/`crashed()` are ordinary
calls (no new syntax).

## lists / collections (2026-05-28)
A list is a value_t (a pointer tagged into a per-run list heap, alongside the
int/string/float tags).  Exposed as ordinary builtin calls (no new syntax):
`list()` (empty), `push(l, x)` (immutable append -> new list), `get(l, i)`,
`len(l)`.  Lists print as `[a, b, c]` and concatenate with strings.
- Lists.abcl → `[10, 20, 30, 40]`, `len 4`, `l[2]=30`, `sum 100`,
  `filtered(>20) = [30, 40]` (build via loop, index, sum, filter into a new
  list).
