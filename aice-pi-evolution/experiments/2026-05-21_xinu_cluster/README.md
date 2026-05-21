# N3 multi-Pi actor cluster — Phase A (host side)

**Status:** host side complete (5/5 + 7/7 assertions green), xinu-raz
side **deferred** while `Xinu_KernelEvolution_Round1.aice` is in
progress in the parallel project that owns `xinu-raz/`.

## What this track is

Round 1 of `AIPL_XinuRazPi_Round1.aice` listed N3 as
"multi-Pi actor cluster" — two or more Embedded Xinu instances
participating in one AIPL actor mesh so an actor on node 0 can
message an actor on node 1.

Phase A delivers a **minimal 2-node ping-pong** demo:

```
node 0 Pinger.start  ─XSEND─►  bridge  ─SEND─►  node 1 Ponger.ping(v)
                                                    │
node 0 Pinger.pong(v) ◄─SEND─  bridge  ◄─XSEND─    │
```

Wire transport: each Xinu QEMU child exposes PL011 UART1
(`0x101F2000`) on a host TCP port via
`-serial tcp:127.0.0.1:<5555+node_id>,server=on,wait=off`.
The host bridge sits between those ports, parsing
`XSEND <dst_node> <actor> <method> [arg]` and rewriting to
`SEND <actor> <method> [arg]` on the destination node.

Same `.abcl` source on every node — runtime branch on
`cluster_node_id()` (compile-time `-DNODE_ID=n` macro baked into each
ELF) decides whether to instantiate Pinger or Ponger.

## File map

| Path | Purpose | Status |
|------|---------|--------|
| `abclc/ClusterPingPongXinu.abcl` | AIPL source for the 2-node demo. Branches on `cluster_node_id()`. | ✅ landed |
| `cluster_bridge.py` | Host router. Connects to N nodes, forwards `XSEND` lines. Pure Python stdlib. | ✅ landed |
| `_test_bridge.py` | Unit test for the bridge. Stands up two fake QEMU TCP servers and drives 7 routing assertions. | ✅ 7/7 PASS |
| `_smoke_n3.sh` | Host-side smoke gate. Runs `aipl2c --check`, `aipl2c --xinu`, `_test_bridge.py`. | ✅ 5/5 PASS |

## What is deferred

The C runtime for the three new builtins must be added to xinu-raz:

```c
// File to create:  xinu-raz/apps/abcl_xinu_cluster.c
value_t cluster_send(int n, value_t *a);     // (dst_node:int, actor:int, method:str, arg:int) -> int
value_t cluster_node_id(int n, value_t *a);  // () -> int  (returns the compile-time NODE_ID)
value_t cluster_size(int n, value_t *a);     // () -> int  (returns 2 for Phase A)
```

These are 100% **outside** the kernel-evolution Round 1's
`file_impact.primary_xinu_raz` list — they live under `apps/`, which
the kernel evo's `untouched` block explicitly excludes — so they can
land independently without touching scheduler / memory / NIC / MMU /
syscall layers.

**Sketch (~120 LOC):**

```c
#include <kernel.h>
extern void abcl_uart1_puts(const char *s);   // +2-line wrapper added to apps/abcl_xinu_rpc.c
static int g_node_id = NODE_ID;               // -DNODE_ID=n at make time

value_t cluster_send(int n, value_t *a) {
    if (n < 3) return v_int(0);
    char line[128];
    int len = sprintf(line, "XSEND %ld %ld %s %ld\n",
                      a[0].i, a[1].i, a[2].s, n >= 4 ? a[3].i : 0);
    abcl_uart1_puts(line);
    return v_int(1);
}
value_t cluster_node_id(int n, value_t *a) { return v_int(g_node_id); }
value_t cluster_size(int n, value_t *a)    { return v_int(2); }
```

Also:
- `apps/abcl_xinu_rpc.c`: add `void abcl_uart1_puts(const char *s) { uart1_puts(s); }` (2 lines, non-static wrapper around the existing helper).
- `apps/Makerules`: add `abcl_xinu_cluster.c` to `C_FILES`.

