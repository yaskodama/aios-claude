#!/usr/bin/env python3
"""_test_bridge.py — unit test for cluster_bridge.py routing logic.

Stands up two fake "QEMU" TCP servers (one per simulated Xinu node),
spawns the bridge as a subprocess that connects to them, then drives a
sequence of XSEND lines through both directions to verify that:

  1. XSEND 1 <a> <m> <v>  emitted on node 0 arrives as SEND <a> <m> <v>
     on node 1.
  2. XSEND 0 <a> <m> <v>  emitted on node 1 arrives as SEND <a> <m> <v>
     on node 0.
  3. Plain text (non-XSEND) emitted by either node is echoed on the
     bridge's stdout with `[node N] ...` prefix.

The test does NOT require Xinu/QEMU or any C-level cluster_send
builtin — it exercises the host bridge in isolation so that Phase A
host-side work can land before the xinu-raz cluster.c module is
ready.  Exits non-zero on any assertion failure.
"""

from __future__ import annotations
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
BRIDGE = HERE / "cluster_bridge.py"

# Use a high port pair so we don't clash with any real QEMU sessions.
PORT_BASE = int(os.environ.get("TEST_PORT_BASE", "16555"))
N_NODES   = 2


class FakeNode:
    """Pretends to be one Xinu QEMU child's UART1 TCP server."""

    def __init__(self, port: int, node_id: int):
        self.port    = port
        self.node_id = node_id
        self.srv     = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", port))
        self.srv.listen(1)
        self.client: socket.socket | None = None
        self.rx_buf = b""
        self.rx_lines: list[str] = []
        self.lock = threading.Lock()

    def accept(self, timeout: float = 5.0) -> None:
        self.srv.settimeout(timeout)
        self.client, _ = self.srv.accept()
        self.client.settimeout(0.1)
        t = threading.Thread(target=self._reader, daemon=True)
        t.start()

    def _reader(self) -> None:
        assert self.client is not None
        while True:
            try:
                chunk = self.client.recv(512)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            self.rx_buf += chunk
            while b"\n" in self.rx_buf:
                line, _, rest = self.rx_buf.partition(b"\n")
                self.rx_buf = rest
                text = line.decode("ascii", errors="replace").rstrip("\r")
                with self.lock:
                    self.rx_lines.append(text)

    def send(self, line: str) -> None:
        assert self.client is not None
        self.client.sendall((line + "\n").encode("ascii"))

    def lines(self) -> list[str]:
        with self.lock:
            return list(self.rx_lines)

    def close(self) -> None:
        for s in (self.client, self.srv):
            if s is None: continue
            try: s.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            try: s.close()
            except OSError: pass


def wait_until(predicate, timeout=3.0, gap=0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(): return True
        time.sleep(gap)
    return False


def main() -> int:
    nodes = [FakeNode(PORT_BASE + i, i) for i in range(N_NODES)]
    bridge_proc: subprocess.Popen | None = None
    rc = 0
    asserts_run = 0
    asserts_pass = 0

    def expect(cond: bool, name: str, detail: str = "") -> None:
        nonlocal asserts_run, asserts_pass, rc
        asserts_run += 1
        if cond:
            asserts_pass += 1
            print(f"  PASS  {name}")
        else:
            rc = 1
            print(f"  FAIL  {name}" + (f"\n        {detail}" if detail else ""))

    bridge_out_buf = []
    bridge_out_lock = threading.Lock()
    def _bridge_stdout_drain(proc):
        if proc.stdout is None: return
        for line in proc.stdout:
            with bridge_out_lock:
                bridge_out_buf.append(line)
    def bridge_out_str() -> str:
        with bridge_out_lock:
            return "".join(bridge_out_buf)

    try:
        # Spawn the bridge; it will connect to each fake server.
        env = dict(os.environ,
                   CLUSTER_HOST="127.0.0.1",
                   CLUSTER_BASE_PORT=str(PORT_BASE),
                   CLUSTER_CONNECT_RETRY="5")
        bridge_proc = subprocess.Popen(
            [sys.executable, str(BRIDGE), str(N_NODES)],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        threading.Thread(
            target=_bridge_stdout_drain, args=(bridge_proc,), daemon=True
        ).start()

        # Accept both bridge connections.
        threads = []
        for n in nodes:
            t = threading.Thread(target=n.accept, daemon=True)
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=6.0)
        expect(
            all(n.client is not None for n in nodes),
            "bridge connects to both nodes",
            detail=f"node 0 client={nodes[0].client} node 1 client={nodes[1].client}",
        )

        ready = wait_until(lambda: "[bridge] ready" in bridge_out_str(), timeout=4.0)
        expect(ready, "bridge prints ready marker")

        # Test 1: node 0 -> XSEND 1 ... → node 1 receives SEND
        nodes[0].send("XSEND 1 0 ping 1")
        got = wait_until(lambda: any("SEND 0 ping 1" in l for l in nodes[1].lines()))
        expect(got, "XSEND from node 0 arrives at node 1 as SEND",
               detail=f"node 1 received: {nodes[1].lines()}")

        # Test 2: node 1 -> XSEND 0 ... → node 0 receives SEND
        nodes[1].send("XSEND 0 0 pong 2")
        got = wait_until(lambda: any("SEND 0 pong 2" in l for l in nodes[0].lines()))
        expect(got, "XSEND from node 1 arrives at node 0 as SEND",
               detail=f"node 0 received: {nodes[0].lines()}")

        # Test 3: non-XSEND text is echoed to bridge stdout
        nodes[0].send("[aipl] hello from node 0")
        got = wait_until(
            lambda: "[node 0] [aipl] hello from node 0" in bridge_out_str(),
            timeout=2.0)
        expect(got, "bridge echoes plain text with [node N] prefix",
               detail=f"stdout tail: {bridge_out_str()[-300:]!r}")

        # Test 4: out-of-bounds dst_node is dropped
        nodes[0].send("XSEND 9 0 nope 0")
        got = wait_until(
            lambda: "BRIDGE-DROP" in bridge_out_str() and "dst=9" in bridge_out_str(),
            timeout=2.0)
        expect(got, "bridge drops out-of-bounds dst_node",
               detail=f"stdout tail: {bridge_out_str()[-300:]!r}")

        # Test 5: self-route (dst == src) is dropped, not looped
        n0_before = len(nodes[0].lines())
        nodes[0].send("XSEND 0 0 self 7")
        time.sleep(0.3)
        n0_after = len(nodes[0].lines())
        expect(n0_after == n0_before,
               "bridge drops self-route XSEND",
               detail=f"node 0 received before={n0_before} after={n0_after}")

    finally:
        if bridge_proc is not None:
            try: bridge_proc.stdin.write("quit\n"); bridge_proc.stdin.flush()
            except (OSError, BrokenPipeError): pass
            try: bridge_proc.terminate()
            except OSError: pass
            try: bridge_proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                bridge_proc.kill()
        for n in nodes: n.close()

    print(f"\n=== _test_bridge.py summary ===")
    print(f"  pass={asserts_pass}/{asserts_run}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
