#!/usr/bin/env python3
"""cluster_bridge.py — Phase-A host router for N3 multi-Pi cluster.

Routes XSEND lines between N Xinu QEMU instances.  Each Xinu instance
exposes its UART1 (PL011 @ 0x101F2000) on a distinct host TCP port
via `-serial tcp:127.0.0.1:<port>,server=on,wait=off`.  The bridge:

  1. Connects to every node's port (retry-on-refused until QEMU comes up).
  2. Reads lines from each node concurrently.
  3. On `XSEND <dst_node> <actor_id> <method> [<arg>]`, rewrites to
     `SEND <actor_id> <method> [<arg>]\\n` and forwards to the destination
     node's socket (per-socket lock so concurrent writers don't interleave).
  4. All other lines are echoed to stdout with a `[node N]` prefix so the
     smoke can grep node-attributed digests.

Phase A is fire-and-forget: there's no ack from the destination back to
the source.  Phase B (actor migration) will add `XMIGRATE` routing.

Usage:
    python3 cluster_bridge.py             # 2 nodes on 5555, 5556
    python3 cluster_bridge.py 3           # 3 nodes on 5555..5557
    CLUSTER_BASE_PORT=5560 python3 cluster_bridge.py 2
    CLUSTER_HOST=10.0.0.5 python3 cluster_bridge.py 4

The bridge runs until SIGINT or stdin EOF.
"""

from __future__ import annotations
import os
import re
import select
import signal
import socket
import sys
import threading
import time


HOST       = os.environ.get("CLUSTER_HOST", "127.0.0.1")
BASE_PORT  = int(os.environ.get("CLUSTER_BASE_PORT", "5555"))
CONNECT_RETRY_S    = float(os.environ.get("CLUSTER_CONNECT_RETRY", "5"))
CONNECT_RETRY_GAP  = 0.1


def _connect_with_retry(host: str, port: int, deadline: float) -> socket.socket:
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            s = socket.create_connection((host, port), timeout=1.0)
            s.settimeout(None)  # blocking; we'll use select() for poll
            return s
        except (ConnectionRefusedError, OSError) as e:
            last_exc = e
            time.sleep(CONNECT_RETRY_GAP)
    raise (last_exc or RuntimeError(f"unreachable: {host}:{port}"))


class Bridge:
    """Owns N TCP sockets, one per node.  Forwarder threads dispatch
    incoming XSEND lines via the appropriate destination lock."""

    XSEND_RE = re.compile(
        r"^XSEND\s+(\d+)\s+(\d+)\s+(\S+)(?:\s+(-?\d+))?\s*$"
    )

    def __init__(self, n_nodes: int) -> None:
        self.n_nodes = n_nodes
        self.socks: list[socket.socket | None] = [None] * n_nodes
        self.locks: list[threading.Lock]       = [threading.Lock() for _ in range(n_nodes)]
        self.bufs:  list[bytes]                = [b""] * n_nodes
        self.stop  = threading.Event()
        self.threads: list[threading.Thread]   = []
        # Stats for unit-testing the routing.
        self.routed_count = 0
        self.echoed_count = 0
        self.stats_lock   = threading.Lock()

    def connect_all(self) -> None:
        deadline = time.monotonic() + CONNECT_RETRY_S
        for n in range(self.n_nodes):
            port = BASE_PORT + n
            sys.stdout.write(f"[bridge] connecting to node {n} on {HOST}:{port} ...\n")
            sys.stdout.flush()
            self.socks[n] = _connect_with_retry(HOST, port, deadline)
            sys.stdout.write(f"[bridge] node {n} ✓\n")
            sys.stdout.flush()

    def send_to(self, node: int, line: str) -> bool:
        sk = self.socks[node]
        if sk is None: return False
        try:
            with self.locks[node]:
                sk.sendall((line + "\n").encode("ascii", errors="replace"))
            return True
        except OSError as e:
            sys.stdout.write(f"[bridge] BRIDGE-DROP node={node}: {e}\n")
            sys.stdout.flush()
            return False

    def _reader(self, node: int) -> None:
        sk = self.socks[node]
        if sk is None: return
        sk.settimeout(0.2)
        while not self.stop.is_set():
            try:
                chunk = sk.recv(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            self.bufs[node] += chunk
            while b"\n" in self.bufs[node]:
                line, _, rest = self.bufs[node].partition(b"\n")
                self.bufs[node] = rest
                text = line.decode("ascii", errors="replace").rstrip("\r")
                self._handle_line(node, text)

    def _handle_line(self, src_node: int, text: str) -> None:
        m = self.XSEND_RE.match(text)
        if m:
            dst   = int(m.group(1))
            actor = int(m.group(2))
            meth  = m.group(3)
            arg   = m.group(4)
            if not (0 <= dst < self.n_nodes):
                sys.stdout.write(f"[bridge] BRIDGE-DROP src={src_node} dst={dst} (oob)\n")
                sys.stdout.flush()
                return
            if dst == src_node:
                sys.stdout.write(f"[bridge] BRIDGE-SELF src={src_node} (drop self-route)\n")
                sys.stdout.flush()
                return
            line = f"SEND {actor} {meth}" + (f" {arg}" if arg is not None else "")
            sys.stdout.write(
                f"[bridge] route src={src_node} dst={dst} "
                f"actor={actor} method={meth} arg={arg or '-'}\n"
            )
            sys.stdout.flush()
            if self.send_to(dst, line):
                with self.stats_lock: self.routed_count += 1
            return
        # Non-XSEND traffic is echoed for the smoke to grep.
        if text:
            sys.stdout.write(f"[node {src_node}] {text}\n")
            sys.stdout.flush()
            with self.stats_lock: self.echoed_count += 1

    def run(self) -> None:
        for n in range(self.n_nodes):
            t = threading.Thread(
                target=self._reader, args=(n,), name=f"reader-{n}", daemon=True
            )
            self.threads.append(t)
            t.start()
        # Drive until stop event.
        try:
            while not self.stop.is_set():
                # Allow Ctrl-C and "quit" on stdin.
                r, _, _ = select.select([sys.stdin], [], [], 0.5)
                if r:
                    line = sys.stdin.readline()
                    if not line or line.strip() == "quit":
                        break
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.stop.set()
        for s in self.socks:
            if s is not None:
                try: s.shutdown(socket.SHUT_RDWR)
                except OSError: pass
                try: s.close()
                except OSError: pass
        for t in self.threads:
            t.join(timeout=1.0)


def main(argv: list[str]) -> int:
    n_nodes = int(argv[1]) if len(argv) > 1 else 2
    if n_nodes < 2:
        print("FAIL: need at least 2 nodes", file=sys.stderr)
        return 2
    br = Bridge(n_nodes)
    def _sigterm(*_): br.shutdown()
    signal.signal(signal.SIGTERM, _sigterm)
    try:
        br.connect_all()
    except OSError as e:
        print(f"FAIL connect: {e}", file=sys.stderr)
        print(f"Hint: each node N must expose UART1 on tcp:{HOST}:{BASE_PORT + 0}+N,"
              f"server=on,wait=off", file=sys.stderr)
        return 2
    sys.stdout.write(f"[bridge] ready — {n_nodes} nodes connected\n")
    sys.stdout.flush()
    br.run()
    sys.stdout.write(
        f"[bridge] done — routed={br.routed_count} echoed={br.echoed_count}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
