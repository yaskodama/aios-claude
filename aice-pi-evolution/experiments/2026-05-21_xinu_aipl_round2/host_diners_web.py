#!/usr/bin/env python3
"""host_diners_web.py — 3 PC + 2 Xinu 哲学者デモ + Web ダッシュボード.

QEMU の UART0 (xsh console) と UART1 (AIPL RPC dispatcher) の双方を
TCP サーバ形式で公開し、本スクリプトが両方の client として接続する.
ブラウザは http://localhost:8080/ にアクセスすると、

  - 左ペイン: UART0 から取り込んだ Xinu console の last N 行
  - 右ペイン上: `LIST` で取得した Xinu 側 actor 一覧 (id / class)
  - 右ペイン下: PC 側 3 哲学者 (P1/P2/P3) の eat 回数 / attempts

を 500ms ポーリングで観測できる.

  Usage:
    # 別ターミナルで QEMU を以下のオプションで起動:
    #   -nographic
    #   -serial tcp:127.0.0.1:5554,server=on,wait=off   # UART0 console
    #   -serial tcp:127.0.0.1:5555,server=on,wait=off   # UART1 RPC
    # その後:
    python3 host_diners_web.py
    open http://localhost:8080/
"""

from __future__ import annotations
import collections
import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


CONSOLE_HOST = os.environ.get("CONSOLE_HOST", "127.0.0.1")
CONSOLE_PORT = int(os.environ.get("CONSOLE_PORT", "5554"))
RPC_HOST     = os.environ.get("RPC_HOST", "127.0.0.1")
RPC_PORT     = int(os.environ.get("RPC_PORT", "5555"))
WEB_HOST     = os.environ.get("WEB_HOST", "127.0.0.1")
WEB_PORT     = int(os.environ.get("WEB_PORT", "8080"))

MEALS_PER_PHILOSOPHER = int(os.environ.get("MEALS", "5"))
ACQUIRE_POLL_MS  = 25
RETRY_BACKOFF_MS = 30
EAT_PAUSE_MS     = 40
JOIN_TIMEOUT_S   = float(os.environ.get("DINERS_TIMEOUT", "300"))
LIST_POLL_S      = 3.0
CONNECT_RETRIES  = 30
CONNECT_RETRY_S  = 0.5
CONSOLE_LINES    = 500

PC_PHILOSOPHERS = [
    # (pid, low_fork, high_fork)
    (1, 0, 4),
    (2, 0, 1),
    (3, 1, 2),
]


# ─────────────────────────────────────────────────────────────────────
# Shared state (thread-safe — single Python GIL + locks where needed)
# ─────────────────────────────────────────────────────────────────────
class DashboardState:
    def __init__(self) -> None:
        self.console: collections.deque[str] = collections.deque(maxlen=CONSOLE_LINES)
        self.actors:  list[dict] = []
        self.philos:  dict[int, dict] = {
            pid: {"meals": 0, "attempts": 0, "status": "idle",
                  "low": low, "high": high}
            for (pid, low, high) in PC_PHILOSOPHERS
        }
        self.connected = {"console": False, "rpc": False}
        self.lock = threading.Lock()
        self.t0 = time.time()

    def push_console(self, line: str) -> None:
        with self.lock:
            self.console.append(
                f"{time.time() - self.t0:7.2f}  {line}".rstrip()
            )

    def update_philo(self, pid: int, **kw) -> None:
        with self.lock:
            self.philos[pid].update(kw)

    def set_actors(self, actors: list[dict]) -> None:
        with self.lock:
            self.actors = actors

    def set_conn(self, kind: str, ok: bool) -> None:
        with self.lock:
            self.connected[kind] = ok

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "console": list(self.console),
                "actors": list(self.actors),
                "philos": {str(k): dict(v) for k, v in self.philos.items()},
                "connected": dict(self.connected),
                "uptime": time.time() - self.t0,
            }


STATE = DashboardState()


# ─────────────────────────────────────────────────────────────────────
# UART0 (console) capture — reads bytes, splits on \n, pushes lines
# ─────────────────────────────────────────────────────────────────────
def console_reader() -> None:
    sock = _connect_with_retry(CONSOLE_HOST, CONSOLE_PORT, "console")
    if sock is None:
        return
    STATE.set_conn("console", True)
    STATE.push_console(f"[host] connected to UART0 {CONSOLE_HOST}:{CONSOLE_PORT}")
    buf = b""
    try:
        sock.settimeout(2.0)
        while True:
            try:
                chunk = sock.recv(1024)
            except (socket.timeout, TimeoutError):
                continue
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, _, buf = buf.partition(b"\n")
                txt = line.decode("utf-8", errors="replace").rstrip("\r")
                # Drop our own LIST/QUERY poll noise that the Xinu RPC
                # dispatcher echoes back via kprintf — otherwise it
                # floods the ring buffer and pushes real Xinu activity
                # (heartbeats / eat markers) out within a few minutes.
                if "[rpc]" in txt:
                    continue
                STATE.push_console(txt)
    except OSError as e:
        STATE.push_console(f"[host] UART0 read error: {e}")
    finally:
        STATE.set_conn("console", False)
        sock.close()


