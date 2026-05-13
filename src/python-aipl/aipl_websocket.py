"""aipl_websocket.py — minimal WebSocket integration for python-aipl.

Mirrors the JS-Node sibling (src/node-aipl-server/server.mjs) and the
OCaml gateway's ws_clients shape:

  - `ws_listen(port)`     — start a WebSocket server on `port`.
                            Each connection is keyed by the `?sid=<id>`
                            query parameter; clients with the same sid
                            form a broadcast group.
  - `ws_send(sid, msg)`   — push `msg` (string) to every client of `sid`.
                            Returns the count of recipients.
  - `ws_close(port)`      — shut down a listener started with ws_listen.

The server runs in a background daemon thread with its own asyncio
loop so AIPL programs (which are synchronous from the language side)
can drive it without restructuring.  The `websockets` library is
imported lazily so smoke tests on machines without it skip cleanly.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Dict, Set, Optional


# Lazy import: only fail when ws_* is actually called without the lib.
def _import_websockets():
    try:
        import websockets  # type: ignore
        return websockets
    except ImportError as e:
        raise RuntimeError(
            "websockets library not installed.  Install with: "
            "pip install websockets") from e


# Per-port server state, keyed by listening port.
_servers: Dict[int, "_WsServer"] = {}
_servers_lock = threading.Lock()


class _WsServer:
    """A running WebSocket listener with sid-keyed broadcast groups."""

    def __init__(self, port: int):
        self.port = port
        self.clients: Dict[str, Set] = {}     # sid -> set of WebSocket objs
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.server = None  # websockets.Server
        self.ready_evt = threading.Event()
        self.lock = threading.Lock()

    def start(self):
        websockets = _import_websockets()

        async def handler(ws):
            sid = "default"
            try:
                # Newer websockets versions: ws.request.path or ws.path.
                path = getattr(getattr(ws, "request", None), "path", None) \
                       or getattr(ws, "path", "/")
                if "?sid=" in path:
                    sid = path.split("?sid=", 1)[1].split("&", 1)[0]
            except Exception:
                pass
            with self.lock:
                self.clients.setdefault(sid, set()).add(ws)
                peers = len(self.clients[sid])
            try:
                await ws.send(
                    '{"kind":"welcome","sid":"' + sid +
                    '","peers":' + str(peers) + '}')
                async for msg in ws:
                    text = msg if isinstance(msg, str) else msg.decode()
                    # Re-broadcast to peers (not back to sender).
                    with self.lock:
                        peers_set = list(self.clients.get(sid, set()))
                    for peer in peers_set:
                        if peer is not ws:
                            try:
                                await peer.send(text)
                            except Exception:
                                pass
            finally:
                with self.lock:
                    s = self.clients.get(sid)
                    if s and ws in s:
                        s.remove(ws)
                        if not s:
                            del self.clients[sid]

        async def runner():
            self.server = await websockets.serve(handler, "0.0.0.0", self.port)
            self.ready_evt.set()
            # keep loop alive
            await asyncio.Future()

        def thread_main():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(runner())
            except asyncio.CancelledError:
                pass

        self.thread = threading.Thread(target=thread_main, daemon=True,
                                        name=f"aipl-ws-{self.port}")
        self.thread.start()
        self.ready_evt.wait(timeout=2.0)

    def broadcast(self, sid: str, message: str) -> int:
        if self.loop is None:
            return 0
        with self.lock:
            peers = list(self.clients.get(sid, set()))
        if not peers:
            return 0
        fut = asyncio.run_coroutine_threadsafe(
            self._do_broadcast(peers, message), self.loop)
        try:
            return fut.result(timeout=1.0)
        except Exception:
            return 0

    async def _do_broadcast(self, peers, message: str) -> int:
        n = 0
        for ws in peers:
            try:
                await ws.send(message)
                n += 1
            except Exception:
                pass
        return n

    def stop(self):
        if self.loop is None:
            return
        async def shutdown():
            if self.server is not None:
                self.server.close()
                await self.server.wait_closed()
            for t in asyncio.all_tasks(self.loop):
                t.cancel()
        try:
            fut = asyncio.run_coroutine_threadsafe(shutdown(), self.loop)
            fut.result(timeout=1.0)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread:
            self.thread.join(timeout=1.0)


# ---------- AIPL-facing API ----------

def ws_listen(port: int) -> int:
    """Start (or no-op re-use) a WebSocket listener on `port`."""
    port = int(port)
    with _servers_lock:
        if port in _servers:
            return port
        srv = _WsServer(port)
        _servers[port] = srv
    srv.start()
    return port


def ws_send(sid: str, message: str, port: Optional[int] = None) -> int:
    """Broadcast `message` to all WS clients on `sid`.

    If `port` is None and exactly one ws_listen() has been called,
    use that port.  Otherwise raise.
    """
    sid = str(sid)
    message = str(message)
    with _servers_lock:
        if port is None:
            if len(_servers) == 1:
                port = next(iter(_servers))
            else:
                raise RuntimeError(
                    "ws_send: pass `port` when multiple listeners exist")
        port = int(port)
        srv = _servers.get(port)
    if srv is None:
        raise RuntimeError(f"ws_send: no listener on port {port}")
    return srv.broadcast(sid, message)


def ws_close(port: int) -> None:
    port = int(port)
    with _servers_lock:
        srv = _servers.pop(port, None)
    if srv is not None:
        srv.stop()


def ws_status() -> dict:
    """Diagnostic: list listening ports and peer counts per sid."""
    with _servers_lock:
        out = {}
        for port, srv in _servers.items():
            with srv.lock:
                out[port] = {sid: len(peers)
                             for sid, peers in srv.clients.items()}
        return out
