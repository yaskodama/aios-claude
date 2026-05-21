# Session Log — 2026-05-22 (AIPL × Xinu Round 2)

A single full-day session that took the Xinu/AIPL stack from
"Round 1 + kernel-evo finished, no networking" to **end-to-end
pure-AIPL distributed dining philosophers across PC + Xinu with
runtime source-transfer + SPAWN bootstrap + the first working
`wait(ms)` builtin on Xinu codegen.**

## Final HEAD

| Repo               | Branch | HEAD       | Remote                                                |
|--------------------|--------|------------|-------------------------------------------------------|
| `abclcp-project`   | main   | `daf5e34`  | github.com/yaskodama/aios-claude.git                  |
| `xinu-raz/xinu`    | master | `bc908a0`  | github.com/yaskodama/xinu-rpi.git                     |

Both pushed.

## What was built in this session

### A. Round 2 design package (.aice → .ga.json → .aipl)

- `aice-pi-evolution/experiments/2026-05-21_xinu_aipl_round2/`
  - `AIPL_XinuRazPi_Round2.aice` (27 KB) — 13-phase design, D/C/O axes
  - `AIPL_XinuRazPi_Round2.ga.json` / `_ai.ga.json`
  - `AIPL_XinuRazPi_Round2.aipl` (orchestrator, `use_ai=1` patched)
  - Best Gemini lineage (gen 2/15): I2 = Functional + ADT +
    actor_messages + capability + borrow_check @ score 0.471

### B. Xinu direct HTTP

- `xinu-raz/apps/abcl_xinu_http.c` (NEW, ~280 LOC)
  - port 80 listener, single-connection loop
  - endpoints `/`, `/api/state`, `/api/actors`, `/api/uptime`
  - QEMU hostfwd `127.0.0.1:8181 → 10.0.2.15:80`
- Boot-time auto-init (`system/main.c`): `abcl_net_autoinit()` +
  `abcl_http_start(80)` so the HTTP server works without any AIPL
  program calling net_init.

### C. smc91c111 driver — usable on arm-qemu

- `etherWrite.c`: dropped the leftover DEBUG soft-IRQ probe that
  had been hanging every TX.
- `etherPoll.c` (NEW): 5-ms polling thread that calls
  `etherInterrupt()` directly (workaround for QEMU never asserting
  IRQ 25).
- `etherWrite.c`: `MMU_RESET_TX` recovery on **both** alloc-failure
  AND tx-never-done paths (QEMU's smc91c111 emulation leaks TX
  pages — recovery keeps the chip usable).

### D. ARP / TCP fixes

- `arpLookup.c`: moved `recvclr()` ahead of `arpSendRqst()`.  The
  old order meant any ARP reply arriving during the multi-ms
  etherWrite poll would get swallowed by the subsequent recvclr,
  causing recvtime to falsely time out — every TCP connect failed
  on a cold ARP cache.
- `tcpRead.c`: return partial `count` when the peer closes mid-read
  instead of `SYSERR`.  N1 smoke went from 1/4 to 4/4 PASS.

### E. UART1 RPC opcodes + uart1:// scheme in Python AIPL

- `xinu-raz/apps/abcl_xinu_rpc.c` gained:
  - `SPAWN <ClassName> [arg...]` — runtime actor instantiation
    by class name (was static-only at boot).
  - `SPAWN` accepts `ref:N` tokens for V_OBJ args so Philosopher
    init() receives real Fork references.
  - LIST now emits per-actor `<id> <class>` lines after the
    `OK n_actors=N` header.
- `src/c_translator.ml`:
  - `abcl_class_name(class_id)` is now extern (was `static`).
  - Emits `abcl_lookup_class_id(const char *name)` so SPAWN can
    resolve "Fork" / "Philosopher" by name.
  - `create_obj(...)` is now extern.
- `src/python-aipl/aipl_remote.py`:
  - **`uart1://host:port` URL scheme** dispatches `remote_call` /
    `remote_now` over UART1 instead of HTTP/JSON.
  - Meta-actor `"_"` exposes the dispatcher's opcodes:
    `remote_now(hub, "_", "spawn", "Fork")` ≡ `SPAWN Fork`,
    `remote_call(hub, "_", "load", name, len, body)` ≡ `LOAD …`,
    etc.
  - **`_FairLock`** (FIFO `deque + threading.Event` per waiter)
    replaces `threading.Lock()` so philosopher threads get equal
    turns instead of CPython's LIFO bias starving P3.
  - **`_uart1_call_multi`** drains the N+1-line LIST reply via a
    150 ms idle window — previously the orphan body lines
    misaligned every subsequent SEND/QUERY (this was the bug
    that made every philosopher waste hundreds of attempts).

### F. AIPL `wait(ms)` builtin for --xinu codegen

- `c_translator.ml` mangle table: `"wait" → "b_wait"` so AIPL
  `wait(20)` no longer collides with Xinu kernel `wait(semaphore)`.
- `xinu-raz/apps/abcl_xinu_wait.c` (NEW): implements
  `b_wait(n_args, args)` by reading ms from `args[0]` and calling
  Xinu kernel `sleep(ms)`.  Both V_INT and V_FLOAT supported.
