"""Distributed actor communication for the Python AIPL runtime.

Wire-compatible with the OCaml runtime's web_gateway.ml so a Python
program can send to actors hosted by an OCaml process and vice versa
without any protocol shim.

Endpoints exposed by start_gateway():
  GET  /                  -> tiny HTML banner
  POST /api/json/send     -> body {"to","method","args","from"}
                             route to a locally-exposed actor
                             (matches src/web_gateway.ml exactly)
  GET  /api/exposed       -> JSON list of exposed actor names

Send side: remote_send(hostport, to, method, args, from) does a
single fire-and-forget POST.  No reply correlation yet — the
receiver can talk back via its own remote_send if it knows the
sender's address.
"""

import hashlib
import hmac
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional


# ---------------------------------------------------------------------------
# HMAC authentication.  Optional — when ABCL_REMOTE_SECRET is set on
# both sides, every POST carries an X-ABCL-Sig header (hex SHA-256
# HMAC of the request body) and the receiver rejects requests whose
# signature doesn't match.

def _shared_secret() -> bytes:
    return os.environ.get("ABCL_REMOTE_SECRET", "").encode("utf-8")


def _sign(body: bytes) -> str:
    return hmac.new(_shared_secret(), body, hashlib.sha256).hexdigest()


def _verify(body: bytes, sig: str) -> bool:
    if not sig:
        return False
    try:
        return hmac.compare_digest(_sign(body), sig)
    except Exception:
        return False


# Registry of actors that should accept remote messages.
_exposed_lock = threading.Lock()
_exposed_actors: dict = {}

# Optional fallback that finds an actor by its variable name in the
# running interpreter's globals — installed by Interpreter.run() so
# any locally-spawned actor is reachable by name from a remote send,
# matching OCaml's "actor_exists" behaviour.  Keeps web_expose
# optional, used only when you want to alias an actor under a
# different public name.
_actor_lookup = None


def set_actor_lookup(callback) -> None:
    """callback(name: str) -> Optional[Actor]"""
    global _actor_lookup
    _actor_lookup = callback


# Track whether a gateway is running so the interpreter knows not to
# auto-shutdown when actors go idle.
_gateway_lock = threading.Lock()
_gateway_count = 0


def _normalize(name: str) -> str:
    """OCaml's web_expose strips a leading slash so `/foo` and `foo`
    register under the same key.  Mirror that on every lookup so
    incoming traffic from an OCaml-style sender lands the same way."""
    n = (name or "").strip()
    if n.startswith("/"):
        n = n[1:]
    return n


def expose(name: str, actor) -> None:
    """Register an actor under a public name.  Subsequent POSTs
    targeting that name from any client (Python or OCaml) are
    delivered to the actor's mailbox."""
    with _exposed_lock:
        _exposed_actors[_normalize(name)] = actor


def find_actor(name: str):
    """Resolve a remote `to` field to a local Actor.  Tries the
    explicit expose() table first (alias names), then the
    interpreter's globals (any local var that holds an actor)."""
    n = _normalize(name)
    with _exposed_lock:
        a = _exposed_actors.get(n)
    if a is not None:
        return a
    if _actor_lookup is not None:
        try:
            return _actor_lookup(n)
        except Exception:
            return None
    return None


def list_exposed_names() -> list:
    with _exposed_lock:
        return list(_exposed_actors.keys())


def is_gateway_running() -> bool:
    with _gateway_lock:
        return _gateway_count > 0


# ---------------------------------------------------------------------------
# HTTP server

