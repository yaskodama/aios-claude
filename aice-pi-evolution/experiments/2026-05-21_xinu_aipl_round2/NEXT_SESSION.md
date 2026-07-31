# NEXT_SESSION — AIPL × Xinu Round 2 (2026-05-22 close)

Last session landed the full pure-AIPL distributed dining-philosopher
pipeline with three host variants (Python, static AIPL, runtime
bootstrap) all green and reproducible.  This file is the handoff.

## Where we are

```
abclcp-project @ 667c044   (origin: aios-claude.git/main)
xinu-raz/xinu  @ 01ecaea   (origin: xinu-rpi.git/master)
```

Both pushed.  Smoke sweep (7 categories) is recorded in
`SMOKE_SWEEP_2026-05-22.md` next to this file — all PASS, NEW
regression count = 0.

## What works end-to-end now

1. **Xinu direct HTTP** — `apps/abcl_xinu_http.c` listens on port 80,
   served via QEMU SLIRP + hostfwd.  Endpoints `/`, `/api/state`
   (JSON snapshot of all actors + their value_t fields), `/api/actors`,
   `/api/uptime`.  Live dashboard at `http://127.0.0.1:8181/` once
   any `run_diners_*.sh` launcher is up.

2. **Pure-AIPL diners (3 variants)**

   |              | Xinu side                                 | PC side                  | mode        |
   |--------------|-------------------------------------------|--------------------------|-------------|
   | Python legacy| DiningPhilosophersDistXinu.aipl (auto)    | host_diners.py           | UART1 raw   |
   | AIPL static  | DiningPhilosophersDistXinu.aipl (auto)    | host_diners.aipl         | remote() / uart1:// |
   | AIPL bootstrap | DiningPhilosophersDistXinu_NoMain.aipl  | host_diners_bootstrap.aipl | LOAD + SPAWN |

3. **UART1 RPC opcodes**:
   ```
   PING                            → OK pong=1
   LIST                            → OK n_actors=N + N "<id> <class>" lines
   SEND  <id> <method> [args...]   → OK method=… id=…
   QUERY <id> <field_idx>          → OK value=K
   LOAD  <name> <bytes>\n<body>    → OK loaded path=… bytes=…
   COMPILE <name>                  → OK / ERR (in-kernel stack VM only)
   RUN <name>                      → OK ran rc=…  (same VM)
   SPAWN <ClassName> [args...]     → OK actor_id=N        ← new in 01ecaea
   ```

4. **Python AIPL ↔ Xinu bridge** (`src/python-aipl/aipl_remote.py`):
   - `uart1://host:port` URL scheme dispatches the standard
     `remote_send` / `remote_call_sync` builtins onto the UART1
     dispatcher.
   - The meta-actor `"_"` exposes the dispatcher's own opcodes
     (`spawn`, `load`, `compile`, `run`, `list`, `ping`).
   - `_FairLock` is FIFO so concurrent philosopher actors are
     scheduled round-robin (no more P3 starvation).
   - LIST replies (header + N body lines) are properly drained via
     `_uart1_call_multi` so subsequent calls stay aligned.

## How to re-verify (one-shot)

```sh
cd /Users/kodamay/ocaml-app/abclcp-project

# Broadest check, no QEMU, ~30 sec
./aice-pi-evolution/experiments/2026-05-20_xinu_razpi_aipl/_smoke_backwardcompat.sh
# Expect Gate1 88/88, Gate2 75/88 (allowlist).

# Three diners variants (each launches QEMU; Ctrl-C between them)
python3 aice-pi-evolution/experiments/2026-05-20_xinu_remote_rpc/host_diners.py
./aice-pi-evolution/experiments/2026-05-21_xinu_aipl_round2/run_diners_all_aipl.sh
./aice-pi-evolution/experiments/2026-05-21_xinu_aipl_round2/run_diners_bootstrap.sh
```

Browse to `http://127.0.0.1:8181/` while any diners launcher runs to
see the live Xinu actor table.

## Landed in this session's tail

- **`wait(ms)` AIPL builtin for --xinu** (abclcp `0244fc2`, xinu-raz
  `bf00977`).  c_translator mangles `wait` → `b_wait` to avoid the
  Xinu-kernel `wait(semaphore)` collision.  `apps/abcl_xinu_wait.c`
  implements it as a thin `sleep(ms)` wrapper.  Used in
  `abclc/DiningPhilosophersDistXinu_NoMain.aipl::fork_denied` for a
  20-ms retry backoff (was an unbounded native-speed retry loop).

- **`SPAWN ref:N`** (xinu-raz `499a27b`) — tokens prefixed with
  `ref:` resolve to V_OBJ instead of V_INT, so SPAWNed Philosophers
  receive real actor refs in `f_low`/`f_high`.

- **`etherWrite` MMU_RESET_TX on tx-never-done** (xinu-raz `bc908a0`)
  — previously only the alloc-failure path called MMU_RESET_TX.  The
  completion-timeout path now does too; without it a stuck TX page
  would linger and the next ARP refresh from SLIRP would knock the
  kernel over.

Bootstrap demo now reliably completes 2 of 3 PC philosophers
(P3 ≈ 25 attempts, P2 ≈ 90 attempts) plus both Xinu Philosophers.
P1 still hits a `tx never done`-correlated reboot maybe 1 run in 2
on a long-running QEMU; see follow-up #1 below.

## Open follow-ups (none are blocking)