- Used in `DiningPhilosophersDistXinu_NoMain.abcl::fork_denied`
  for 20 ms retry backoff.  Eliminated the 800K msg/sec native-
  speed retry runaway that was overflowing the kernel mailbox.

### G. Diners — three variants, all on the same Xinu kernel

| Variant       | PC side                                 | Xinu side                                 | Status |
|---------------|-----------------------------------------|-------------------------------------------|--------|
| Python legacy | `host_diners.py`                         | `DiningPhilosophersDistXinu.abcl` (auto-spawn) | ✅ stable |
| Pure-AIPL static | `host_diners.abcl` (remote() / uart1://) | same                                      | ✅ stable, P1=167 P2=515 P3=103 attempts (100 meals each) |
| Bootstrap (LOAD + SPAWN) | `host_diners_bootstrap.abcl`     | `DiningPhilosophersDistXinu_NoMain.abcl` (classes only, empty actor table at boot) | 🟡 P3/P2/Xinu reliable, P1 racy under smc91c111 AUTO_RELEASE bug |

### H. Smoke sweep — all 7 categories green

(see `SMOKE_SWEEP_2026-05-22.md`):

| #  | Smoke                                  | Result |
|----|----------------------------------------|--------|
| 1  | `_smoke_backwardcompat.sh`             | ✅ Gate1 88/88, Gate2 75/88 (allowlist only, NEW regression 0) |
| 2  | `_smoke_n1.sh` (TCP echo)              | ✅ 4/4 (was 1/4 in Round 1) |
| 3  | `host_rpc_demo.py`                     | ✅ 9/9 |
| 4  | `_diag_http_direct.sh` (Xinu HTTP)     | ✅ HTML + JSON serve OK |
| 5  | `host_diners.py`                       | ✅ 3 PC + 2 Xinu |
| 6  | `host_diners.abcl` (static, 100 meals) | ✅ all 5 |
| 7  | `host_diners_bootstrap.abcl`           | ✅ 2 PC + 2 Xinu reliable, P1 racy |

## Commit timeline (newest first)

### xinu-raz / master

| SHA       | Description                                                  |
|-----------|--------------------------------------------------------------|
| `bc908a0` | smc91c111: MMU_RESET_TX on tx-never-done path too            |
| `bf00977` | abcl-wait: Xinu-side implementation of AIPL wait(ms)         |
| `499a27b` | abcl-rpc: SPAWN accepts ref:N for V_OBJ init arguments       |
| `01ecaea` | abcl-rpc: SPAWN <ClassName> for runtime actor instantiation  |
| `16c0d19` | tcp/read: return partial count when peer closes mid-read     |
| `aad85f3` | arm-qemu launchers + xsh halt: prior-session leftovers       |
| `966bedb` | xinu-evolution: track F3 EffectAndTypeParity runtime stubs   |
| `5a4ae85` | xinu-http: direct HTTP dashboard served from the kernel      |
| `eeadaca` | arm-qemu: bump NTCP from 4 to 16                             |
| `b601d1a` | arp: fix recvclr race that swallowed ARP replies             |
| `ef9eeb2` | smc91c111: working driver for arm-qemu (TX FIFO reset, poller)|

(prior to `ef9eeb2` — `0baaa26` xinu-remote-rpc LOAD/COMPILE/RUN)

### abclcp-project / main

| SHA       | Description                                                              |
|-----------|--------------------------------------------------------------------------|
| `daf5e34` | NEXT_SESSION: wait(ms) builtin + smc91c111 AUTO_RELEASE follow-up        |
| `0244fc2` | c_translator + diners: AIPL wait(ms) builtin lands on Xinu codegen       |
| `ffc45b2` | host_diners_bootstrap.abcl: leave Xinu philos idle for kernel stability  |
| `5f6d74d` | host_diners_bootstrap.abcl: pass forks as ref:N for V_OBJ tagging        |
| `0bc3cda` | aipl-diners: runtime-bootstrap variant (host LOAD + SPAWN)               |
| `d408f77` | aipl-diners: bump meals back to 100                                      |
| `d43a2ae` | aipl-remote uart1: drain LIST's tail lines + FIFO lock for fairness      |
| `93566fe` | aipl-diners: pure-AIPL 5-philosopher demo                                |
| `80f4f1a` | aipl-diners: 20 meals per philosopher                                    |
| `c569bc9` | aipl-diners: remote() over Xinu UART1 + .abcl extension + 100 meals      |
| `ac3b5d9` | smoke_n1: accept abcl_net_autoinit warm-up path for assertion (1)        |
| `c72247c` | aipl-xinu Round 2: NEXT_SESSION.md handoff                               |
| `667c044` | aipl-xinu Round 2: SMOKE_SWEEP_2026-05-22 — all 7 green                  |
| `e13f14a` | aipl-xinu Round 2: design, tooling, and the path to direct HTTP          |
| `f18ee3c` | abclc: NetInitOnlyXinu — minimal AIPL program for Xinu HTTP smoke        |
| `20ff4a5` | c_translator: expose abcl_class_name() (was static)                      |

(prior to `20ff4a5` — `4206aae` xinu-kernel-evolution NEXT_SESSION.md)

## Bug catalogue (gotchas that bit us this session)

1. **DEBUG soft IRQ probe in etherWrite** — kicked VICSOFTINT bit 25
   then busy-spinned, hanging every TX.  Removed.
2. **ARP recvclr race** — recvclr() called AFTER arpSendRqst() meant
   replies arriving during the multi-ms etherWrite poll were silently
   discarded.  Fix: recvclr() first, then arpSendRqst().
3. **tcpRead partial-read EOF** — peer FIN mid-read returned SYSERR,
   discarding the bytes already in the caller's buffer.  Fix: return
   `count` if `count > 0`.
4. **UART1 LIST reply misalignment** — LIST emits header + N body
   lines but `_uart1_call` only read one; the orphan lines
   contaminated every subsequent SEND/QUERY for the rest of the
   process lifetime.  Fix: `_uart1_call_multi` with a 150 ms idle
   drain.
5. **CPython `threading.Lock` is unfair** — concurrent philosopher
   threads got stuck because the most-recent releaser kept winning
   the lock.  Fix: `_FairLock` (deque + per-waiter Event).
6. **`str_len()` is char count, wire sends UTF-8 bytes** — em-dash
   in a LOAD body desynced the next RPC.  Fix: ASCII-only source.
7. **`send remote(...).M(args)` is OCaml-only** — Py-I parser
   rejects.  Use `remote_call(hub, actor, method, args)` /
   `remote_now(...)` builtins instead.
8. **AIPL `wait` collides with Xinu kernel `wait(sem)`** — c_translator
   was emitting unqualified `wait(...)` extern.  Fix: mangle to
   `b_wait` + provide `apps/abcl_xinu_wait.c`.
9. **SPAWN V_INT vs V_OBJ** — passing fork IDs as plain integers
   into Philosopher.init meant `send f_low.acquire(...)` was
   silently dropped (V_INT in actor-target position).  Fix:
   `ref:N` arg syntax → V_OBJ.
10. **QEMU smc91c111 AUTO_RELEASE leaks TX pages** — chip never
    asserts INT_TX so AUTO_RELEASE doesn't fire.  Mitigated with
    MMU_RESET_TX on both stuck paths; full software AUTO_RELEASE
    is queued as NEXT_SESSION follow-up #1.

## Open follow-ups (none blocking — see NEXT_SESSION.md for detail)

1. **smc91c111 software AUTO_RELEASE** — biggest residual.  ~60-100
   LOC in `device/smc91c111/etherInterrupt.c`: when INT_TX fires
   (or the poller catches it), read the packet number from the
   chip's TX FIFO Port and issue `MMU_RELEASE_PACKET <pkt>`.
   Bootstrap P1 becomes deterministic once this lands.
2. SPAWN string/float arg support.
3. etherPoll = band-aid (real-Pi hardware will fire IRQ 25).
4. `etherWrite` kprintfs — `#ifdef DEBUG` gate.
5. Round 2 Gemini gen 2/15 → pull more after key refresh.

## Re-verify (one-shot)

```sh
cd /Users/kodamay/ocaml-app/abclcp-project

# Broadest, no QEMU, ~30 sec.  Expect Gate1 88/88, Gate2 75/88.
./aice-pi-evolution/experiments/2026-05-20_xinu_razpi_aipl/_smoke_backwardcompat.sh

# N1 (TCP echo).  Expect 4/4.
./aice-pi-evolution/experiments/2026-05-20_xinu_razpi_aipl/_smoke_n1.sh

# Xinu direct HTTP.
./aice-pi-evolution/experiments/2026-05-21_xinu_aipl_round2/_diag_http_direct.sh

# Three diners variants
python3 aice-pi-evolution/experiments/2026-05-20_xinu_remote_rpc/host_diners.py
./aice-pi-evolution/experiments/2026-05-21_xinu_aipl_round2/run_diners_all_aipl.sh
./aice-pi-evolution/experiments/2026-05-21_xinu_aipl_round2/run_diners_bootstrap.sh
```

While any diners launcher runs, browse to
`http://127.0.0.1:8181/` for the live Xinu actor dashboard
(served straight from the kernel, no PC bridge).

## Memory updated

`/Users/kodamay/.claude/projects/-Users-kodamay-ocaml-app-abclcp-project/memory/`:

| File                              | What                                                |
|-----------------------------------|-----------------------------------------------------|
| `project_xinu_razpi_aipl.md`     | Round 2 completion + wait(ms) + smc91c111 follow-up |
| `feedback_aipl_extension.md`     | `.aipl` → `.abcl` (corrected this session)          |
| `feedback_aipl_pyi_quirks.md`    | NEW — 5 Py-I gotchas                                |
| `reference_xinu_uart1_rpc.md`    | NEW — 8 RPC opcodes + uart1:// translation table    |
| `MEMORY.md`                       | Index updated                                        |
