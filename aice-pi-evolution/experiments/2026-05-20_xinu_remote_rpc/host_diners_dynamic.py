#!/usr/bin/env python3
"""host_diners_dynamic.py — distributed dining philosophers, but the
PC ALSO uploads + compiles + runs an AIPL source string on Xinu
before the diners eat.

Flow:
  1.  Connect to Xinu UART1 RPC on 127.0.0.1:5555.
  2.  PING + LIST to verify the dispatcher is ready.
  3.  LOAD <name> <byte_count>\\n<source bytes> — ships a small AIPL
      source string from PC to Xinu's in-XFS /home directory.
  4.  COMPILE <name> — Xinu's in-kernel abclcTranslate + ccCompile
      produce a real bytecode a.out at /home/<name>.
  5.  RUN <name> — Xinu's aoutRun executes the bytecode in the
      in-kernel sequential VM.  Output (e.g. the literal 7007) lands
      on UART0; we can grep for it from the QEMU stdio side later.
  6.  THEN the host runs the 3-PC-philosopher dining-philosophers
      loop against the pre-compiled Fork + Philosopher actors that
      were instantiated at kernel boot (DiningPhilosophersDistXinu).
      P4 and P5 self-tick inside Xinu.

Limit: the in-kernel VM (system/aout.c) is a stack-based sequential
interpreter — PUSH / ADD / PRINT etc — so the DYNAMICALLY UPLOADED
program cannot itself spawn actors.  The diner actors are still
pre-compiled into the kernel image.  Step 3-5 prove the upload +
compile + run channel works; step 6 proves the RPC drives those
actors in the same session.
"""

from __future__ import annotations
import os
import socket
import sys
import threading
import time


HOST = os.environ.get("RPC_HOST", "127.0.0.1")
PORT = int(os.environ.get("RPC_PORT", "5555"))

# Tiny AIPL snippet to upload + compile + run.  Must conform to the
# in-kernel `abclc` subset (system/abclc.c): at least one `class` with
# `method`s, a `main { ... }` block, and `printf(...)` calls (NOT the
# `print` builtin used elsewhere in this project — different runtime).
#
# Bytecode VM in system/aout.c is sequential, no actor messages, but
# this single-class single-actor program fits.  Prints "[dyn] x=7007"
# so the QEMU UART0 log contains the literal 7007 we can grep.
DYNAMIC_SOURCE = b"""class Greeter {
  method run() {
    printf("[dyn] hello from in-Xinu compile, x=%d\\n", 7007);
  }
}

main {
  new Greeter g;
  send g.run();
}
"""

MEALS_PER_PHILOSOPHER = int(os.environ.get("MEALS", "5"))
ACQUIRE_POLL_MS  = 25
RETRY_BACKOFF_MS = 30
EAT_PAUSE_MS     = 40
JOIN_TIMEOUT_S   = float(os.environ.get("DINERS_TIMEOUT", "120"))

PC_PHILOSOPHERS = [
    # (pid, low_fork, high_fork)
    (1, 0, 4),
    (2, 0, 1),
    (3, 1, 2),
]


