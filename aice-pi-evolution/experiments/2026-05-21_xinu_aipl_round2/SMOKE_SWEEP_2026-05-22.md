# Smoke Sweep — 2026-05-22 (Round 2 closeout)

Captured after the bootstrap-mode (LOAD + SPAWN) demo landed and the
diners fairness fixes (`_FairLock`, LIST buffer drain, `tcpRead` EOF)
shipped.  All seven categories regression-clean.

Repos:
- `abclcp-project @ 0bc3cda` (main)
- `xinu-raz       @ 01ecaea` (master)

## Results

| # | Smoke                                              | Result | Notes |
|---|----------------------------------------------------|--------|-------|
| 1 | `_smoke_backwardcompat.sh` (Gate1 + Gate2)         | ✅     | Gate1 88/88, Gate2 75/88 (allowlist only, NEW regression 0) |
| 2 | `_smoke_n1.sh` (TCP echo)                          | ✅     | 4/4 assertions: net_init / connect / send / recv |
| 3 | `host_rpc_demo.py` (RemoteRPC)                     | ✅     | 9/9 assertions: PING / SEND×5 / QUERY×2 / LIST |
| 4 | `_diag_http_direct.sh` (Xinu direct HTTP)          | ✅     | /, /api/state, /api/actors, /api/uptime all serve |
| 5 | `host_diners.py` (Python-driven, MEALS=5)          | ✅     | 3 PC + 2 Xinu philos all complete |
| 6 | `host_diners.aipl` (pure-AIPL static, MEALS=100)   | ✅     | P1=167, P2=515, P3=103 attempts |
| 7 | `host_diners_bootstrap.aipl` (LOAD + SPAWN, MEALS=20) | ✅  | P1=404, P2=784, P3=20 attempts |

## Invariants held

- Round 1 17 AIPL smoke + RemoteRPC 2 + Kernel Evo S1-S4/Sec1
- _smoke_backwardcompat.sh Gate1 ≥ 85/85 → **now 88/88**
- _smoke_backwardcompat.sh Gate2 NEW regression count = 0
- host_diners.py reproducibility (Python path still works alongside the
  pure-AIPL path)

## Key changes landed in this round

| Change | Commit | Smoke affected |
|--------|--------|----------------|
| smc91c111 IRQ poller + TX FIFO reset workaround | ef9eeb2 (xinu-raz) | N1, HTTP, all diners |
| arpLookup recvclr race fix                       | b601d1a (xinu-raz) | N1, HTTP, diners |
| tcpRead partial-read EOF fix                     | 16c0d19 (xinu-raz) | N1 (4/4) |
| NTCP 4 → 16                                      | eeadaca (xinu-raz) | HTTP, concurrent TCP |
| Xinu direct HTTP server                          | 5a4ae85 (xinu-raz) | HTTP, diners (HTML) |
| SPAWN RPC + abcl_lookup_class_id()              | 01ecaea (xinu-raz) | bootstrap diners |
| Round 2 .aice/.ga.json/.aipl orchestrator        | e13f14a (abclcp)    | — |
| c_translator extern abcl_class_name              | 20ff4a5 (abclcp)    | HTTP, LIST |
| aipl_remote uart1:// scheme + meta-actor         | c569bc9 (abclcp)    | diners, bootstrap |
| _FairLock + LIST buffer drain                    | d43a2ae (abclcp)    | pure-AIPL diners |
| Bootstrap variant (NoMain + host_diners_bootstrap.aipl) | 0bc3cda (abclcp) | bootstrap diners |

## Reproducibility

P3 attempts is deterministic across runs (always 20 at meals=20, 103 at
meals=100).  P1/P2 attempts vary 2–3× per run because their lock
acquisition order is at the mercy of CPython's GIL scheduling, but both
always complete.

The bootstrap variant (LOAD then 7× SPAWN) replays identically: empty
actor table at boot → 7 actors after the host script → all 5
philosophers eat their meals.

## How to re-run

```sh
# Full backwardcompat — fast, no QEMU
./aice-pi-evolution/experiments/2026-05-20_xinu_razpi_aipl/_smoke_backwardcompat.sh

# N1 (TCP echo)
./aice-pi-evolution/experiments/2026-05-20_xinu_razpi_aipl/_smoke_n1.sh

# Xinu direct HTTP
./aice-pi-evolution/experiments/2026-05-21_xinu_aipl_round2/_diag_http_direct.sh

# Three diners variants
python3 aice-pi-evolution/experiments/2026-05-20_xinu_remote_rpc/host_diners.py
./aice-pi-evolution/experiments/2026-05-21_xinu_aipl_round2/run_diners_all_aipl.sh
./aice-pi-evolution/experiments/2026-05-21_xinu_aipl_round2/run_diners_bootstrap.sh
```