class _Handler(BaseHTTPRequestHandler):
    # Silence the default access log so it doesn't crowd actor output.
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self._serve_index()
        elif self.path.startswith("/api/exposed"):
            self._serve_exposed()
        elif self.path.startswith("/healthz"):
            self._serve_healthz()
        else:
            self.send_error(404, "Not Found")

    def _serve_healthz(self):
        body = json.dumps({
            "status": "ok",
            "exposed": list_exposed_names(),
        }).encode("utf-8")
        self._send_bytes(200, "application/json", body)

    def do_POST(self):
        if self.path.startswith("/api/json/send"):
            self._handle_send()
        elif self.path.startswith("/api/json/call"):
            self._handle_call()
        else:
            self.send_error(404, "Not Found")

    def _send_bytes(self, code: int, ctype: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_index(self):
        names = list_exposed_names()
        rows = "".join(f"<li>{n}</li>" for n in names) or "<li><em>(none)</em></li>"
        body = (
            "<!doctype html><meta charset=utf-8>"
            "<style>body{font-family:ui-monospace,Menlo,monospace;margin:2rem;color:#cde;background:#0e1116}"
            "h1{font-size:1rem;color:#8af}li{color:#cde}</style>"
            "<h1>AIPL Python gateway</h1>"
            "<p>Exposed actors:</p><ul>" + rows + "</ul>"
            "<p><small>Wire-compat with OCaml web_gateway: "
            "<code>POST /api/json/send</code></small></p>"
        ).encode("utf-8")
        self._send_bytes(200, "text/html; charset=utf-8", body)

    def _serve_exposed(self):
        body = json.dumps({"exposed": list_exposed_names()}).encode("utf-8")
        self._send_bytes(200, "application/json", body)

    def _read_authed_body(self):
        """Read POST body bytes; if ABCL_REMOTE_SECRET is set, also
        verify the X-ABCL-Sig HMAC.  Returns (str body, ok)."""
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""
        if _shared_secret():
            sig = self.headers.get("X-ABCL-Sig", "")
            if not _verify(raw, sig):
                self.send_error(401, "invalid or missing X-ABCL-Sig")
                return "", False
        return raw.decode("utf-8"), True

    def _handle_send(self):
        body, ok = self._read_authed_body()
        if not ok:
            return
        try:
            payload = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError) as e:
            return self.send_error(400, f"bad json: {e}")
        if not isinstance(payload, dict):
            return self.send_error(400, "json body must be an object")

        to_name = str(payload.get("to", ""))
        method = str(payload.get("method", ""))
        args = payload.get("args", []) or []
        if not isinstance(args, list):
            return self.send_error(400, "args must be an array")
        from_name = str(payload.get("from", ""))

        actor = find_actor(to_name)
        if actor is None:
            print(f"[gateway] unknown actor: {to_name!r} (from={from_name})")
            return self.send_error(404, f"no exposed actor: {to_name}")

        # Print so a server-side .abcl program shows traffic in its
        # log without explicit handler instrumentation.
        print(f"[gateway] -> {to_name}.{method}({args}) from={from_name!r}", flush=True)
        try:
            from aipl_events import publish as _pub
            _pub("remote_in", to=to_name, method=method, sync=False, from_=from_name)
        except Exception:
            pass

        try:
            actor.send_method(method, list(args), sender=None)
        except Exception as e:
            return self.send_error(500, f"dispatch failed: {e}")

        body_ok = b'{"ok":true}'
        self._send_bytes(200, "application/json", body_ok)

    def _handle_call(self):
        """Synchronous remote call: dispatch with a Future and block
        the HTTP response until the actor's reply() arrives (or the
        method returns without one — then reply is null).  Wire shape:

          POST /api/json/call
          body: {"to":"name","method":"m","args":[...],"from":"who"}
          resp 200 application/json: {"ok": true, "reply": <value>}

        Optional `?timeout_ms=N` query (default 30 000)."""
        body, ok = self._read_authed_body()
        if not ok:
            return
        try:
            payload = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError) as e:
            return self.send_error(400, f"bad json: {e}")
        if not isinstance(payload, dict):
            return self.send_error(400, "json body must be an object")

        to_name = str(payload.get("to", ""))
        method = str(payload.get("method", ""))
        args = payload.get("args", []) or []
        if not isinstance(args, list):
            return self.send_error(400, "args must be an array")
        from_name = str(payload.get("from", ""))

        timeout_ms = 30_000
        if "?" in self.path:
            from urllib.parse import parse_qs, urlsplit
            q = parse_qs(urlsplit(self.path).query)
            if q.get("timeout_ms"):
                try:
                    timeout_ms = int(q["timeout_ms"][0])
                except ValueError:
                    pass

        actor = find_actor(to_name)
        if actor is None:
            return self.send_error(404, f"no exposed actor: {to_name}")

        from aipl_runtime import Future
        fut = Future()
        print(f"[gateway] (call) -> {to_name}.{method}({args}) from={from_name!r}", flush=True)
        try:
            from aipl_events import publish as _pub
            _pub("remote_in", to=to_name, method=method, sync=True, from_=from_name)
        except Exception:
            pass
        try:
            actor.send_method(method, list(args), sender=None, reply_future=fut)
        except Exception as e:
            return self.send_error(500, f"dispatch failed: {e}")

        value = fut.get(timeout=timeout_ms / 1000.0)
        body_resp = json.dumps({"ok": True, "reply": value}).encode("utf-8")
        self._send_bytes(200, "application/json", body_resp)


