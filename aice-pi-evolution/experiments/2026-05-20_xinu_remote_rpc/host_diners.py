#!/usr/bin/env python3
"""host_diners.py — 3 PC-side philosophers for the distributed
dining philosophers demo (PC×3 + Xinu×2).

All three host philosophers share a single TCP connection to the
Xinu UART1 dispatcher (QEMU `-serial tcp:` only accepts one client).
A `threading.Lock` serialises request/reply pairs so concurrent
philosopher logic can run, but each call+reply is atomic on the wire.

Fork actors live on Xinu at ids 0..4.  P4 and P5 (Xinu philosophers,
ids 5, 6) run their own AIPL `send`/callback loop and need no help
from the host.

Topology (must match abclc/DiningPhilosophersDistXinu.abcl):
    P1: low=F0  high=F4
    P2: low=F0  high=F1
    P3: low=F1  high=F2

Each PC philosopher eats 3 times then exits.  Eat events print
`[Pn ate meal=K]` to stdout so the smoke can grep them.
"""

from __future__ import annotations
import os
import socket
import sys
import threading
import time


HOST = os.environ.get("RPC_HOST", "127.0.0.1")
PORT = int(os.environ.get("RPC_PORT", "5555"))
MEALS_PER_PHILOSOPHER = 3
ACQUIRE_POLL_MS  = 25
RETRY_BACKOFF_MS = 30
EAT_PAUSE_MS     = 40

PC_PHILOSOPHERS = [
    # (pid, low_fork, high_fork)
    (1, 0, 4),
    (2, 0, 1),
    (3, 1, 2),
]


class SharedRpc:
    """One TCP socket shared by all PC philosophers.  Every call()
    acquires `lock` for the duration of one send+recv_line cycle so
    replies are never mixed up across threads."""

    def __init__(self, host: str = HOST, port: int = PORT) -> None:
        self.sock = socket.create_connection((host, port), timeout=5.0)
        self.sock.settimeout(5.0)
        self.buf  = b""
        self.lock = threading.Lock()
        # Drain the boot greeting line ("OK ready=1\r\n") if any.
        with self.lock:
            try:
                self.sock.settimeout(0.3)
                self._recv_line_locked()
            except (socket.timeout, TimeoutError):
                pass
            self.sock.settimeout(5.0)

    def _recv_line_locked(self) -> str:
        while b"\n" not in self.buf:
            chunk = self.sock.recv(512)
            if not chunk:
                break
            self.buf += chunk
        line, _, rest = self.buf.partition(b"\n")
        self.buf = rest
        return line.decode("ascii", errors="replace").rstrip("\r")

    def call(self, line: str) -> dict[str, str]:
        with self.lock:
            self.sock.sendall((line + "\n").encode("ascii"))
            reply = self._recv_line_locked()
        out: dict[str, str] = {}
        if reply.startswith("OK"):
            out["__ok__"] = "1"
            for tok in reply[3:].split():
                if "=" in tok:
                    k, _, v = tok.partition("=")
                    out[k] = v
        elif reply.startswith("ERR "):
            out["__err__"] = reply[4:].strip()
        else:
            out["__raw__"] = reply
        return out

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def try_acquire(rpc: SharedRpc, fork_id: int, my_pid: int) -> bool:
    """SEND acquire, sleep briefly so the fork actor can process the
    message, then QUERY holder.  True iff holder == my_pid."""
    rpc.call(f"SEND {fork_id} acquire {my_pid}")
    time.sleep(ACQUIRE_POLL_MS / 1000.0)
    q = rpc.call(f"QUERY {fork_id} 0")
    try:
        return int(q.get("value", "-1")) == my_pid
    except ValueError:
        return False


def release(rpc: SharedRpc, fork_id: int, my_pid: int) -> None:
    rpc.call(f"SEND {fork_id} release {my_pid}")


def philosopher_thread(rpc: SharedRpc, pid: int, low: int, high: int) -> None:
    name = f"P{pid}"
    print(f"[{name}] thinking (low=F{low} high=F{high})")
    meals = 0
    attempts = 0
    while meals < MEALS_PER_PHILOSOPHER:
        attempts += 1
        if not try_acquire(rpc, low, pid):
            time.sleep(RETRY_BACKOFF_MS / 1000.0)
            continue
        if not try_acquire(rpc, high, pid):
            release(rpc, low, pid)
            time.sleep(RETRY_BACKOFF_MS / 1000.0)
            continue
        meals += 1
        print(f"[{name} ate meal={meals}] (attempts={attempts})")
        time.sleep(EAT_PAUSE_MS / 1000.0)
        release(rpc, high, pid)
        release(rpc, low, pid)
        # Pause briefly so neighbours can race for forks too.
        time.sleep(0.01)
    print(f"[{name}] done after {attempts} attempts")


def main() -> int:
    print(f"--- host diners on {HOST}:{PORT} "
          f"({len(PC_PHILOSOPHERS)} PC + 2 Xinu) ---")
    rpc = SharedRpc()
    threads = []
    for (pid, low, high) in PC_PHILOSOPHERS:
        t = threading.Thread(target=philosopher_thread,
                             args=(rpc, pid, low, high),
                             name=f"P{pid}", daemon=True)
        threads.append(t)
        t.start()
        # Stagger a tad so the initial acquire wave is interleaved.
        time.sleep(0.03)

    rc = 0
    for t in threads:
        t.join(timeout=90.0)
        if t.is_alive():
            print(f"FAIL {t.name} did not finish within 90s")
            rc = 1

    rpc.close()
    if rc == 0:
        print("--- all PC philosophers finished ---")
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ConnectionRefusedError, OSError) as e:
        print(f"FAIL connect {HOST}:{PORT}: {e}")
        print("Hint: QEMU must be running with "
              "-serial tcp:127.0.0.1:5555,server=on,wait=off")
        sys.exit(2)