These touch only `apps/` (= kernel evo's untouched set) and `apps/Makerules` (single-line additive edit), so the merge is trivial.

## Integration runbook (when xinu-raz cluster.c lands)

```sh
# 1) Add the cluster.c module + wrapper in xinu-raz (~120 LOC)
#    edit:  xinu-raz/apps/Makerules
#    new:   xinu-raz/apps/abcl_xinu_cluster.c
#    edit:  xinu-raz/apps/abcl_xinu_rpc.c   (add `abcl_uart1_puts` wrapper)

# 2) Build twice (one ELF per node)
for n in 0 1; do
  ./_build/default/src/aipl2c.exe abclc/ClusterPingPongXinu.abcl \
      -o /tmp/cluster_n${n}.c --xinu --max-msgs 0
  cp /tmp/cluster_n${n}.c /Users/kodamay/projects/xinu-raz/xinu/apps/abcl_program.c
  ( cd /Users/kodamay/projects/xinu-raz/xinu/compile && \
    make clean && \
    make PLATFORM=arm-qemu \
         COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi- \
         DEBUG="-DAIPL_AUTOSTART -DNODE_ID=${n}" )
  cp /Users/kodamay/projects/xinu-raz/xinu/compile/xinu.elf /tmp/xinu_n${n}.elf
done

# 3) Launch 2 QEMU instances (UART0=stdio captured, UART1=TCP)
for n in 0 1; do
  qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
      -kernel /tmp/xinu_n${n}.elf -nographic -no-reboot \
      -serial file:/tmp/n${n}.log \
      -serial "tcp:127.0.0.1:$((5555 + n)),server=on,wait=off" &
done

# 4) Start bridge
python3 aice-pi-evolution/experiments/2026-05-21_xinu_cluster/cluster_bridge.py 2 \
    > /tmp/bridge.log 2>&1 &

# 5) Wait + verify digests
sleep 12
grep -E "70000|70001|80001|90002|99999" /tmp/n0.log /tmp/n1.log
grep -E "XSEND|route" /tmp/bridge.log | head
pkill -f qemu-system-arm
pkill -f cluster_bridge.py
```

Expected digest sequence in `/tmp/n1.log`:
```
70001            # Ponger up
80001            # received ping arg=1
80002            # received ping arg=2 (round 2)
...
```

Expected in `/tmp/n0.log`:
```
70000            # Pinger up
90002            # received pong arg=2 (first round closed)
90003            # round 2 closed
...
99999            # Pinger done after 4 rounds
```

## Why split host-first

The kernel-evolution round starting on `xinu-raz/` is high-frequency
churn: scheduler / memory allocator / NIC / MMU work commits multiple
times per session.  Adding `apps/abcl_xinu_cluster.c` to that tree
during peak churn risks (a) merge conflict at `apps/Makerules`, (b) my
work blocking on theirs while the build is mid-refactor.  Landing the
host bridge + AIPL source + the unit-tested routing logic now means:

- The xinu-raz side becomes a **~120 LOC, single-file, ~30 minute** patch
  whenever the kernel evo settles (no design exploration needed).
- The host bridge is already proven 7/7 against fake nodes so the only
  thing left to verify is that `cluster_send` writes valid `XSEND`
  lines into UART1 — which we can debug independently with `nc` if
  needed.

## Future phases (sketched, not yet started)

- **Phase B** (`cluster_migrate(self, dst_node, "tag")`): serialise an
  F1 checkpoint blob across the wire so an actor can move between
  nodes. ~270 LOC, 4 assertions.
- **Phase C** (`cluster_broadcast(method, arg)`): fanout to every
  matching class on every node. Optional WebSocket visualiser. ~250
  LOC.

## Related

- AIPL Round 1: `aice-pi-evolution/experiments/2026-05-20_xinu_razpi_aipl/`
- RemoteRPC track (single-node host RPC): `2026-05-20_xinu_remote_rpc/`
- Parallel project (kernel evolution, DO NOT TOUCH same files):
  `2026-05-21_xinu_kernel_evolution/Xinu_KernelEvolution_Round1.aice`
