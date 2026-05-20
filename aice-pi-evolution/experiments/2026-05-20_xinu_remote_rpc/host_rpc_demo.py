#!/usr/bin/env python3
"""host_rpc_demo.py — H4 reference client (stdlib socket only).

Same conversation as host_rpc_demo.sh but each reply is parsed into a
dict, assertions are run inline, and a non-zero exit code is returned
on any mismatch.  Useful as the green-light gate in _smoke_remote_rpc.sh.

Usage:
    python3 host_rpc_demo.py          # 127.0.0.1:5555
    RPC_HOST=10.0.0.5 RPC_PORT=5555 python3 host_rpc_demo.py
"""

from __future__ import annotations
import os
import socket
import sys
import time


HOST = os.environ.get("RPC_HOST", "127.0.0.1")
PORT = int(os.environ.get("RPC_PORT", "5555"))
TIMEOUT_S = float(os.environ.get("RPC_TIMEOUT", "5.0"))


def open_conn() -> socket.socket:
    s = socket.create_connection((HOST, PORT), timeout=TIMEOUT_S)
    s.settimeout(TIMEOUT_S)
    return s


def call(sock: socket.socket, cmd: str) -> str:
    sock.sendall((cmd + "\n").encode("ascii"))
    # Read until we see a LF.  The kernel dispatcher writes "...\r\n",
    # so strip both at the end.
    buf = bytearray()
    deadline = time.monotonic() + TIMEOUT_S
    while time.monotonic() < deadline:
        chunk = sock.recv(256)
        if not chunk:
            break
        buf.extend(chunk)
        if b"\n" in buf:
            line, _, _ = buf.partition(b"\n")
            return line.decode("ascii", errors="replace").rstrip("\r")
    raise TimeoutError(f"no reply within {TIMEOUT_S}s for {cmd!r}")


def parse_reply(reply: str) -> dict[str, str]:
    """Parse 'OK k1=v1 k2=v2' or 'ERR reason' into a dict.

    For ERR the dict has key '__err__' = the reason.  For OK the keys
    are the leading 'k=v' pairs and '__ok__' = '1'.
    """
    out: dict[str, str] = {}
    if reply.startswith("ERR "):
        out["__err__"] = reply[4:].strip()
        return out
    if not reply.startswith("OK"):
        out["__err__"] = f"unexpected reply: {reply!r}"
        return out
    out["__ok__"] = "1"
    for tok in reply[3:].split():
        if "=" in tok:
            k, _, v = tok.partition("=")
            out[k] = v
    return out


def assert_ok(label: str, reply: dict, **want) -> None:
    if "__err__" in reply:
        print(f"FAIL {label}: {reply['__err__']}")
        sys.exit(1)
    for k, v in want.items():
        got = reply.get(k)
        if got != str(v):
            print(f"FAIL {label}: expected {k}={v}, got {k}={got!r} "
                  f"(full reply: {reply})")
            sys.exit(1)
    print(f"OK   {label}: {reply}")


def main() -> int:
    print(f"--- connecting to {HOST}:{PORT} ---")
    with open_conn() as s:
        # The dispatcher writes 'OK ready=1' as soon as the thread is
        # up.  Drain it (best-effort) so subsequent reads are aligned.
        s.settimeout(1.0)
        try:
            greet = s.recv(64).decode("ascii", errors="replace")
            print(f"[greet] {greet.strip()!r}")
        except (socket.timeout, TimeoutError):
            print("[greet] (no banner — already drained or late)")
        s.settimeout(TIMEOUT_S)

        # The 9-command demo.  Every assertion is a single line so it
        # is obvious which step failed if the kernel is slow.
        assert_ok("PING",
                  parse_reply(call(s, "PING")),
                  pong="1")

        assert_ok("SEND 0 bump (1)",
                  parse_reply(call(s, "SEND 0 bump")),
                  method="bump", id="0")
        assert_ok("SEND 0 bump (2)",
                  parse_reply(call(s, "SEND 0 bump")),
                  method="bump", id="0")
        assert_ok("SEND 0 dump",
                  parse_reply(call(s, "SEND 0 dump")),
                  method="dump", id="0")

        assert_ok("SEND 1 set_who 42",
                  parse_reply(call(s, "SEND 1 set_who 42")),
                  method="set_who", id="1")
        assert_ok("SEND 1 hello",
                  parse_reply(call(s, "SEND 1 hello")),
                  method="hello", id="1")

        # Give the actors a moment to consume the mailbox before
        # observing their fields (the mailbox is MPSC so dispatch is
        # asynchronous from the dispatcher's reply).
        time.sleep(0.5)

        assert_ok("QUERY 0 0  (Counter.n)",
                  parse_reply(call(s, "QUERY 0 0")),
                  value="2")
        assert_ok("QUERY 1 0  (Greeter.who_tag)",
                  parse_reply(call(s, "QUERY 1 0")),
                  value="42")
        assert_ok("LIST",
                  parse_reply(call(s, "LIST")),
                  n_actors="2")

    print("--- all assertions PASS ---")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ConnectionRefusedError, OSError) as e:
        print(f"FAIL connect {HOST}:{PORT}: {e}")
        print("Hint: QEMU must be running with "
              "-serial tcp:127.0.0.1:5555,server=on,wait=off")
        sys.exit(2)