def start_gateway(port: int, *, host: str = "0.0.0.0") -> None:
    """Start the HTTP gateway on a daemon thread.  Returns once the
    listen socket is bound.  Multiple calls are allowed (each binds a
    separate port); is_gateway_running() goes True after the first."""
    server = HTTPServer((host, port), _Handler)
    global _gateway_count
    with _gateway_lock:
        _gateway_count += 1
    t = threading.Thread(
        target=server.serve_forever,
        name=f"abcl-gateway-{port}",
        daemon=True,
    )
    t.start()
    print(f"[gateway] listening on http://{host}:{port}/")


# ---------------------------------------------------------------------------
# Client side

def _make_signed_request(url: str, payload: bytes) -> "urllib.request.Request":
    headers = {"Content-Type": "application/json"}
    if _shared_secret():
        headers["X-ABCL-Sig"] = _sign(payload)
    return urllib.request.Request(url, data=payload, method="POST", headers=headers)


def _publish_remote_out(hostport: str, to_actor: str, method: str, sync: bool):
    try:
        from aipl_events import publish
        publish("remote_out", host=hostport, to=to_actor, method=method, sync=sync)
    except Exception:
        pass


# ─── uart1:// scheme — talk Xinu RPC dispatcher over a serial TCP socket
#
# When a remote() call addresses "uart1://host:port", the wire protocol is
# the line-oriented Xinu UART1 RPC (PING/SEND/QUERY/LIST) instead of the
# JSON/HTTP gateway.  This lets pure-AIPL programs orchestrate the Xinu
# AIPL actor table without going through the HTTP gateway (which would
# need Xinu's smc91c111 stack + a JSON parser).
#
# Method-to-wire mapping:
#   send remote(uart1://...).M(a1, a2, ...)  →  "SEND <actor> M a1 a2\n"
#   now  remote(uart1://...).field(N)        →  "QUERY <actor> N\n"
#                                             →  reply parsed as int
#                                                ("OK value=K"  → K)
#   now  remote(uart1://...).ping()          →  "PING\n"   → raw reply line
#   now  remote(uart1://...).list()          →  "LIST\n"   → raw reply line
import socket
import threading

_UART1_SOCKETS: dict = {}
_UART1_LOCK = threading.Lock()

def _is_uart1(hostport: str) -> bool:
    return isinstance(hostport, str) and hostport.startswith("uart1://")

def _uart1_target(hostport: str) -> tuple:
    raw = hostport[len("uart1://"):]
    if ":" in raw:
        host, port_s = raw.split(":", 1)
        return host, int(port_s)
    return raw, 5555

def _uart1_get_socket(hostport: str) -> socket.socket:
    """One socket per uart1 endpoint, lazily opened.  The Xinu UART1
    dispatcher is single-client (QEMU `-serial tcp:...` accepts one
    connection), so a single shared socket with an external lock is
    the right model."""
    with _UART1_LOCK:
        s = _UART1_SOCKETS.get(hostport)
        if s is not None:
            return s
        host, port = _uart1_target(hostport)
        s = socket.create_connection((host, port), timeout=10.0)
        s.settimeout(10.0)
        # Drain the boot greeting if any (e.g. "OK ready=1").
        try:
            s.settimeout(0.3)
            s.recv(256)
        except (socket.timeout, TimeoutError, OSError):
            pass
        s.settimeout(10.0)
        _UART1_SOCKETS[hostport] = s
        return s

def _uart1_recv_line(s: socket.socket, buf_holder: list) -> str:
    """Read one \\n-terminated line, buffering leftovers."""
    buf = buf_holder[0] if buf_holder else b""
    while b"\n" not in buf:
        chunk = s.recv(512)
        if not chunk:
            break
        buf += chunk
    line, _, rest = buf.partition(b"\n")
    if buf_holder:
        buf_holder[0] = rest
    else:
        buf_holder.append(rest)
    return line.decode("ascii", errors="replace").rstrip("\r")

