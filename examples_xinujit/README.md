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