# ─────────────────────────────────────────────────────────────────────
# UART1 (RPC) shared client — every call locks for one send+recv
# ─────────────────────────────────────────────────────────────────────
class SharedRpc:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.sock.settimeout(5.0)
        self.buf  = b""
        self.lock = threading.Lock()
        # Drain boot greeting line if present.
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

    def _drain_extra(self) -> list[str]:
        """Read any additional reply lines that arrived within a short
        idle window.  Used by LIST whose reply spans several lines."""
        extra: list[str] = []
        prev_to = self.sock.gettimeout()
        self.sock.settimeout(0.15)
        try:
            while True:
                while b"\n" not in self.buf:
                    chunk = self.sock.recv(512)
                    if not chunk:
                        return extra
                    self.buf += chunk
                line, _, rest = self.buf.partition(b"\n")
                self.buf = rest
                txt = line.decode("ascii", errors="replace").rstrip("\r")
                if not txt:
                    continue
                extra.append(txt)
        except (socket.timeout, TimeoutError):
            pass
        finally:
            self.sock.settimeout(prev_to)
        return extra

    def call(self, line: str) -> dict[str, str]:
        with self.lock:
            self.sock.sendall((line + "\n").encode("ascii"))
            reply = self._recv_line_locked()
        return _parse_reply(reply)

    def call_multi(self, line: str) -> tuple[dict[str, str], list[str]]:
        with self.lock:
            self.sock.sendall((line + "\n").encode("ascii"))
            reply = self._recv_line_locked()
            extra = self._drain_extra()
        return _parse_reply(reply), extra

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _parse_reply(reply: str) -> dict[str, str]:
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


def _connect_with_retry(host: str, port: int, label: str) -> socket.socket | None:
    last_err = None
    for i in range(CONNECT_RETRIES):
        try:
            return socket.create_connection((host, port), timeout=3.0)
        except (ConnectionRefusedError, OSError) as e:
            last_err = e
            time.sleep(CONNECT_RETRY_S)
    print(f"FAIL connect {label} {host}:{port}: {last_err}", file=sys.stderr)
    return None


# ─────────────────────────────────────────────────────────────────────
# PC philosopher thread (same logic as host_diners.py)
# ─────────────────────────────────────────────────────────────────────
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
    STATE.update_philo(pid, status=f"thinking (low=F{low} high=F{high})")
    meals = 0
    attempts = 0
    while meals < MEALS_PER_PHILOSOPHER:
        attempts += 1
        STATE.update_philo(pid, attempts=attempts, status=f"acquire F{low}")
        if not try_acquire(rpc, low, pid):
            time.sleep(RETRY_BACKOFF_MS / 1000.0)
            continue
        STATE.update_philo(pid, status=f"acquire F{high}")
        if not try_acquire(rpc, high, pid):
            release(rpc, low, pid)
            time.sleep(RETRY_BACKOFF_MS / 1000.0)
            continue
        meals += 1
        STATE.update_philo(pid, meals=meals, status=f"eating meal {meals}")
        STATE.push_console(f"[P{pid}] ate meal={meals} (attempts={attempts})")
        time.sleep(EAT_PAUSE_MS / 1000.0)
        release(rpc, high, pid)
        release(rpc, low, pid)
        STATE.update_philo(pid, status="thinking")
        time.sleep(0.01)
    STATE.update_philo(pid, status=f"done ({attempts} attempts)")
    STATE.push_console(f"[P{pid}] done after {attempts} attempts")


