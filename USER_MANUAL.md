# AIPL User's Manual

**AIPL** (Actor-based Intelligent Parallel Language; formerly AIPL) is a
re-implementation of ABCL/1 — the concurrent object-oriented language designed
in Akinori Yonezawa's laboratory at the Tokyo Institute of Technology — given a
modern syntax and multiple runtimes (native OCaml / browser JS / C). This
manual summarizes the language specification and walks through the bundled
sample programs.

> 日本語版は [`USER_MANUAL_JP.md`](USER_MANUAL_JP.md) を参照してください.

> For backward compatibility, the file extension `.abcl`, the Python runtime
> module names (`aipl_main.py`, etc.), and environment variables such as
> `ABCL_AI_PROVIDER` are kept under their former names.

- Target version: the OCaml REPL implementation bundled in this repository (`abclcp-project`)
- Main sources: `src/lexer.mll`, `src/parser.mly`, `src/eval_thread.ml`
- Samples: `abclc/*.abcl`, `src/*.abcl`

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Building and Running the System](#2-building-and-running-the-system)
3. [Language Specification](#3-language-specification)
   - 3.1 [Lexical Elements](#31-lexical-elements)
   - 3.2 [Types and Values](#32-types-and-values)
   - 3.3 [Expressions and Statements](#33-expressions-and-statements)
   - 3.4 [Classes and Actors](#34-classes-and-actors)
   - 3.5 [Message Sending (`send` / `send!` / `call`)](#35-message-sending-send--send--call)
   - 3.6 [Selective Receive with `select`](#36-selective-receive-with-select)
   - 3.7 [Behavior Replacement with `become`](#37-behavior-replacement-with-become)
   - 3.8 [`reply` and `sender`](#38-reply-and-sender)
   - 3.9 [Remote Sending](#39-remote-sending)
4. [Built-in Function Reference](#4-built-in-function-reference)
5. [Sample Programs](#5-sample-programs)
   - 5.1 [Hello — Minimal Sample](#51-hello--minimal-sample)
   - 5.2 [Counter — Self-Messages and Fields](#52-counter--self-messages-and-fields)
   - 5.3 [PingPong — Two-Party Message Exchange](#53-pingpong--two-party-message-exchange)
   - 5.4 [Become — Dynamic Behavior Replacement](#54-become--dynamic-behavior-replacement)
   - 5.5 [BoundedBuffer — Producer/Consumer Problem](#55-boundedbuffer--producerconsumer-problem)
   - 5.6 [Philosophers — Dining Philosophers](#56-philosophers--dining-philosophers)
   - 5.7 [Rotate4Lines — SDL Drawing and Timers](#57-rotate4lines--sdl-drawing-and-timers)
   - 5.8 [WebCalc — HTTP Gateway and `select`](#58-webcalc--http-gateway-and-select)
6. [Phase C-E2 Type Inference (Python Runtime)](#6-phase-c-e2-type-inference-python-runtime)
7. [AIPL v2 Distributed Runtime (`aipl_dist`)](#7-aipl-v2-distributed-runtime-aipl_dist)
8. [Appendix: Troubleshooting](#8-appendix-troubleshooting)

---

## 1. Introduction

AIPL is a concurrent programming language based on the **actor model**.
A program is composed of multiple independent *actors* (instances of classes),
and actors communicate with one another through **asynchronous messages**.

- Each actor owns its own message queue (mailbox)
- State (fields) is confined within the actor and cannot be read or written directly from the outside
- A method call is expressed as a **message send (`send`)**
- The receiver processes messages in arrival order, or conditionally via a `select` statement

Of the three send modes — past / now / future — found in traditional ABCL/1,
AIPL provides the **past mode (fire-and-forget)** as `send`, and the equivalent
of the **now mode (synchronous reply-wait)** through the combination of `reply`
+ `select`.

---

## 2. Building and Running the System

### 2.1 Building

Running `make` in the top directory builds both the OCaml and JS
implementations.

```bash
make            # = make all (OCaml + JS)
make ocaml      # OCaml REPL only (_build/default/src/repl_thread.exe)
make js         # Regenerate the browser parser
```

### 2.2 Running Samples

```bash
make run-hello             # abclc/Hello.abcl
make run-philosophers      # 5 philosophers
make run-rotate4           # SDL drawing demo
./run_bounded_buffer.sh    # Bounded buffer
./run_pingpong_xinu.sh     # PingPong (XINU backend)
```

To feed an arbitrary source file directly:

```bash
_build/default/src/repl_thread.exe abclc/Hello.abcl
```

### 2.3 Running in the Browser

A web version lives under `src/browser-abcl/`. `make serve-js` lets you open
the various demo HTML pages (`viz_philosophers.html`, etc.) from
`http://localhost:3000/`.

---

## 3. Language Specification

### 3.1 Lexical Elements

#### Comments

```
// line comment
/* block
   comment */
```

#### Keywords

```
class  method  var  float  new  become
send   send!   call  remote  reply
if  then  else  while  do
select  case  timeout  ->
self  sender
```

#### Operators

| Category | Operators |
|------|--------|
| Arithmetic | `+` `-` `*` `/` |
| Comparison | `==` `!=` `<` `<=` `>` `>=` |
| Assignment | `=` |

`+` is used both for numeric addition and string concatenation.
If one operand is a string, the other is automatically stringified
(`"count = " + 5`).

#### Literals

- Integer: `0`, `42`
- Floating-point: `3.14`, `100.` (a trailing dot is allowed)
- String: `"hello\n"` (escapes are `\\` `\"` `\n` `\t` `\r`)
- Identifier: `[A-Za-z_][A-Za-z0-9_]*`

### 3.2 Types and Values

AIPL has weak static checking plus a dynamic value representation. The kinds of
values are as follows.

| Type name | Example | Notes |
|------|----|------|
| `int` | `42` | 64-bit integer |
| `float` | `3.14`, `100.` | Double precision |
| `string` | `"abc"` | UTF-8 |
| `bool` | result of a comparison | |
| `actor(C)` | result of `new C()` | An instance of class `C` |
| `array` | `array_empty()` … | Elements are expected to be of the same type |
| `unit` | return of `print(...)` | |

`typeof(x)` retrieves the type name (a string) at runtime.

### 3.3 Expressions and Statements

#### Expressions

```
expr := literal
      | identifier             // variable reference, self, sender
      | expr op expr           // binary operation
      | new C(arg, ...)        // actor creation (within an expression)
      | f(arg, ...)            // built-in function call
      | (expr)
```

#### Statements

```
stmt := var x = expr ;                 // local variable declaration
      | x = expr ;                     // assignment
      | f(arg, ...) ;                  // function call (discard result)
      | call f(arg, ...) ;             // same (explicit form)
      | send target.method(args) ;     // asynchronous message send
      | send! target.method(args) ;    // send bypassing type checking
      | become C(args) ;               // replace self's behavior
      | if (expr) stmt [else stmt]
      | while expr do stmt
      | { stmt; stmt; ... }            // block
      | select { case ... timeout ... }
```

The condition of an `if` is an `expr`, combining `==`, `!=`, `<`, `<=`, `>`, `>=`.

### 3.4 Classes and Actors

```
class ClassName {
  // field declarations (initializer required)
  var fieldA = 0;
  var fieldB = 0.0;
  float fieldC = 1.5;     // typed declaration (float is the only dedicated keyword)

  method init(args...) { ... }      // invoked automatically on instance creation
  method other(args...) { ... }
}
```

- Fields **must be declared with an initializer**
- If an `init` method is defined, it runs automatically on `new`
- If undefined, the creation-time message is skipped and a warning is logged

Instantiating at top level:

```
var name = new ClassName(args);
```

`name` then serves as the actor's name (a mailbox reference).

### 3.5 Message Sending (`send` / `send!` / `call`)

#### `send` — asynchronous message send (recommended)

```
send target.method(args);
```

- `target` is an actor variable created at top level, or `self` / `sender`
- The call returns immediately, and the message is enqueued in the recipient's mailbox
- Only messages that pass type checking are sent

#### `send!` — bypass type checking

An escape hatch for dynamic situations where a remote peer or the interpreter
cannot fully determine types. **Normally use `send`.**

#### `call` — calling a built-in function

For built-in functions (`print`, `sdl_*`, `wait`, etc.) use `call f(...)` or
simply `f(...);`. This is an ordinary function call that waits for the result;
it is not a method call on another actor.

### 3.6 Selective Receive with `select`

Use this when you want to wait for **only specific messages** from the mailbox.

```
select {
  case add(a, b) -> {
    reply(a + b);
  }
  case mul(a, b) -> {
    reply(a * b);
  }
  timeout 15000 -> {
    print("nothing arrived after 15 seconds");
  }
}
```

- Each `case` pattern can only be `methodName(varName, ...)` (no guard expressions)
- Non-matching messages remain in the queue (they are not consumed)
- `timeout N` is in milliseconds. When `N` elapses, the corresponding block runs
- The `timeout` clause is optional (in which case it waits forever)

### 3.7 Behavior Replacement with `become`

An actor can "transform" itself into another class.

```
class A {
  method ping() {
    print("A.ping");
    become B();
  }
}
class B {
  method ping() {
    print("B.ping");
    become A();
  }
}
```

`become` can be used only within a method body, and replaces the current
actor's fields and methods with the result of the new class's `init`. The
mailbox is preserved.

### 3.8 `reply` and `sender`

Within a method body, the implicit variable `sender` is available (the actor
that most recently sent this message).

```
method add(a, b) {
  reply(a + b);            // send a "return value" message back to sender
}
```

- `reply(v)` returns the value `v` to the `sender`
- If the sender came in via the web gateway (HTTP), it is returned as the HTTP response body
- If the sender is an actor, it arrives at its waiting pattern (`select`)

You can also send any method to `sender`, as in `send sender.X(args)`.

### 3.9 Remote Sending

You can send to actors on another host or in another process with the following
syntax.

```
send remote("localhost:8080", "fork2").take(0);
```

- 1st argument: host and port (listened on by `web_listen` on the OCaml side)
- 2nd argument: the actor name within the peer process

In the browser sample `distributed_philosophers_browser.abcl`, variables such
as `fork2` hold a string like `"@fork2"`, and the runtime sees the leading `@`
and automatically routes over HTTP (an interpretation extension of `send`).

---

## 4. Built-in Function Reference

These are the functions registered in the `prim_table` of
`src/eval_thread.ml`. All are called with `f(args)` or `call f(args);`.

### 4.1 Input/Output

| Function | Description |
|------|------|
| `print(v)` | Stringify a value and write to standard output. Also logged in the web UI |
| `typeof(v)` | Return the type name (`"int"`, `"float"`, `"string"`, `"actor(C)"`, …) |

### 4.2 Control

| Function | Description |
|------|------|
| `wait(ms)` | Sleep the current actor (thread) for `ms` milliseconds |

### 4.3 Math Functions

`sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `sqrt`, `exp`, `log10`,
`abs`, `floor`, `ceil`, `round` — all `float -> float`.

### 4.4 Arrays

| Function | Description |
|------|------|
| `array_empty()` | Create an empty array |
| `array_len(a)` | Number of elements |
| `array_get(a, i)` | The i-th element (out of range raises an exception) |
| `array_set(a, i, v)` | Return a **new array** with the i-th element replaced by v |
| `array_push(a, v)` | Return a **new array** with v appended to the end |

> Arrays are treated as a persistent data structure (there are no destructive
> updates). Therefore reassign, as in `a = array_set(a, 0, 99.);`.

### 4.5 SDL Drawing

| Function | Description |
|------|------|
| `sdl_init(w, h)` | Open a window |
| `sdl_clear()` | Clear the screen |
| `sdl_present()` | Flush the front buffer |
| `sdl_line(x1,y1,x2,y2)` | White line |
| `sdl_line_c(x1,y1,x2,y2,r,g,b)` | RGB-specified line |
| `sdl_erase_line(x1,y1,x2,y2)` | Erase a line (redraw with the background color) |
| `sdl_poll_key()` | Key scan code (0 if nothing is pressed) |
| `sdl_mouse_x() / sdl_mouse_y()` | Mouse coordinates |
| `sdl_mouse_down()` | Left-button state (0/1) |

### 4.6 Web Gateway

| Function | Description |
|------|------|
| `web_listen(port)` | Start the built-in HTTP server |
| `web_expose(path, actorName)` | Expose a friendly path |
| `reply(v)` | If the message originated from an HTTP request, return it as the response body |

You can call actors from the outside with `POST /api/json/send` or
`POST /api/x/<path>`.

### 4.7 Debugging

| Function | Description |
|------|------|
| `actor_dump(a)` | Pretty-print an actor's type info (class name, method list) |

### 4.7k Phase 11 — Gradual Static Type Checking (Python Runtime)

Attaching **type annotations** to variables / fields / functions lets the system
detect type mismatches before execution. **Unannotated places are treated as
`any`** and are not warned about (gradual).

```
var p: int = 42;                                 // OK
var s: string = "hi";                            // OK
var bad: int = "thirty";                          // ✗ warning

function add(a: int, b: int) -> int { return a + b; }  // OK
function bad_return(a: int) -> int { return "x"; }     // ✗ warning

class Counter {
  var count: int = 0;
  method tick() { count = count + 1; }
  method get() -> int { return count; }            // method return is also OK
}
```

**Type expressions** (annotation syntax):

| Form | Example |
|----|----|
| atomic | `int`, `float`, `string`, `bool`, `any`, `unit`, `image`, `actor`, `future` |
| array | `array[int]`, `array[array[int]]` |
| tuple | `tuple(int, string)` |
| record | `record{a: int, b: string}` |

**How to run:**

```sh
# Pre-check from the CLI (issues go to stderr)
python3 aipl_main.py --type-check program.abcl

# Strict mode — stop with exit 2 if there are issues
python3 aipl_main.py --type-check --strict program.abcl

# Call from within the program
var issues = type_check();      // array[string] of issue messages
```

**Effect on `typeof`:** A user function's signature is **initialized from its
annotation** and further refined by trace observation:

```
function add(a: int, b: int) -> int { ... }
typeof(add)   → "function(a:int, b:int) -> int"  // from annotation
```

Sample: `src/python-aipl/samples/Typecheck.abcl`

#### Additional Checks in Phase 11b (call-site)

- **Argument types of function calls** — flag `f("hi", 1)` if declared `f(a:int, b:int)`
- **Argument types of built-ins** — flag `read_file(42)` (signature is `path:string`)
- **Argument types of method calls** — flag `now c.tick("x")` (declared `tick(by:int)`)
- **Constructor args of `new C(...)`** — checked against `init`'s annotations
- **Return type of `now obj.method()`** — inferred from the class's method declaration
- **Variadic `+` signature** — flag the `42` in `path_join("a", 42, "c")`
- **Optional argument `[provider,]`** — accept both arities (with/without provider)

```
function add(a: int, b: int) -> int { return a + b; }
class Counter {
  var count: int = 0;
  method init(start: int) { count = start; }
  method tick(by: int) { count = count + by; }
  method get() -> int { return count; }
}

read_file(42);                       // ✗ int vs string
add("nope", 1);                      // ✗ string vs int
add(1, 2, 3);                        // ✗ arity 3 vs 2
var c = new Counter("ten");          // ✗ string vs int
now c.tick("nope");                  // ✗ method arg
var n: int = now c.get();            // ✓ method return inferred from -> int
```

Sample: `src/python-aipl/samples/Typecheck11b.abcl`

#### Phase 11c: Union Types + Simple Generics

- **Union type annotations** — `var x: int | string = ...;` allows multiple types
- **Type variables** — use a single uppercase letter (`T`, `U`, ...) for generics

```
function id(x: T) -> T { return x; }            // type variable T
function pair(a: T, b: T) -> tuple(T, T) { ... }
function head(arr: array[T]) -> T { return arr[0]; }

function describe(x: int | string) -> string {  // union argument
  return "got " + x;
}

var n: int = id(42);              // T = int  → returns int
var s: string = id("hello");      // T = string (a different call)
var u: int | string = 42;         // OK
var u2: int | string = "x";       // OK
var u3: int | string = 3.14;      // ✗ float does not match

pair(1, 2);                       // OK: T = int
pair(1, "two");                   // ✗ T already bound to int → conflicts with string
head(42);                         // ✗ array[T] required, given an int
```

Generics are **per-call binding**: T is freshly bound at each call. If T appears
multiple times among the arguments (e.g. `pair(a: T, b: T)`), they **must be the
same type**.

Sample: `src/python-aipl/samples/Typecheck11c.abcl`

#### Phase 11d: Control-Flow Sensitivity (`typeof`-based narrowing)

Guards of the form `if (typeof(x) == "T")` are detected so that **within the
then-branch `x` is narrowed to `T`**. For `!=`, the direction is reversed (`x`
is narrowed to the union minus `T` in the then-branch).

```
function describe(x: int | string) -> string {
  if (typeof(x) == "int") {
    var n: int = x + 1;        // ← OK because x is narrowed to int here
    return "int: " + n;
  }
  var s: string = x;            // ← in the else-branch x is narrowed to string
  return "str: " + s;
}

function safe_len(x: int | string) -> int {
  if (typeof(x) != "string") {
    return 0;                   // ← x is not a string here, so int
  }
  var s: string = x;            // ← in the then-branch (inverted) x is string
  return str_len(s);
}
```

#### Phase 11e: Lightweight Dependent Types (Fixed-Length Arrays)

With `array[T, N]`, **the length N becomes part of the type**, and:

- The length of the initializer is checked against N
- Out-of-bounds access at a constant index is checked
- A length check is also done on assignment to a field/var

```
class Demo {
  var counts: array[int, 3] = [10, 20, 30];     // OK
  method run() {
    var trio: array[int, 3] = [1, 2, 3];        // OK
    var first: int = trio[0];                   // OK
    var oops:  int = trio[5];                   // ✗ out of bounds (5 >= 3)
    var short: array[int, 5] = [1, 2];          // ✗ length 2 != 5
    counts = [1, 2];                            // ✗ length 2 != 3
  }
}
```

The `_infer` result for an array literal `[1, 2, 3]` is also strengthened to the
length-carrying type `array[int, 3]`, so compatibility is judged in both
directions between `array[int]` (unspecified length) and `array[int, N]`
(specified length).

Sample: `src/python-aipl/samples/Typecheck11de.abcl`

### 4.7p Phase 16 — Transient Cast at the any-Boundary

The type annotations introduced in Phases 11–15 were checked only by static
analysis. Phase 16 adds the **runtime type cast at the `any -> T` boundary**
that was listed as priority #1 in the Soundness Report. It catches, at runtime,
value type mismatches that static checking missed.

**Enabling:** the `--transient` flag.

```sh
python3 aipl_main.py samples/Transient.abcl              # normal execution
python3 aipl_main.py samples/Transient.abcl --transient  # with runtime checks
```

**Check sites:** runtime checks are inserted at three annotated boundaries.

```
class C {
  method tick(amount: int) -> int {   // ← (1) argument boundary
    var local: int = amount + 1;       // ← (2) var-decl boundary
    return local;
  }
}

function square(x: int) -> int {       // ← (3) function argument boundary
  return x * x;
}

var n: int = ai_call("...");           // ✗ ai_call returns a string
                                       //    → transient cast error
```

`any` or unannotated boundaries are not checked. The same compatibility judgment
as static checking (`aipl_typeck._compatible`) is reused, so static and runtime
apply the same rules.

**Zero cost:** without `--transient`, none of the check code runs. The design
preserves the "annotations are present but not mandatory" nature of gradual
typing while letting you obtain strong guarantees only when you need them.

Samples:
- `samples/Transient.abcl` (clean)
- `samples/Transient_violation.abcl` (errors only under `--transient`)

### 4.7o Phase 15 — symbol_owned (Encapsulation of Actor Fields)

Completes the predictive axis `state_representation = symbol_owned` from Phase
9. Static checking enforces that an actor's state (fields) **can be modified only
by the actor itself**:

```
class BankAccount {
  var balance: int = 0;          // default: externally invisible (private)
  pub var holder: string = "";   // pub: externally readable

  method deposit(amount: int) -> int {
    balance = balance + amount;  // writing from your own method is OK
    return balance;
  }
}

class Bandit {
  method attack() {
    var acct = new BankAccount();
    var s = acct.holder;     // OK   (external read of a pub field)
    var b = acct.balance;    // ✗   (external read of a private field)
    acct.balance = 999;      // ✗   (external write is forbidden regardless of pub/private)
  }
}
```

**Rules:**
- Prefixing a field declaration with `pub` makes it **externally readable**. The
  default (no `pub`) is private.
- **External writes (`obj.field = ...`) are always forbidden**: even `pub`
  forces modification to go through a method (protecting actor invariants).
- Within a method of the same class, you can freely read/write your own fields
  by their bare `field` name (this resolves as a Var, not a FieldAccess).
- Record types (anonymous `{...}` data) remain freely readable/writable —
  Phase 15 targets actors only.

Samples: `src/python-aipl/samples/Owned.abcl` (clean),
`samples/Owned_violations.abcl` (emits 3 intentional violations).

### 4.7n Phase 14 — Linear / Borrow Types (use-after-move detection)

The `linear T` prefix declares a **value usable at most once**:

```
function open(name: string) -> linear int { ... }
function write(f: linear int, s: string) -> linear int { ... }
function close(f: linear int) -> int { ... }
```

Passing a variable to a function that takes a `linear` parameter marks the
variable as **moved**, and any subsequent reference is a **use-after-move
error**:

```
var fh: linear int = open("x");
write(fh, "hello");        // consumes fh
close(fh);                 // ✗ use-after-move
```

The correct pattern is to **rebind**: the function returns a new linear value,
which you reassign:

```
var fh: linear int = open("x");
fh = write(fh, "hello");   // old fh is moved, new fh returned
fh = write(fh, "world");
close(fh);                 // final consumption
```

**Control-flow awareness:** if an `if`'s then-branch ends in `return`, it does
not affect the post-if moved state. This refines the previous conservative
behavior of unioning both branches:

```
function ok_branch(name: string, prefer_close: int) -> int {
  var fh: linear int = open(name);
  if (prefer_close == 1) {
    return close(fh);     // then-branch ends in return
  }
  return close(fh);       // OK: each return path consumes exactly once
}
```

The **compatibility** of `linear T` is the same as the base type T (linearity is
a constraint on a separate axis). `var x: int = some_linear_int_var;` is fine as
a type, but may still error in the moved check.

Sample: `src/python-aipl/samples/Linear.abcl`

### 4.7m Phase 13 — CSP Channels

Introduces a **synchronous channel** separate from inter-actor messages. Use it
for producer/consumer, pipelines, `select`-style multi-channel waiting, and so
on.

```
var ch = channel(capacity);                        // capacity 0 = unbounded
var ch = channel(capacity, "int");                 // type hint (advisory)

channel_send(ch, value);                           // blocks if full
var v = channel_recv(ch);                          // blocks if empty
var v = channel_recv(ch, 100);                     // timeout 100ms
var pair = channel_try_recv(ch);                   // (bool ok, any v)
channel_close(ch);
var n = channel_size(ch);

// Wait for the first of multiple channels + timeout
var pick = select_recv([ch1, ch2, ch3], 50);       // tuple(int idx, any v)
                                                    // idx=-1 means timeout
```

`typeof(ch)` is displayed in the form `channel[<element_type>, cap=N]`
(`cap=∞` if unbounded).

**Implementation note:** internally it is a thread-safe Python `queue.Queue`. By
passing channel references between actors, multiple actors can read from and
write to the same channel (the central CSP model). `channel_send` and
`channel_recv` wait even while the receiving actor continues processing.

Sample: `src/python-aipl/samples/Channels.abcl`
(producer/consumer + select + a compile-time-generated pipeline)

### 4.7l Phase 12 — Capability-Based Effect System

Writing `!{...}` at the end of a function/method declaration declares the
**side-effect categories** that function is permitted to emit:

```
function read_config(p: string) -> string !{fs} { ... }
function classify(text: string) -> string !{ai, net} { ... }
function pipeline(p: string) -> string !{fs, ai, net} { ... }
```

The main effect categories:

| Category | Built-ins |
|---|---|
| `fs` | `read_file` / `write_file` / `list_dir` / `mkdir` / `image_load` / ... |
| `net` | `web_listen` / `remote_*` |
| `ai` (`+ net`) | `ai_call_*` / `ai_call_image_*` (LLM calls) |
| `mut` | `compile` / `add_method` / `remove_method` / `spawn` |

**Static propagation:** if function A calls function B (effect `e`), then `e` is
also mixed into A's observed effects. The checker flags when **declared is not a
superset of observed**:

```
function bad(path: string) -> string !{fs} {
  return ai_call(read_file(path));      // ✗ uses {ai, fs, net}, declared only {fs}
}
```

**Gradual:** functions that do **not** write a `!{...}` annotation are skipped
(to avoid breaking existing code). Only annotated functions are checked
strictly.

Sample: `src/python-aipl/samples/Effects.abcl`

### 4.7j AI Actor — Auto-Spawn, now / future Support (Python Runtime)

The AIPL runtime **auto-spawns a global actor named `AI` at startup** (much like
initializing the SDL library). This lets you handle AI through AIPL's standard
actor message protocol instead of hitting the `ai_call_*` built-ins directly:

```
var r = now AI.ask("hello");           // synchronous (wait for reply)
var f = future AI.ask("long task");    // parallel (obtain a Future)
var a = await(f);                       // retrieve later
send AI.ask("fire and forget");         // discard the return value
```

> Note: `call` is an AIPL reserved word (for the `call f(args);` statement), so
> the AI's method names are **`ask` (text) / `see` (image) / `usage`
> (aggregation)** depending on context.

| Method | Role |
|---------|------|
| `AI.ask(prompt)` | Text (auto provider) |
| `AI.ask_p(provider, prompt)` | Text + provider specified |
| `AI.ask_sys(system, prompt)` | With a system prompt |
| `AI.ask_sys_p(provider, system, prompt)` | The above + provider specified |
| `AI.see(prompt, image)` | Multimodal (image input) |
| `AI.see_p(provider, prompt, image)` | The above + provider specified |
| `AI.see_sys(system, prompt, image)` | Image + system |
| `AI.see_sys_p(provider, system, prompt, image)` | Everything |
| `AI.usage()` / `AI.cost()` / `AI.remaining()` | Monitoring |

If you need parallel execution, **create multiple instances with `new AI()`** so
each proceeds independently (1 actor = sequential processing of 1 message).

```
var ai_a = new AI();
var ai_b = new AI();
var fa = future ai_a.ask_p(2, "task A");
var fb = future ai_b.ask_p(3, "task B");
print(await(fa)); print(await(fb));
```

Type inference with `typeof`:

| Expression | typeof result |
|----|-------------|
| `AI` (autospawned) | `actor(AI, methods=[ask, ask_p, ask_sys, ...])` |
| `now AI.ask("x")` | `string` |
| `future AI.ask("x")` | `future` |
| `now AI.see("x", img)` | `string` |

Sample: `src/python-aipl/samples/AIActor.abcl`

### 4.7h AI Calls — Provider Selection and Multimodal (Python Runtime)

Every `ai_call_*` can take an **optional provider as the first argument**:

| Value | Target |
|----|--------|
| `1` / `"gemini"` | Gemini (default) |
| `2` / `"anthropic"` / `"claude"` / `"claudecode"` | Anthropic Claude |
| `3` / `"openai"` / `"chatgpt"` / `"gpt"` | OpenAI ChatGPT |
| `0` / `"auto"` / omitted | Auto-selected from environment variables + API keys |

Setting `AIPL_AI_PROVIDER=mock` routes everything to mock (for tests/demos).

```
ai_call("hello")              // auto-selection
ai_call(1, "hello")           // Gemini
ai_call(2, "hello")           // Claude
ai_call(3, "hello")           // ChatGPT
ai_call("anthropic", "hello") // string alias
ai_call_with_system(2, "be brief", "hi")
```

**Multimodal (image input)** — the `ai_call_image` family was added:

```
var img = image_load("photo.png");
ai_call_image("describe this", img);              // auto-selection
ai_call_image(2, "describe this", img);           // Claude vision
ai_call_image(2, "compare these", img1, img2);    // multiple images OK
ai_call_image_with_system(2, "be brief",
                          "describe", img);
```

Image-input types: the result of image-load/create, an `array[int]` from
`read_bytes(path)`, raw `bytes`, or a `{ path: "x.png" }` record are all
accepted. The MIME type is auto-detected from the magic bytes of PNG / JPEG /
GIF / WebP.

Sample: `src/python-aipl/samples/MultiProvider.abcl`

### 4.7g App / Website Generation — Files / Images / Directories / JSON (Python Runtime)

| Function | Description |
|------|------|
| `read_file(path)` / `write_file(p, s)` / `append_file(p, s)` / `file_exists(p)` | Existing text I/O |
| `read_bytes(p)` / `write_bytes(p, bytes)` / `append_bytes(p, bytes)` | Binary I/O (bytes are an int array of 0–255) |
| `image_load(p)` | Load an image (normalized to RGBA, Pillow) |
| `image_save(img, p)` | Save an image (format determined by extension) |
| `image_create(w, h, r, g, b, a=255)` | Create a solid-color RGBA image |
| `image_pixel(img, x, y)` | Return a `tuple(int, int, int, int)` |
| `image_set_pixel(img, x, y, r, g, b, a=255)` | Overwrite a pixel (mutates) |
| `image_size(img)` | `tuple(width, height)` |
| `list_dir(p)` / `mkdir(p)` / `path_join(...)` / `path_basename(p)` / `path_dirname(p)` | Directory and path operations |
| `json_parse(s)` / `json_stringify(v, indent=2)` | JSON I/O |

`typeof` newly returns **`image(WxH, MODE)`** and **`bytes(N)`**. Since an image
can be read as a record with `.width` / `.height` / `.mode`, it can be embedded
directly into template HTML strings.

```
class SiteGen {
  function build_logo() {
    var img = image_create(64, 64, 0, 0, 0, 0);
    var y = 0;
    while (y < 64) do {
      var x = 0;
      while (x < 64) do {
        image_set_pixel(img, x, y, x*4, y*3, 128, 255);
        x = x + 1;
      } y = y + 1;
    }
    return img;
  }
  method generate(config) {
    mkdir("out_site");
    image_save(build_logo(), "out_site/logo.png");
    write_file("out_site/index.html",
               "<h1>" + config.site_name + "</h1>");
    write_file("out_site/manifest.json", json_stringify(config, 2));
  }
}
```

Sample: `src/python-aipl/samples/SiteGen.abcl`
(emits HTML + CSS + a dynamically generated PNG logo + a JSON manifest in 100%
AIPL)

### 4.7f Dynamic Method Injection / Removal (Python Runtime)

| Function | Description |
|------|------|
| `add_method(target, source)` | If `target` is a class name (string), register the `method ...` declarations in `source` for the whole class; if it is an actor reference, register them for that instance only |
| `remove_method(target, name)` | Remove a method by name |
| `methods_of(target)` | Return an array of the currently available method names |

The output of `typeof(actor)` also includes the method list:
`"actor(Greeter, methods=[greet, init, shout, whisper])"`

Per-actor injection **applies to that instance only**, and takes precedence over
the class level in method resolution.

```
class Greeter {
  var label = "g1";
  method greet(n) { print("[" + label + "] hello, " + n); }
}
var g = new Greeter();
add_method("Greeter",
  "method shout(n) { print(\"[\" + label + \"] HEY!! \" + n); }");
var _ = now g.shout("Alice");            // [g1] HEY!! Alice
remove_method("Greeter", "shout");
```

Sample: `src/python-aipl/samples/MethodPatch.abcl`

> Memo: because methods ride on an actor's asynchronous mailbox, alternating a
> burst of `send a.m()` with `add_method` will **scramble the timing order** (all
> sends are enqueued first, then processed with the final-state method). To
> observe patch ordering in a demo, call via `now` (synchronous).

### 4.7i Type Signatures of Built-in Functions (Python Runtime)

`typeof(name)` returns a signature string even for **a built-in name itself**:

```
typeof(read_bytes)
   → "function(path:string) -> array[int]"
typeof(image_create)
   → "function(w:int, h:int, r:int, g:int, b:int [, a:int=255]) -> image"
typeof(ai_call_image)
   → "function([provider,] prompt:string, image+) -> string"
typeof(json_stringify)
   → "function(value:any [, indent:int]) -> string"
typeof(typeof)
   → "function(value:any) -> string"
```

Built-ins are internally returned as `BuiltinRef(name)` values, and their
signatures are collected in `aipl_interp.py:BUILTIN_SIGNATURES`. On the other
hand, `typeof` of a **call result** returns the structural type of the value:

```
typeof(image_create(8,8,0,200,100,255))   → "image(8x8, RGBA)"
typeof(image_pixel(img, 0, 0))             → "tuple(int, int, int, int)"
typeof(json_stringify({a:1}, 2))           → "string"
```

Sample: `src/python-aipl/samples/Signatures.abcl`

### 4.7e User-Defined Functions (Python Runtime)

```
function name(p1, p2) {
  ...
  return expr;       // synchronous return value
}
```

These can be written **at the top level** as well as **inside a class body**. A
function inside a class can be called without qualification from that class's
methods, and inherits the calling actor's context, so it **can access fields and
call sibling functions**.

```
class StatActor {
  var samples = [];

  function clamp(x, lo, hi) {            // class-local helper
    if (x < lo) { return lo; }
    if (x > hi) { return hi; }
    return x;
  }

  method summary() {
    var v = clamp(samples_avg(), 0, 100);   // unqualified sibling-function call
    reply(v);
  }
}
```

**Trace-based type inference:** writing a bare function name yields a
`FunctionRef` value. `typeof(f)` returns the type signature accumulated from
observed calls:

```
function describe(x) { return typeof(x) + ":" + x; }
describe(1); describe("a"); describe(3.14);
typeof(describe)
   → "function(x:float | int | string) -> string"
```

Sample: `src/python-aipl/samples/Functions.abcl`

### 4.7d Composite Types (Tuples, Python Runtime)

| Notation | Meaning |
|------|------|
| `()` | Empty tuple |
| `(x,)` | 1-tuple (trailing comma required — to distinguish from grouping `(x)`) |
| `(1, 20, "test")` | N-tuple (each slot may have a different type) |
| `(2, (3, 4))` | Nested tuple |
| `t[i]` | Positional access (read-only; tuples are immutable) |

`typeof` returns the per-slot types **including the length**:

```
typeof((1, 20, "test"))  → "tuple(int, int, string)"
typeof((2, (3, 4)))      → "tuple(int, tuple(int, int))"
typeof(())               → "tuple()"
typeof((42,))            → "tuple(int)"
```

Difference from arrays: arrays are same-type and variable-length (length is not
part of the type); tuples are per-position typed, immutable, and **have their
length as part of the type**.

Sample: `src/python-aipl/samples/Tuples.abcl`

### 4.7c Record Types (Python Runtime)

| Notation | Meaning |
|------|------|
| `{ k1: v1, k2: v2, ... }` | Record literal (executed as a Python dict) |
| `r.field` | Field read (chainable: `r.a.b.c`) |
| `r.field = v;` | Field write (chainable) |
| `typeof(v)` | **Structural type inference** — return the value's shape as a string |

`typeof` walks recursively to emit the structure:

```
typeof({ name: "Alice", age: 30 })
   → "record{name:string, age:int}"
typeof({ owner: { id: 1, label: "ops" } })
   → "record{owner:record{id:int, label:string}}"
typeof([1, 2, 3])     → "array[int]"
typeof([1, "a"])      → "array[int | string]"
typeof(42)            → "int"
typeof(actor_ref)     → "actor(ClassName)"
```

A record can be held by a class field as well as by a method's local variable:

```
class Profile {
  var owner = { id: 0, label: "anonymous" };
  var stats = { hits: 0, misses: 0 };
  method touch_hit() { stats.hits = stats.hits + 1; }
}
```

Sample: `src/python-aipl/samples/Records.abcl`

### 4.7b Array Literals and Index Notation (Python Runtime)

| Notation | Meaning |
|------|------|
| `var x = [];` | Empty array |
| `var x = [1, 2, 3];` | Array literal |
| `var x[N];` | **Declare an N-element array** (default value 0) |
| `var x[N] = init;` | Initialize all N to `init` |
| `var grid[R][C];` | **2-dimensional** (R×C, default 0) |
| `var grid[R][C] = init;` | 2-dimensional, all cells `init` |
| `var cube[A][B][C];` | 3-dimensional (any number of dimensions) |
| `x[i]`, `grid[i][j]`, ... | Element read |
| `x[i] = v;`, `grid[i][j] = v;`, ... | Element write |
| `array_len(x)` | Number of (1-D) elements |
| `array_push(x, v)` | Append to the end (in-place, returns None) |

**The size can be any expression**: variables, fields, parameters, and
arithmetic expressions are allowed.

```
class Matrix {
  var rows = 4;
  var cols = 5;
  var cells[rows][cols];                  // dynamic size from field references
  method poke(i, j, v) { cells[i][j] = v; }
}

var R = 3;
var pad[R][R + 1] = -1;                   // local variable + expression
```

`var x[N];` can be used both as a class field declaration and as a method's
local variable. For details see `src/python-aipl/samples/Arrays.abcl` (1-D) and
`samples/MultiDimArrays.abcl` (multi-dimensional).

### 4.8 Dynamic Compilation & Dynamic Actor Creation (Python Runtime Extension)

| Function | Description |
|------|------|
| `compile(source)` | Parse an AIPL source string and register its `class` declarations in the class table. Also execute top-level statements. Returns the number of registered classes |
| `spawn(name, args...)` | Create, as an actor, an instance of the class named by the string (a statically written class, or one registered via `compile`). Also calls `init(args...)` |

This lets you write a **factory that dynamically creates actors in response to a
received message**. For samples see `src/python-aipl/samples/Dynamic.abcl` and
`samples/DynamicWorkerPool.abcl`.

```
class Factory {
  method create(name, source) {
    compile(source);
    reply(spawn(name));
  }
}
var f = new Factory();
var greeter = now f.create("Greeter",
  "class Greeter { method hi(n) { print(\"hello \" + n); } }");
send greeter.hi("world");
```

---

## 5. Sample Programs

### 5.1 Hello — Minimal Sample

`abclc/Hello.abcl`

```
class Hello {
  float count = 0.;

  method init(n) {
    count = n;
    print("Hello object initialized with " + n);
  }

  method greet() {
    print("Hello! count = " + count);
  }

  method inc() {
    count = count + 1.;
    print("count incremented to " + count);
  }
}

var h = new Hello(5);     // ← init(5) is called automatically
send h.greet();           // Hello! count = 5
send h.inc();             // count incremented to 6
send h.greet();           // Hello! count = 6
```

**What you learn:** field declarations, automatic invocation of `init`,
asynchronous messages via `send`, string concatenation with `+`.

Run:

```bash
make run-hello
```

### 5.2 Counter — Self-Messages and Fields

`abclc/counter.abcl`

```
class Counter {
  var count = 0.;
  method inc() {
    count = count + 1.;
    print("count:" + count);
    send self.dec(3.);
  }
  method dec(x) {
    count = count - x;
    print(count);
  }
}

var c1 = new Counter();
var c2 = new Counter();
send c1.inc();
send c2.inc();
```

**What you learn:** sending a message to yourself with `self`, and that multiple
actors have independent mailboxes.

### 5.3 PingPong — Two-Party Message Exchange

`abclc/PingPong.abcl`

```
class Pinger {
  method init() {
    print("Pinger starting");
    send ponger.ping();
  }
  method pong() {
    print("Pinger got pong");
    send sender.ping();
  }
}

class Ponger {
  method ping() {
    print("Ponger got ping");
    send sender.pong();
  }
}

var pinger = new Pinger();
var ponger = new Ponger();
```

**What you learn:** replying to "the immediate sender" via `sender`, and actors
that keep running forever on a cyclic message. You can `send` to an external
actor from within `init`.

### 5.4 Become — Dynamic Behavior Replacement

`abclc/become.abcl`

```
class A {
  method ping() {
    print("A.ping");
    become B();
  }
}

class B {
  method ping() {
    print("B.ping");
    become A();
  }
}

var x = new A();
send x.ping();   // A.ping  → becomes B
send x.ping();   // B.ping  → becomes A
send x.ping();   // A.ping
```

**What you learn:** the behavior of the same actor variable `x` switches with
each receive. Message order is preserved, and `become` takes effect from the
next message.

### 5.5 BoundedBuffer — Producer/Consumer Problem

`abclc/bounded_buffer.abcl` (excerpt)

```
class Buffer {
  var cap = 4;
  var s0 = 0; var s1 = 0; var s2 = 0; var s3 = 0;
  var head = 0; var tail = 0; var count = 0;
  var pwaiter = ""; var pitem = 0;
  var cwaiter = "";

  method put(item) {
    if (cwaiter != "") {
      send sender.put_ok();
      send cwaiter.got(item);
      cwaiter = "";
    } else {
      if (count == cap) {
        pwaiter = sender;     // full → make the producer wait
        pitem   = item;
      } else {
        // ... store into a slot ...
        send sender.put_ok();
      }
    }
  }
  method get() { ... }
}
```

**What you learn:**

- A technique to synchronize **without locks** (holding a wait queue in your own
  fields)
- The asynchronous pattern of saving `sender` and later "returning a response to
  the caller", as in `send pwaiter.put_ok();`
- Expressing a capacity of 4 with slot variables instead of an array (an example
  of writing with the language's minimal features)

Run:

```bash
./run_bounded_buffer.sh
```

### 5.6 Philosophers — Dining Philosophers

`abclc/philosophers.abcl` (excerpt)

```
object Fork {
  int taken = 0;
  method take() {
    if (taken == 0) { taken = 1; }
    else            { send self take; }   // retry if already taken
  }
  method release() { taken = 0; }
}

object Philosopher {
  int id = 0;
  object leftFork;
  object rightFork;

  method think()  { send self hungry; }
  method hungry() {
    send leftFork take;
    send rightFork take;
    send self eat;
  }
  method eat() {
    send leftFork release;
    send rightFork release;
    send self think;
  }
}
```

> Note: the old syntax above (`object`/`int`/the spaced `send X m` form) is kept
> for compatibility with old samples. New samples (`Philosophers5.abcl`, etc.)
> are written in the `class`-based style, which is the recommended style.

**What you learn:** symmetric deadlock among 5 actors, the avoidance technique
via handoff, and that the SDL version (`Philosophers5.abcl`) can also visualize
it.

Run:

```bash
make run-philosophers     # console
./run_viz_philosophers.sh # SDL visual
```

### 5.7 Rotate4Lines — SDL Drawing and Timers

`abclc/Rotate4Lines.abcl`

```
class Line {
  var cx = 0.0; var cy = 0.0;
  var angle = 0.0; var len = 50.0;
  var r = 255; var g = 255; var b = 255;
  var x1 = 0.0; var y1 = 0.0; var x2 = 0.0; var y2 = 0.0;
  var drawn = 0;

  method init(startCx, startCy, startAngle, cr, cg, cb) {
    cx = startCx; cy = startCy; angle = startAngle;
    r = cr; g = cg; b = cb;
  }

  method rotate() {
    if (drawn == 1) { call sdl_erase_line(x1, y1, x2, y2); }
    angle = angle + 3.0;
    var rad = angle * 3.14159 / 180.0;
    var dx = cos(rad) * len;
    var dy = sin(rad) * len;
    x1 = cx - dx; y1 = cy - dy;
    x2 = cx + dx; y2 = cy + dy;
    call sdl_line_c(x1, y1, x2, y2, r, g, b);
    call sdl_present();
    drawn = 1;
    call wait(32);
    send self.rotate();
  }
}

sdl_init(500, 500);
var li1 = new Line(125.0, 125.0,   0.0, 255,  80,  80);
var li2 = new Line(375.0, 125.0,  90.0,  80, 255, 120);
var li3 = new Line(125.0, 375.0, 180.0,  80, 160, 255);
var li4 = new Line(375.0, 375.0, 270.0, 255, 200,  40);
send li1.rotate(); send li2.rotate(); send li3.rotate(); send li4.rotate();
```

**What you learn:** a "homemade timer loop" via the combination of `wait(ms)`
and `send self.rotate()`, and multi-threaded drawing where 4 actors each spin
independently at 30 FPS.

### 5.8 WebCalc — HTTP Gateway and `select`

`src/web_calc1.abcl`

```
class Calc {
  method init() {
    print("Calc initialized");
    send self.main();
  }

  method add(a, b) {
    reply(999);            // an add that arrives early returns 999
  }

  method main() {
    print("waiting...");
    select {
      case add(a, b) -> {
        reply(a + b);     // only adds that arrive while waiting in main compute normally
      }
      timeout 15000 -> {
        print("timeout occurred");
      }
    }
    print("select finished");
  }
}

var calc = new Calc();
web_listen(8080);
web_expose("/calc", "calc");
print("Open http://localhost:8080/ and send to actor 'calc'");
```

**What you learn:**

- How to wait for "only specific messages" with `select`
- The `timeout` clause
- Returning a value to the HTTP response with `reply`
- Turning into an external API with `web_listen` + `web_expose`

Open `http://localhost:8080/` in a browser and POST
`{"method":"add","args":[3,4]}` to the actor `calc`, and 7 is returned.

---

## 6. Phase C-E2 Type Inference (Python Runtime)

In addition to the **gradual static type checking** of the Phase 11 series, the
Python edition of AIPL has, from Phase C onward, **constraint-based
Hindley–Milner type inference + Z3 refinement**. Even without explicit
annotations it assembles type information for the whole program, and the later
Phase E-2 integrated CLI (`--check`) can run type-check and inference at the same
time.

Implementation file: `src/python-aipl/aipl_inference.py` (about 1255 LOC as of
Phase E-2).

### 6.1 CLI: `--infer`, `--check`

| Flag | Role |
|---|---|
| `--type-check` | The Phase 11-series signature-based gradual checker (existing) |
| `--infer` | Run constraint-based HM inference + Z3 refinement (Phases C/D/E), print the inference result per method, and exit |
| **`--check`** | **Run both of the above simultaneously** with section headers (Phase E-2). Get both results in one command |
| `--strict` | Stop with exit code 2 (typeck) / 3 (infer) if there are issues |

```sh
# Inference only
python3 src/python-aipl/aipl_main.py program.aipl --infer

# Integrated: type-check + inference (recommended)
python3 src/python-aipl/aipl_main.py program.aipl --check

# Strict mode: exit if either emits an issue
python3 src/python-aipl/aipl_main.py program.aipl --check --strict
```

`--infer` / `--check` do not run the program (they only run analysis after
parsing and then exit).

### 6.2 Inferred Information

Example output of `--infer` (from `feature_b_crossclass/sample1_simple.aipl`):

```
=== Adder.add ===
  params:
    x : Int
    y : Int
  return : Int

=== Bridge.use_adder ===
  params:
    other : Adder
    a : Int
    b : Int
  return : Int
  locals:
    s : Int

[infer] 2 method(s), 0 unify issue(s), 0 refinement issue(s)
```

From zero-annotation code it **back-infers across classes** everything from
`Adder.add`'s `Int → Int → Int` to `Bridge.use_adder`'s `other : Adder`.

### 6.3 Achieved Features (Phase C → E-2)

| Feature | Phase | Description |
|---|---|---|
| Basic HM type inference | C | Int → Int functions, Bool predicates, automatic Rat/Real inference |
| Cross-class inference (D-1) | D | Argument and return types flow between classes via `now obj.method()` |
| `where` clause (refinement) | E-α | Write `Int where k >= 0 and k <= 100` at the AIPL surface, checked by Z3 |
| Actor field sharing (E-β) | E-β | Fix a class field's `var n = 0;` to one TVar across methods |
| Record structural (E-γ) | E-γ | `{a: Int, b: Str}` structural types + width subtyping |
| Real/Rat refinement (E-γ-R) | E-γ-R | `Real where x > 0.0` decided by Z3's Real theory |
| typeck × inference integration | E-2 | Run type-check + inference in one command via `--check`, sharing `BUILTIN_SIGNATURES` |

### 6.4 Using the `where` Clause

```aipl
class Engine {
  method process(r: Int where r >= 0 and r <= 100) -> Int {
    reply(r * 2);
  }
}
```

A design discovered by evolutionary computation under the
`AIPL_v2_TypeInference` specification. Samples are in
`aice-pi-evolution/experiments/2026-05-17_aipl_v2_type_inference/samples/feature_c_refinement/`.

An unsatisfiable refinement (vacuously false) is checked at **declaration
time**:

```aipl
method bad(k: Int where k >= 5 and k <= 3) -> Int { reply(k); }
// → refinement issue: vacuously false (Z3 unsat)
```

### 6.5 Detailed Documentation

The design and implementation records for each phase are in
`aice-pi-evolution/experiments/2026-05-17_aipl_v2_type_inference/`:

- `PHASE_C_REPORT.md` (HM + Z3 basic implementation)
- `PHASE_D_REPORT.md` (cross-class)
- `PHASE_E_REPORT.md` (`where` clause in grammar)
- `PHASE_E_BETA_REPORT.md` (actor field sharing)
- `PHASE_E_GAMMA_REPORT.md` (record structural)
- `PHASE_E_GAMMA_R_REPORT.md` (Real/Rat refinement)
- `PHASE_E_2_REPORT.md` (`--check` integration)
- `SAMPLES_SNAPSHOT.md` (execution snapshot of 7 features × 3 = 21 samples)

---

## 7. AIPL v2 Distributed Runtime (`aipl_dist`)

`aipl_dist.py` is a module (about 591 LOC) that **opt-in overlays at the runtime
layer** the design discovered by the evolutionary computation of AIPL v2 (2)
"Distributed" (the 3 candidates I0003 balanced / I0023 hang-resilience / I0036
Erlang OTP). The AIPL language specification is unchanged, and existing samples
behave identically without modification.

Implementation files:
- `src/python-aipl/aipl_dist.py` (new module)
- `src/python-aipl/aipl_interp.py` (automatic hook on spawn, +27 lines)
- `src/python-aipl/aipl_runtime.py` (automatic hook on actor failure, +13 lines)

### 7.1 Master Switch

```sh
export AIPL_DIST_ENABLE=1   # ← if this is unset / "0", all features are no-ops
```

Unless you set `AIPL_DIST_ENABLE=1`, the `aipl_dist` functions are **all no-ops
that immediately return None / False**. This structurally guarantees zero impact
on existing programs.

### 7.2 List of the 8 Features (assuming `AIPL_DIST_ENABLE=1`)

| Feature | env var | Description |
|---|---|---|
| **I-1** env_var_routing | `AIPL_ROUTE="Name1:tag1,Name2:tag2"` | An actor-name → tag routing table. Look up with `route_for("Name")` |
| **I-2** structured_log | `AIPL_DIST_LOG_FILE=/path/log.ndjson` | ND-JSON, 1 line/event, thread-safe writes |
| **I-3** token_budget_aware | `AIPL_DIST_RPM=N` / `AIPL_DIST_TPM=N` | Rate-limit AI calls with a 60-second sliding window |
| **I-4** checkpoint_and_resume | `AIPL_DIST_CHECKPOINT_DIR=/path/ck` | Atomically save actor fields, restore on spawn |
| **IQ** quarantine_and_skip | `AIPL_DIST_QUARANTINE_TTL=60` | Auto-quarantine on actor failure; subsequent sends are silently skipped |
| **IM-1** quorum_replicate | `AIPL_DIST_QUORUM_PROVIDERS="openai,anthropic,gemini"` | Send to N providers in parallel and adopt the first to respond |
| **IM-2** subtree_quarantine | `AIPL_DIST_SUBTREE_QUARANTINE=1` | On actor failure, quarantine its descendants too (Erlang OTP style) |
| **integration** | (combination of the above) | Integrate spawn-tree tracking, observability, and resilience |

### 7.3 Quick Start

`AIPL_DIST_ENABLE=1` alone turns on just observability (I-2) and spawn logging:

```sh
AIPL_AI_PROVIDER=mock AIPL_DIST_ENABLE=1 \
  AIPL_DIST_LOG_FILE=/tmp/aipl.ndjson \
  python3 src/python-aipl/aipl_main.py program.aipl

cat /tmp/aipl.ndjson
# {"ts": 1779033685.5..., "event": "actor_spawn", "actor": "counter", "cls": "Counter"}
# {"ts": 1779033685.5..., "event": "actor_routed", "actor": "counter", ...}
```

### 7.4 A Full Set of Countermeasures for the PsiLang v3 Silent-Hang Scenario

For the problem where PsiLang v3 trial #1 lost 35/38 individuals to an OpenAI
silent hang, enabling the 3 MVPs simultaneously gives a **triple defense at the
call-level / actor-level / subtree-level**:

```sh
export AIPL_DIST_ENABLE=1
export AIPL_DIST_QUORUM_PROVIDERS="openai,anthropic,gemini"  # IM-1
export AIPL_DIST_QUARANTINE_TTL=60                          # IQ
export AIPL_DIST_SUBTREE_QUARANTINE=1                       # IM-2
export AIPL_DIST_CHECKPOINT_DIR=/tmp/aipl_ck                # I-4
export AIPL_DIST_LOG_FILE=/tmp/aipl.ndjson                  # I-2
```

- **call-level**: even if OpenAI hangs, anthropic/gemini respond → the caller continues
- **actor-level**: if the actor still dies, it is auto-quarantined (60s)
- **subtree-level**: descendant actors are quarantined together (= Erlang OTP's blast-radius containment)
- **persistent state**: checkpoint is restored on actor re-spawn
- **observability**: all events are recorded in NDJSON

### 7.5 Samples (8 features × 3 = 24)

Organized into per-feature subdirectories under
`aice-pi-evolution/experiments/2026-05-17_aipl_v2_type_inference/IMPL_I0003_MVP/samples/`:

```
samples/
├── i1_env_var_routing/        sample1_basic.aipl, sample2_no_match.py, sample3_log_correlation.py
├── i2_structured_log/         sample1_basic.py, sample2_no_file.py, sample3_multi_thread.py
├── i3_token_budget/           sample1_basic.py, sample2_blocking.py, sample3_aipl_integration.aipl
├── i4_checkpoint/             sample1_basic.py, sample2_atomic.py, sample3_list_states.py
├── iq_quarantine/             sample1_basic.aipl, sample2_ttl_expiry.py, sample3_manual_clear.py
├── im1_quorum/                sample1_first_wins.py, sample2_tolerates_one_failure.py, sample3_all_fail.py
├── im2_subtree_quarantine/    sample1_basic.aipl, sample2_grandchildren.aipl, sample3_unrelated_unaffected.aipl
└── integration/               sample1_basic.aipl, sample2_combined_logging.aipl, sample3_full_resilience.aipl
```

The unit tests are in `IMPL_I0003_MVP/tests/test_aipl_dist.py` (27 of them).

### 7.6 Public API (`aipl_dist` module)

```python
import aipl_dist

# master
aipl_dist.is_enabled()                  -> bool

# I-1 routing
aipl_dist.route_for(name: str)           -> Optional[str]
aipl_dist.parse_route_table(raw: str)    -> dict[str, str]

# I-2 log
aipl_dist.log_event(event, **fields)     -> bool

# I-3 budget
aipl_dist.token_budget_gate()            -> Optional[TokenBudgetGate]
aipl_dist.call_ai_with_budget(prompt, call_ai_fn=None, **kw) -> str

# I-4 checkpoint
aipl_dist.save_actor_state(name, state)  -> bool
aipl_dist.restore_actor_state(name)      -> Optional[dict]
aipl_dist.list_actor_states()            -> dict[str, str]

# IQ quarantine
aipl_dist.quarantine_actor(name, ttl=None) -> bool
aipl_dist.is_quarantined(name)             -> bool
aipl_dist.clear_quarantine(name)           -> bool
aipl_dist.quarantine_status()              -> dict[str, float]

# IM Erlang OTP
aipl_dist.register_spawn(child, parent)    -> None
aipl_dist.descendants_of(actor)            -> list[str]
aipl_dist.quarantine_subtree(actor, ttl=None) -> list[str]
aipl_dist.call_ai_quorum(prompt, providers=None, **kw) -> str
```

All functions are no-ops returning None / False / an empty dict when
`AIPL_DIST_ENABLE != "1"`.

### 7.7 Origin in Evolutionary Design Search

The design of `aipl_dist.py` was not hand-written; it derives from the results
of a MAP-Elites search (8 seeds × 30 generations) of `AIPL_v2_Distributed.aice`
(an 11-axis GA specification):

- Spec: `AIPL_v2_Distributed.aice` / `.ga.json` / `.schema.json` (in `aice-pi-evolution/experiments/2026-05-17_aipl_v2_type_inference/`)
- Run 1 / Run 2 results: `distributed_run_outputs/` (38 individuals / 25 cells / 24 min × 2)
- Design reports: `IMPL_DESIGN.md`, `IMPL_RUN_REPORT.md`, `IMPL_INTEGRATION_REPORT.md`, `IMPL_I0023_REPORT.md`, `IMPL_I0036_REPORT.md`

---

## 8. Appendix: Troubleshooting

| Symptom | Remedy |
|------|------|
| `Unknown function: foo` | A built-in misspelling. Cross-check against the registered name in `prim_table` (`src/eval_thread.ml`) |
| `Actor X not found` | Check whether you did `send X....` before `var X = new ...;` |
| `[Actor] X.init arity mismatch` | The number of args in `new C(args)` differs from `init`'s formal parameters |
| `select` never returns | The pattern does not match the received message / no `timeout` specified |
| The SDL window is unresponsive | Call `sdl_present()` every frame / yield with `wait` |
| HTTP request hangs | You are not calling `reply`, or `select` lacks an appropriate `case` |
| **`[infer] ... unify issue(s)`** | Output of `--infer`. Look at the location (`at assign to s`, etc.) and adjust annotations / reproduce with `AIPL_AI_PROVIDER=mock` |
| **`refinement is vacuously false`** | A `where` clause predicate is unsat in Z3. Review the value range (e.g. `k >= 5 and k <= 3` is the empty set) |
| **`[actor X.Y] error: unknown function: foo`** | A built-in is not registered at runtime. Check `BUILTIN_TABLE` in `aipl_interp.py` |
| **The AIPL runtime silently hangs** | Set `AIPL_DIST_ENABLE=1 AIPL_DIST_QUARANTINE_TTL=60` and re-run. Failed actors are auto-quarantined |
| **You hit the OpenAI tier-1 rate limit** | Enable the I-3 gate with `AIPL_DIST_ENABLE=1 AIPL_DIST_RPM=400 AIPL_DIST_TPM=180000` |
| **An AI call gets stuck on a single provider** | Use `AIPL_DIST_QUORUM_PROVIDERS="openai,anthropic,gemini"` for parallel failover |

> A note on design philosophy: in AIPL, remembering "reply to the sender if you
> want to synchronize, select if you want to wait, become if you want to switch
> state" lets you express most concurrency patterns with language features
> alone. Fault tolerance is **layered on not by the language but by `aipl_dist`'s
> env vars** — the operational pattern after Phase E.