class SharedRpc:
    """One TCP socket shared by all PC philosopher threads.  Every
    call() acquires `lock` for the duration of one send + read-line
    cycle so replies are not crossed across threads."""

    def __init__(self, host: str = HOST, port: int = PORT) -> None:
        self.sock = socket.create_connection((host, port), timeout=10.0)
        self.sock.settimeout(10.0)
        self.buf  = b""
        self.lock = threading.Lock()
        with self.lock:
            try:
                self.sock.settimeout(0.3)
                self._recv_line_locked()
            except (socket.timeout, TimeoutError):
                pass
            self.sock.settimeout(10.0)

    def _recv_line_locked(self) -> str:
        while b"\n" not in self.buf:
            chunk = self.sock.recv(512)
            if not chunk:
                break
            self.buf += chunk
        line, _, rest = self.buf.partition(b"\n")
        self.buf = rest
        return line.decode("ascii", errors="replace").rstrip("\r")

    def _send_locked(self, line: str) -> None:
        self.sock.sendall((line + "\n").encode("ascii"))

    def call(self, line: str) -> dict[str, str]:
        with self.lock:
            self._send_locked(line)
            reply = self._recv_line_locked()
        return _parse(reply)

    def load(self, name: str, source: bytes) -> dict[str, str]:
        """Special-cased: LOAD writes the header line then the raw
        body bytes.  The reply lands after Xinu has fully drained
        the body — same lock-held window so no other thread can
        sneak a request in between."""
        header = f"LOAD {name} {len(source)}\n".encode("ascii")
        with self.lock:
            self.sock.sendall(header + source)
            reply = self._recv_line_locked()
        return _parse(reply)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _parse(reply: str) -> dict[str, str]:
    out: dict[str, str] = {"__raw__": reply}
    if reply.startswith("OK"):
        out["__ok__"] = "1"
        for tok in reply[3:].split():
            if "=" in tok:
                k, _, v = tok.partition("=")
                out[k] = v
    elif reply.startswith("ERR "):
        out["__err__"] = reply[4:].strip()
    return out


def banner(s: str) -> None:
    print(f"\n=== {s} ===")


def expect_ok(label: str, reply: dict[str, str]) -> bool:
    if reply.get("__ok__") == "1":
        print(f"  OK   {label}: {reply}")
        return True
    print(f"  FAIL {label}: {reply}")
    return False


def dynamic_compile(rpc: SharedRpc, name: str = "dyn") -> bool:
    banner("dynamic upload + compile + run")
    if not expect_ok("PING",       rpc.call("PING")):                   return False
    if not expect_ok("LIST init",  rpc.call("LIST")):                   return False
    if not expect_ok(f"LOAD {name}",   rpc.load(name, DYNAMIC_SOURCE)): return False
    if not expect_ok(f"COMPILE {name}", rpc.call(f"COMPILE {name}")):   return False
    if not expect_ok(f"RUN {name}",     rpc.call(f"RUN {name}")):       return False
    return True


def try_acquire(rpc: SharedRpc, fork_id: int, my_pid: int) -> bool:
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
    print(f"  [{name}] thinking (low=F{low} high=F{high})")
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
        print(f"  [{name} ate meal={meals}] (attempts={attempts})")
        time.sleep(EAT_PAUSE_MS / 1000.0)
        release(rpc, high, pid)
        release(rpc, low, pid)
        time.sleep(0.01)
    print(f"  [{name}] done after {attempts} attempts")


def diners(rpc: SharedRpc) -> int:
    banner(f"dining philosophers (3 PC + 2 Xinu, meals={MEALS_PER_PHILOSOPHER} each)")
    threads = []
    for (pid, low, high) in PC_PHILOSOPHERS:
        t = threading.Thread(target=philosopher_thread,
                             args=(rpc, pid, low, high),
                             name=f"P{pid}", daemon=True)
        threads.append(t)
        t.start()
        time.sleep(0.03)

    rc = 0
    for t in threads:
        t.join(timeout=JOIN_TIMEOUT_S)
        if t.is_alive():
            print(f"  FAIL {t.name} did not finish within {JOIN_TIMEOUT_S:.0f}s")
            rc = 1
    return rc


def main() -> int:
    print(f"--- host_diners_dynamic.py — {HOST}:{PORT} ---")
    rpc = SharedRpc()

    if not dynamic_compile(rpc):
        rpc.close()
        return 1

    rc = diners(rpc)

    banner("LIST final")
    print(f"  {rpc.call('LIST')}")
    rpc.close()
    print("\n--- done ---")
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ConnectionRefusedError, OSError) as e:
        print(f"FAIL connect {HOST}:{PORT}: {e}")
        sys.exit(2)