1. **smc91c111 AUTO_RELEASE doesn't work under QEMU**
   - Even with MMU_RESET_TX on both stuck paths, QEMU's smc91c111
     model never asserts INT_TX so each TX leaks its page.  After a
     few SLIRP-initiated ARP probes (~5-10 s apart) the chip state
     degrades enough that the kernel takes a fault and reboots.
   - **Proper fix**: implement AUTO_RELEASE in software — when
     etherInterrupt sees INT_TX (or our poller catches it), read
     the packet number from the chip's TX FIFO header and issue
     `MMU_RELEASE_PACKET <pkt>`.  ~60-100 LOC in
     `device/smc91c111/etherInterrupt.c`.
   - Real-Pi hardware should be unaffected: IRQ 25 will fire,
     AUTO_RELEASE is genuine silicon.  This is a QEMU-only nuisance.

2. **`SPAWN` accepts only V_INT / V_OBJ args**
   - String / float init arguments aren't reachable yet.  Adding
     them needs handle_spawn to detect quoted tokens (a la
     `SPAWN Greeter 0 "hello"`).  Not blocking any current sample.

3. **smc91c111 IRQ poller is a band-aid**
   - The driver still relies on the 5-ms `etherPoll` thread because
     IRQ 25 never asserts on QEMU.  Real-Pi hardware will fire IRQ
     normally — the poller becomes redundant there but harmless.

4. **Debug kprintfs**
   - `etherWrite.c` still kprintfs every `tx len=N` / `tx alloc ok`
     / `tx never done (MMU_RESET_TX recovered)`.  Useful while the
     smc91c111 saga continues; gate behind `#ifdef DEBUG` once #1
     lands.

5. **Round 2 Gemini evolution** — gen 2 of 15 captured in
   `out/AIPL_XinuRazPi_Round2.aipl_lineage.json`.  Best individual
   is `I2: Functional + ADT + actor_messages + capability +
   borrow_check @ 0.471`.  Pull more generations next time the
   GEMINI_API_KEY is fresh.

## Known files (cheat sheet)

```
aice-pi-evolution/experiments/2026-05-21_xinu_aipl_round2/
   AIPL_XinuRazPi_Round2.aice        (design, 27 KB)
   AIPL_XinuRazPi_Round2.ga.json     (mock IR)
   AIPL_XinuRazPi_Round2_ai.ga.json  (AI IR)
   AIPL_XinuRazPi_Round2.aipl        (orchestrator, use_ai=1)
   README.md                          (round 2 plan)
   SMOKE_SWEEP_2026-05-22.md          (most recent sweep)
   NEXT_SESSION.md                    (this file)
   _diag_n1_arp.sh                    (ARP+TCP pcap diag)
   _diag_http_direct.sh               (Xinu HTTP smoke)
   host_diners_web.py                 (legacy PC-bridge dashboard)
   run_diners_web.sh                  (legacy launcher)
   run_diners_xinu_http.sh            (Xinu-direct HTTP launcher)
   run_diners_all_aipl.sh             (pure-AIPL static launcher)
   run_diners_bootstrap.sh            (LOAD + SPAWN launcher)

abclc/
   DiningPhilosophersDistXinu.aipl         (static variant — top-level new)
   DiningPhilosophersDistXinu_NoMain.aipl  (bootstrap variant — classes only)
   NetInitOnlyXinu.aipl                    (minimal NIC-up sample)
   TcpEchoClientXinu.aipl                  (N1 sample)
   RemoteRpcDemoXinu.aipl                  (host_rpc_demo.py target)

aice-pi-evolution/experiments/2026-05-20_xinu_remote_rpc/
   host_diners.py                          (Python legacy)
   host_diners.aipl                        (pure-AIPL static)
   host_diners_bootstrap.aipl              (LOAD + SPAWN)
   host_diners_dynamic.{py,aipl}           (older LOAD/COMPILE/RUN demo)
   host_rpc_demo.{py,sh}                   (smoke #3)

src/python-aipl/aipl_remote.py             (uart1:// scheme + FairLock)
src/c_translator.ml                        (extern abcl_class_name + abcl_lookup_class_id)
xinu/apps/abcl_xinu_rpc.c                  (UART1 dispatcher + SPAWN)
xinu/apps/abcl_xinu_http.c                 (Xinu direct HTTP server)
xinu/apps/abcl_xinu_net.c                  (NIC + abcl_net_autoinit)
xinu/device/smc91c111/etherPoll.c          (5-ms IRQ poller)
xinu/device/smc91c111/etherWrite.c         (TX FIFO reset workaround)
xinu/network/arp/arpLookup.c               (recvclr race fix)
xinu/device/tcp/tcpRead.c                  (partial-read EOF fix)
xinu/system/main.c                         (autoinit + http_start at boot)
xinu/compile/platforms/arm-qemu/xinu.conf  (NTCP = 16)
```

## Tips that bit us this round

- **AIPL `str_len()` is a char count, not a byte count.**  Multi-byte
  UTF-8 glyphs in a `LOAD` body desync the next RPC (Xinu reads exactly
  `len` bytes from the wire; leftover bytes contaminate `SPAWN`).
  Keep `LOAD` source bodies ASCII-only.

- **`send remote(...).M(args)` is OCaml-only** in the AIPL grammar.
  The Py-I parser doesn't recognise that form.  Use `remote_call(...)`
  / `remote_now(...)` as the equivalent in `.aipl` files run by
  `aipl_main.py`.

- **CPython `threading.Lock()` is unfair** under GIL contention.
  Use the `_FairLock` in `aipl_remote.py` whenever multiple actor
  threads share a single physical resource.

- **Xinu UART1 socket is single-client.**  QEMU's `-serial tcp:` only
  accepts one connection.  Don't try to `nc` it while a launcher is
  attached — you'll get a connection refused.  Use HTTP `/api/state`
  for external visibility.

- **The `-net dump` QEMU syntax is gone** in modern releases.  Use
  `-object filter-dump,id=fX,netdev=netY,file=...` with the modern
  `-netdev` form (see `_diag_n1_arp.sh` for the template).