# ─────────────────────────────────────────────────────────────────────
# Actor table poller — periodic LIST + per-actor QUERY for fork holder
# ─────────────────────────────────────────────────────────────────────
def actor_poll_thread(rpc: SharedRpc) -> None:
    while True:
        try:
            head, extra = rpc.call_multi("LIST")
            n_str = head.get("n_actors") or head.get("count") or "0"
            try:
                n = int(n_str)
            except ValueError:
                n = 0
            actors: list[dict] = []
            # extra lines may carry "<id> <class>" or "actor<id>=<class>"
            for ln in extra:
                parts = ln.split()
                if len(parts) >= 2 and parts[0].isdigit():
                    actors.append({"id": int(parts[0]),
                                   "klass": " ".join(parts[1:])})
                elif "=" in ln:
                    k, _, v = ln.partition("=")
                    if k.startswith("actor"):
                        try:
                            aid = int(k[len("actor"):])
                        except ValueError:
                            aid = -1
                        actors.append({"id": aid, "klass": v})
            # If extra was empty, just synthesise n placeholder rows.
            if not actors and n > 0:
                actors = [{"id": i, "klass": "(unknown)"} for i in range(n)]
            # Annotate fork holders if reachable (id 0..4 are forks).
            for a in actors:
                if 0 <= a["id"] <= 4:
                    h = rpc.call(f"QUERY {a['id']} 0")
                    try:
                        a["holder"] = int(h.get("value", "-1"))
                    except ValueError:
                        a["holder"] = -1
            STATE.set_actors(actors)
        except OSError as e:
            STATE.push_console(f"[host] LIST poll error: {e}")
            STATE.set_conn("rpc", False)
            return
        time.sleep(LIST_POLL_S)


# ─────────────────────────────────────────────────────────────────────
# HTTP server — serves /, /api/state
# ─────────────────────────────────────────────────────────────────────
INDEX_HTML = """<!doctype html>
<html lang="ja"><meta charset="utf-8">
<title>Xinu Diners Dashboard</title>
<style>
  body { font: 13px/1.45 ui-monospace, "SF Mono", Menlo, monospace;
         margin: 0; background: #0e1116; color: #d6deeb; }
  header { padding: 8px 16px; background: #181d27; border-bottom: 1px solid #2c3242;
           display: flex; align-items: baseline; gap: 16px; }
  header h1 { margin: 0; font-size: 16px; color: #82aaff; }
  header .conn { font-size: 11px; }
  header .conn span { padding: 1px 6px; border-radius: 3px; margin-right: 6px; }
  .ok  { background: #1a3b1a; color: #b6f0b6; }
  .bad { background: #3b1a1a; color: #f0b6b6; }
  main { display: grid; grid-template-columns: 1.4fr 1fr; gap: 1px;
         background: #2c3242; height: calc(100vh - 42px); }
  section { background: #0e1116; padding: 10px 14px; overflow: auto; }
  section h2 { margin: 0 0 8px; font-size: 12px; color: #c792ea;
               text-transform: uppercase; letter-spacing: 0.05em; }
  #console { font-size: 12px; white-space: pre-wrap; }
  #console .line { color: #d6deeb; }
  #console .line.host { color: #7fbcff; }
  #console .line.eat  { color: #b6f0b6; }
  #console .line.rpc  { color: #4a5568; }     /* dim poll noise */
  #console.hide-rpc .line.rpc { display: none; }
  #toggle-rpc { font-size: 11px; color: #82aaff; cursor: pointer;
                background: #1a2a3a; padding: 1px 8px; border-radius: 3px;
                border: none; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid #2c3242; }
  th { color: #82aaff; font-weight: normal; }
  .pill { display: inline-block; padding: 0 6px; border-radius: 3px;
          background: #1a2a3a; color: #82aaff; font-size: 11px; }
  .meals { color: #f78c6c; }
  .right > div + div { margin-top: 14px; }
</style>
<header>
  <h1>Xinu Diners Dashboard</h1>
  <div class="conn">
    UART0 console <span id="c-console" class="bad">–</span>
    UART1 RPC     <span id="c-rpc"     class="bad">–</span>
    <span id="uptime"></span>
  </div>
</header>
<main>
  <section>
    <h2>Xinu Console (UART0)
      <button id="toggle-rpc" onclick="toggleRpc()">hide [rpc] poll noise</button>
    </h2>
    <div id="console" class="hide-rpc"></div>
  </section>
  <section class="right">
    <div>
      <h2>Xinu Actors (LIST)</h2>
      <table id="actors"><thead><tr>
        <th style="width:3em">id</th><th>class</th>
        <th style="width:5em">holder</th>
      </tr></thead><tbody></tbody></table>
    </div>
    <div>
      <h2>PC Philosophers</h2>
      <table id="philos"><thead><tr>
        <th style="width:3em">pid</th><th>status</th>
        <th style="width:5em" class="meals">meals</th>
        <th style="width:5em">tries</th>
      </tr></thead><tbody></tbody></table>
    </div>
  </section>
</main>
<script>
const $ = (id) => document.getElementById(id);
function setConn(elem, on) {
  elem.textContent = on ? "OK" : "—";
  elem.className   = on ? "ok"  : "bad";
}
function renderConsole(lines) {
  const out = lines.map(L => {
    let cls = "line";
    if (L.includes("[host]")) cls += " host";
    if (L.includes("[rpc]"))  cls += " rpc";
    if (L.match(/ate meal=/))  cls += " eat";
    return `<div class="${cls}">${L.replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]))}</div>`;
  }).join("");
  const el = $("console");
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
  el.innerHTML = out;
  if (atBottom) el.scrollTop = el.scrollHeight;
}
function toggleRpc() {
  const el = $("console");
  el.classList.toggle("hide-rpc");
  const btn = $("toggle-rpc");
  btn.textContent = el.classList.contains("hide-rpc")
    ? "show [rpc] poll noise"
    : "hide [rpc] poll noise";
}
function renderActors(actors) {
  const body = $("actors").querySelector("tbody");
  body.innerHTML = actors.length
    ? actors.map(a => `<tr><td><span class="pill">${a.id}</span></td>
                          <td>${a.klass}</td>
                          <td>${a.holder !== undefined && a.holder >= 0 ? "P"+a.holder : ""}</td></tr>`).join("")
    : `<tr><td colspan="3" style="opacity:0.6">no actors</td></tr>`;
}
function renderPhilos(philos) {
  const rows = Object.keys(philos).sort().map(pid => {
    const p = philos[pid];
    return `<tr><td><span class="pill">P${pid}</span></td>
                <td>${p.status}</td>
                <td class="meals">${p.meals}</td>
                <td>${p.attempts}</td></tr>`;
  }).join("");
  $("philos").querySelector("tbody").innerHTML = rows;
}
async function tick() {
  try {
    const r = await fetch("/api/state");
    const s = await r.json();
    setConn($("c-console"), s.connected.console);
    setConn($("c-rpc"),     s.connected.rpc);
    $("uptime").textContent = "uptime " + s.uptime.toFixed(1) + "s";
    renderConsole(s.console);
    renderActors(s.actors);
    renderPhilos(s.philos);
  } catch (e) { /* keep polling */ }
}
setInterval(tick, 500); tick();
</script>
</html>
"""


class DashHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: N802
        return  # silence default access log

    def do_GET(self):  # noqa: N802
        if self.path == "/" or self.path == "/index.html":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/state":
            body = json.dumps(STATE.snapshot()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404, "not found")


def serve_http() -> None:
    srv = ThreadingHTTPServer((WEB_HOST, WEB_PORT), DashHandler)
    print(f"--- HTTP serving on http://{WEB_HOST}:{WEB_PORT}/ ---")
    srv.serve_forever()


# ─────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────
def main() -> int:
    print(f"--- host_diners_web on {RPC_HOST}:{RPC_PORT} "
          f"({len(PC_PHILOSOPHERS)} PC + 2 Xinu, "
          f"meals={MEALS_PER_PHILOSOPHER} each) ---")

    # 1. Console reader (UART0 → ring buffer)
    threading.Thread(target=console_reader, name="console", daemon=True).start()

    # 2. RPC connection (UART1)
    rpc_sock = _connect_with_retry(RPC_HOST, RPC_PORT, "rpc")
    if rpc_sock is None:
        print("FAIL: could not connect to UART1 RPC port", file=sys.stderr)
        print("Hint: QEMU must expose `-serial tcp:127.0.0.1:5555,server=on,wait=off`",
              file=sys.stderr)
        return 2
    rpc = SharedRpc(rpc_sock)
    STATE.set_conn("rpc", True)
    STATE.push_console(f"[host] connected to UART1 {RPC_HOST}:{RPC_PORT}")

    # Probe with PING so we know the dispatcher is alive.
    pong = rpc.call("PING")
    STATE.push_console(f"[host] PING reply: {pong.get('__raw__','?')}")

    # 3. Actor LIST poller
    threading.Thread(target=actor_poll_thread, args=(rpc,),
                     name="actor-poll", daemon=True).start()

    # 4. HTTP server (daemon — we exit when philosophers finish)
    threading.Thread(target=serve_http, name="http", daemon=True).start()
    print(f"open http://{WEB_HOST}:{WEB_PORT}/ in a browser")

    # 5. PC philosophers
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
            print(f"FAIL {t.name} did not finish within {JOIN_TIMEOUT_S:.0f}s")
            rc = 1

    if rc == 0:
        STATE.push_console("[host] all PC philosophers finished")
        print("--- all PC philosophers finished ---")
    print("(HTTP server staying up — Ctrl-C to exit)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    rpc.close()
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ConnectionRefusedError, OSError) as e:
        print(f"FAIL connect: {e}", file=sys.stderr)
        sys.exit(2)