# Persistent recv buffer per socket so partial reads survive across calls.
_UART1_BUFS: dict = {}

def _uart1_call(hostport: str, command: str) -> str:
    """Send `command` (without trailing newline), return one reply line.
    Lock-serialised so concurrent actors don't interleave on the wire."""
    s = _uart1_get_socket(hostport)
    with _UART1_LOCK:
        buf_holder = _UART1_BUFS.setdefault(hostport, [b""])
        s.sendall((command + "\n").encode("ascii"))
        return _uart1_recv_line(s, buf_holder)

def _uart1_remote_send(hostport: str, to_actor: str, method: str,
                       args: list) -> None:
    """Async wire form for the Fork/Counter/Greeter style actors:
       SEND <id> <method> [arg1] [arg2] ...
    The Xinu RPC dispatcher acks with "OK method=... id=...".  We
    drop the ack here because fire-and-forget semantics."""
    parts = ["SEND", str(to_actor), method] + [str(a) for a in args]
    _uart1_call(hostport, " ".join(parts))

def _uart1_remote_call_sync(hostport: str, to_actor: str, method: str,
                            args: list):
    """Sync remote() calls.  Special methods:
       field(i) -> int           (= QUERY <actor> i, parse "value=K")
       ping()   -> str           (= PING)
       list()   -> str           (= LIST)
       (other)  -> raw reply line (=SEND-style; not usually useful sync)"""
    if method == "field":
        idx = int(args[0]) if args else 0
        line = _uart1_call(hostport, f"QUERY {to_actor} {idx}")
        # "OK value=K" → K, "ERR ..." → None
        if line.startswith("OK"):
            for tok in line[3:].split():
                if tok.startswith("value="):
                    try:
                        return int(tok.split("=", 1)[1])
                    except ValueError:
                        return tok.split("=", 1)[1]
        return None
    if method == "ping":
        return _uart1_call(hostport, "PING")
    if method == "list":
        return _uart1_call(hostport, "LIST")
    # Fallback: SEND-style as a sync call returning the dispatcher's
    # ack line ("OK method=... id=..." or "ERR ...").
    parts = ["SEND", str(to_actor), method] + [str(a) for a in args]
    return _uart1_call(hostport, " ".join(parts))


def remote_send(hostport: str, to_actor: str, method: str,
                args: list, from_name: str = "") -> None:
    """Fire-and-forget remote send.  Matches the OCaml
    Remote_client.remote_send wire format."""
    if _is_uart1(hostport):
        _publish_remote_out(hostport, to_actor, method, sync=False)
        try:
            _uart1_remote_send(hostport, to_actor, method, args)
        except OSError as e:
            print(f"[remote_send uart1] {hostport}/{to_actor}.{method} failed: {e}")
        return
    url = f"http://{hostport}/api/json/send"
    payload = json.dumps({
        "to":     to_actor,
        "method": method,
        "args":   list(args),
        "from":   from_name,
    }).encode("utf-8")
    req = _make_signed_request(url, payload)
    _publish_remote_out(hostport, to_actor, method, sync=False)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        print(f"[remote_send] {hostport}/{to_actor}.{method} HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        print(f"[remote_send] {hostport}/{to_actor}.{method} failed: {e.reason}")


def remote_call_sync(hostport: str, to_actor: str, method: str,
                     args: list, from_name: str = "",
                     timeout_s: float = 30.0):
    """Synchronous remote call: blocks until the receiver's actor
    method calls reply(value) (or returns without one — then None).
    Returns the JSON-decoded reply value."""
    if _is_uart1(hostport):
        _publish_remote_out(hostport, to_actor, method, sync=True)
        try:
            return _uart1_remote_call_sync(hostport, to_actor, method, args)
        except OSError as e:
            raise RuntimeError(f"remote_call uart1 {hostport}/{to_actor}.{method} failed: {e}")
    url = f"http://{hostport}/api/json/call?timeout_ms={int(timeout_s * 1000)}"
    payload = json.dumps({
        "to":     to_actor,
        "method": method,
        "args":   list(args),
        "from":   from_name,
    }).encode("utf-8")
    req = _make_signed_request(url, payload)
    _publish_remote_out(hostport, to_actor, method, sync=True)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s + 5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("reply")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"remote_call {hostport}/{to_actor}.{method} HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"remote_call {hostport}/{to_actor}.{method} failed: {e.reason}")
