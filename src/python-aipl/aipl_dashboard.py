"""Tiny HTTP dashboard for AI-OS counters.

Serves two endpoints from a daemon thread (stdlib only):

    GET /              — auto-refreshing HTML page
    GET /usage.json    — current counters as JSON

Started from aipl_main.py via the --dashboard PORT flag.  The runtime
keeps running normally; the server reads the counters via
abcl_ai.get_usage() / get_remaining().  The page itself polls
/usage.json every second and renders without any external assets.
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import aipl_ai
import aipl_events


# Web IDE: serve files from the python-abcl source tree (where this
# module lives).  Path traversal is blocked by _ide_safe_path.
_IDE_ROOT = os.path.dirname(os.path.abspath(__file__))


def _ide_safe_path(rel: str):
    """Resolve `rel` against _IDE_ROOT, returning the absolute path
    iff it stays inside the workspace and ends in `.abcl`.  None for
    anything fishy (path traversal, wrong extension, empty)."""
    if not rel:
        return None
    rel = rel.replace("\\", "/").lstrip("/")
    if ".." in rel.split("/"):
        return None
    if not rel.endswith(".abcl"):
        return None
    full = os.path.realpath(os.path.join(_IDE_ROOT, rel))
    root = os.path.realpath(_IDE_ROOT) + os.sep
    if not (full == os.path.realpath(_IDE_ROOT) or full.startswith(root)):
        return None
    return full


# Runtime peer list — combines the static env-var seed with anyone
# who's POSTed /api/peer/register on this dashboard.
_dyn_peers_lock = threading.Lock()
_dyn_peers: set = set()

# ── Live program + actor introspection ────────────────────────────────
# aipl_main wires the running interpreter (and its source) in here once
# it is built, so the /actors dashboard can show the current program and
# every live actor's class / state / fields.
_introspect_lock = threading.Lock()
_interp_ref = None
_program_source = ""
_program_path = ""

# Console ring — every AIPL print() line, mirrored here for the browser
# console window (the Mac-side analog of the Xinu HDMI console).
_console_lock = threading.Lock()
_console_lines: list = []
_console_head = 0               # total lines ever appended (monotonic)
_CONSOLE_MAX = 500


def _console_append(line: str) -> None:
    global _console_head
    with _console_lock:
        _console_lines.append(str(line))
        _console_head += 1
        if len(_console_lines) > _CONSOLE_MAX:
            del _console_lines[:len(_console_lines) - _CONSOLE_MAX]


def set_program(interp, source_text: str = "", source_path: str = "") -> None:
    """Register the running interpreter so /actors can introspect it, and
    route AIPL print() output into the browser console window."""
    global _interp_ref, _program_source, _program_path
    with _introspect_lock:
        _interp_ref = interp
        _program_source = source_text or ""
        _program_path = source_path or ""
    try:
        import aipl_interp
        aipl_interp.set_console_sink(_console_append)
    except Exception:
        pass


# ── Program switcher ─────────────────────────────────────────────────
# The dashboard can stop the running program and load another, so the
# user can flip between e.g. the local dining demo and the Mac+Xinu one.
_PROGRAMS: list = []           # [{key,label,path}]
_run_lock = threading.Lock()
_run_thread = None
_program_stopped = False       # True after Stop (中止) until next Start/Switch
_selected_key = ""             # program chosen in the dropdown / initial pick
_PROGRAM_LABELS = {
    "local_diners.abcl": "Dining Philosophers (local, 5)",
    "dine_dynamic.abcl": "Dining Philosophers (3 local + 2 remote / Xinu)",
    "mac_diners.abcl":   "Dining Philosophers (3 Mac + 2 Xinu, static)",
    "ring_demo.abcl":    "Token ring (local, 4)",
}


def configure_programs(initial_path: str) -> None:
    """Build the switchable-program list from the .abcl files next to the
    initial program."""
    global _PROGRAMS, _selected_key
    import os, glob
    d = os.path.dirname(os.path.abspath(initial_path))
    progs = []
    for p in sorted(glob.glob(os.path.join(d, "*.abcl"))):
        base = os.path.basename(p)
        progs.append({"key": base,
                      "label": _PROGRAM_LABELS.get(base, base),
                      "path": p})
    _PROGRAMS = progs
    _selected_key = os.path.basename(initial_path)   # default dropdown pick


def _run_program_thread(path: str) -> None:
    try:
        from aipl_parser import parse_file
        from aipl_interp import Interpreter
        program = parse_file(path)
        interp = Interpreter(program)
        src = ""
        try:
            with open(path) as f:
                src = f.read()
        except Exception:
            pass
        set_program(interp, src, path)
        # run effectively until the program is switched out (shutdown).
        interp.run(idle_ms=120, timeout_s=86400)
    except Exception as e:
        _console_append(f"[program ended: {e}]")


def load_program(key: str) -> bool:
    """Stop the current program's actors and start the selected one."""
    global _run_thread, _program_stopped, _selected_key
    import aipl_runtime
    with _run_lock:
        prog = next((p for p in _PROGRAMS if p["key"] == key), None)
        if prog is None:
            return False
        _selected_key = key
        # resume first so parked actor threads can see the stop message.
        aipl_runtime.resume_all()
        with _introspect_lock:
            cur = _interp_ref
        if cur is not None:
            try:
                cur.scheduler.shutdown()
            except Exception:
                pass
        if _run_thread is not None and _run_thread.is_alive():
            _run_thread.join(timeout=2.0)
        _program_stopped = False
        with _console_lock:                 # fresh console per program load
            _console_lines.clear()
        _console_append(f"=== loaded: {prog['label']} ===")
        t = threading.Thread(target=_run_program_thread, args=(prog["path"],),
                             name=f"abcl-prog-{key}", daemon=True)
        _run_thread = t
        t.start()
        return True


def stop_program() -> None:
    """中止 — halt the current program by shutting down all its actors.
    Start (or Switch) brings a program back."""
    global _program_stopped
    import aipl_runtime
    with _run_lock:
        aipl_runtime.resume_all()        # unstick parked actors so stop lands
        with _introspect_lock:
            cur = _interp_ref
        if cur is not None:
            try:
                cur.scheduler.shutdown()
            except Exception:
                pass
        _program_stopped = True
        _console_append("=== program stopped ===")


def _json_safe(v):
    """Make an actor field value JSON-serialisable for the dashboard."""
    if isinstance(v, bool) or isinstance(v, (int, float, str)) or v is None:
        return v
    nm = getattr(v, "name", None)            # an Actor reference?
    if nm is not None:
        return "<actor %s>" % nm
    return str(v)


def register_peer(hostport: str) -> None:
    h = hostport.strip()
    if not h:
        return
    with _dyn_peers_lock:
        _dyn_peers.add(h)


def _peer_dashboards() -> list:
    seeds = []
    raw = os.environ.get("ABCL_PEER_DASHBOARDS", "").strip()
    if raw:
        seeds = [p.strip() for p in raw.split(",") if p.strip()]
    with _dyn_peers_lock:
        dyn = list(_dyn_peers)
    # Stable order: env seeds first, then alphabetical dynamic.
    return list(dict.fromkeys(seeds + sorted(dyn)))


# Tiny per-key cache so a noisy page-refresh doesn't hammer peers.
_peer_cache_lock = threading.Lock()
_peer_cache: dict = {}        # hostport -> (timestamp, payload_dict | None)
PEER_CACHE_TTL_S = 0.8


def _fetch_peer_usage(hostport: str) -> "dict | None":
    now = time.monotonic()
    with _peer_cache_lock:
        cached = _peer_cache.get(hostport)
        if cached is not None and (now - cached[0]) < PEER_CACHE_TTL_S:
            return cached[1]
    payload = None
    url = f"http://{hostport}/usage.json"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
        payload = None
    with _peer_cache_lock:
        _peer_cache[hostport] = (now, payload)
    return payload


_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>AIPL AI-OS Dashboard</title>
<style>
  body { font-family: ui-monospace, Menlo, Consolas, monospace;
         margin: 2rem; color: #ddd; background: #0e1116; }
  h1   { font-size: 1rem; color: #8af; margin: 0 0 1rem; }
  h2   { font-size: 0.85rem; color: #6a8; margin: 1.25rem 0 0.4rem; }
  table { border-collapse: collapse; }
  td.k { color: #889; padding: 0.2rem 1rem 0.2rem 0; }
  td.v { color: #cde; font-weight: 600; }
  small { color: #667; }
  #events {
    background: #050810; padding: 0.6rem 0.8rem; max-height: 320px;
    overflow-y: auto; border: 1px solid #223;
    font-size: 0.78rem; line-height: 1.4; }
  .ev { color: #aab; }
  .ev .k { color: #fc6; margin-right: 0.5rem; }
  .ev .ai_call { color: #8df; }
  .ev .remote_in { color: #6f8; }
  .ev .remote_out { color: #f9a; }
  #peers, #topo { border-collapse: collapse; }
  #peers th, #peers td, #topo th, #topo td { padding: 0.2rem 0.8rem; text-align: right; }
  #peers th, #topo th { color: #889; font-weight: normal; border-bottom: 1px solid #223; }
  #peers td:first-child, #peers th:first-child,
  #topo td:first-child, #topo th:first-child { text-align: left; color: #aaf; }
  #topo td:nth-child(2), #topo th:nth-child(2),
  #topo td:nth-child(3), #topo th:nth-child(3) { text-align: left; }
  #peers tr.bad td { color: #f88; }
  #peers tr.total td { color: #cde; border-top: 1px solid #223; font-weight: 700; }
</style></head><body>
<h1>AIPL AI-OS Dashboard
  <small style="color:#667"><a style="color:#6af" href="/ide">→ Web IDE</a>
  &nbsp;<a style="color:#6af" href="/chat">→ Chat</a></small></h1>
<table id="t"></table>
<small id="ts"></small>
<h2>Cluster (this node + peers)</h2>
<table id="peers"><thead><tr>
  <th>node</th><th>calls</th><th>in</th><th>out</th><th>total</th><th>cost</th>
</tr></thead><tbody id="peers-body"></tbody></table>
<h2>Observed traffic (this node)</h2>
<svg id="graph" width="600" height="380" style="border:1px solid #223;background:#050810;display:block;margin-bottom:0.5rem"></svg>
<table id="topo"><thead><tr>
  <th>src</th><th>dst</th><th>method</th><th>count</th><th>last</th>
</tr></thead><tbody id="topo-body"></tbody></table>
<h2>Live events</h2>
<div id="events"></div>
<script>
async function refresh() {
  try {
    const r = await fetch('/usage.json', { cache: 'no-store' });
    const u = await r.json();
    const rows = [
      ['calls',           u.calls],
      ['input tokens',    u.input_tokens.toLocaleString()],
      ['output tokens',   u.output_tokens.toLocaleString()],
      ['total tokens',    u.total_tokens.toLocaleString()],
      ['cost (USD)',      '$' + u.cost_usd.toFixed(6)],
      ['budget',          u.budget > 0 ? u.budget.toLocaleString() : '(unlimited)'],
      ['remaining',       u.remaining < 0 ? '(unlimited)' : u.remaining.toLocaleString()],
    ];
    document.getElementById('t').innerHTML = rows
      .map(([k, v]) => `<tr><td class=k>${k}</td><td class=v>${v}</td></tr>`)
      .join('');
    document.getElementById('ts').textContent =
      'last update: ' + new Date().toLocaleTimeString();
  } catch (e) {
    document.getElementById('ts').textContent = 'error: ' + e;
  }
}
refresh();
setInterval(refresh, 1000);

async function refreshPeers() {
  try {
    const r = await fetch('/aggregate.json', { cache: 'no-store' });
    const a = await r.json();
    const tb = document.getElementById('peers-body');
    const fmt = (n) => (typeof n === 'number') ? n.toLocaleString() : '-';
    const lines = [];
    for (const n of a.nodes) {
      const u = n.usage || {};
      const cls = n.ok ? '' : 'bad';
      lines.push(`<tr class="${cls}"><td>${n.name}${n.ok ? '' : ' (offline)'}</td>` +
        `<td>${fmt(u.calls)}</td><td>${fmt(u.input_tokens)}</td>` +
        `<td>${fmt(u.output_tokens)}</td><td>${fmt(u.total_tokens)}</td>` +
        `<td>${u.cost_usd != null ? '$' + u.cost_usd.toFixed(6) : '-'}</td></tr>`);
    }
    const A = a.aggregate;
    lines.push(`<tr class="total"><td>TOTAL</td><td>${fmt(A.calls)}</td>` +
      `<td>${fmt(A.input_tokens)}</td><td>${fmt(A.output_tokens)}</td>` +
      `<td>${fmt(A.total_tokens)}</td><td>$${A.cost_usd.toFixed(6)}</td></tr>`);
    tb.innerHTML = lines.join('');
  } catch (e) { /* ignore — peer offline */ }
}
refreshPeers();
setInterval(refreshPeers, 2000);

async function refreshTopo() {
  try {
    const r = await fetch('/topology.json', { cache: 'no-store' });
    const t = await r.json();
    const tb = document.getElementById('topo-body');
    if (!t.edges.length) {
      tb.innerHTML = '<tr><td colspan="5"><small>no traffic yet</small></td></tr>';
      return;
    }
    const rows = t.edges.slice(0, 30).map(e => {
      const ago = Math.max(0, Math.round(Date.now()/1000 - e.last_ts));
      return `<tr><td>${e.src}</td><td>${e.dst}</td><td>${e.method}</td>` +
        `<td>${e.count}</td><td><small>${ago}s ago</small></td></tr>`;
    });
    tb.innerHTML = rows.join('');
  } catch (_) { /* ignore */ }
}
refreshTopo();
setInterval(refreshTopo, 2000);

async function refreshGraph() {
  let t;
  try {
    t = await (await fetch('/topology.json', { cache: 'no-store' })).json();
  } catch (_) { return; }
  const svg = document.getElementById('graph');
  const W = 600, H = 380, cx = W/2, cy = H/2, R = Math.min(W,H)/2 - 50;
  if (!t.edges.length) {
    svg.innerHTML = '<text x="20" y="30" fill="#667" font-size="12">no traffic yet</text>';
    return;
  }
  const nodes = Array.from(new Set(t.edges.flatMap(e => [e.src, e.dst])));
  const pos = {};
  nodes.forEach((n, i) => {
    const a = 2 * Math.PI * i / nodes.length - Math.PI/2;
    pos[n] = { x: cx + R*Math.cos(a), y: cy + R*Math.sin(a) };
  });
  const maxCount = Math.max(1, ...t.edges.map(e => e.count));
  let svgInner =
    '<defs><marker id="ah" viewBox="0 0 10 10" refX="14" refY="5" ' +
    'markerWidth="7" markerHeight="7" orient="auto">' +
    '<path d="M0,0 L10,5 L0,10 z" fill="#8a8"/></marker></defs>';
  // edges first so circles draw on top
  for (const e of t.edges) {
    const s = pos[e.src], d = pos[e.dst];
    if (!s || !d) continue;
    const w = 1 + 5 * (e.count / maxCount);
    svgInner += `<line x1="${s.x}" y1="${s.y}" x2="${d.x}" y2="${d.y}" ` +
                `stroke="#688" stroke-width="${w.toFixed(1)}" ` +
                `opacity="0.7" marker-end="url(#ah)"/>`;
  }
  for (const n of nodes) {
    const p = pos[n];
    svgInner += `<circle cx="${p.x}" cy="${p.y}" r="22" fill="#162a3e" stroke="#6f8" stroke-width="2"/>`;
    svgInner += `<text x="${p.x}" y="${p.y+4}" text-anchor="middle" font-size="11" fill="#cde">${n.slice(0,16)}</text>`;
  }
  svg.innerHTML = svgInner;
}
refreshGraph();
setInterval(refreshGraph, 2000);

const events = document.getElementById('events');
function appendEvent(evt) {
  const t = new Date(evt.ts * 1000).toLocaleTimeString();
  const detail = Object.entries(evt)
    .filter(([k]) => k !== 'ts' && k !== 'kind')
    .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join(' ');
  const div = document.createElement('div');
  div.className = 'ev';
  div.innerHTML = `<span class="k ${evt.kind}">${t}  ${evt.kind}</span> ${detail}`;
  events.appendChild(div);
  while (events.childNodes.length > 200) events.removeChild(events.firstChild);
  events.scrollTop = events.scrollHeight;
}
const es = new EventSource('/events');
es.onmessage = (m) => { try { appendEvent(JSON.parse(m.data)); } catch (_) {} };
es.onerror   = () => { /* auto-reconnect */ };
</script></body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Silence the default access log so it doesn't crowd actor output.
        return

    def _send_bytes(self, code: int, ctype: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/usage.json"):
            self._serve_json()
        elif self.path.startswith("/aggregate.json"):
            self._serve_aggregate()
        elif self.path.startswith("/topology.json"):
            self._serve_topology()
        elif self.path.startswith("/events"):
            self._serve_events()
        elif self.path.startswith("/healthz"):
            self._serve_healthz()
        elif self.path.startswith("/api/files"):
            self._serve_ide_files()
        elif self.path.startswith("/api/file?"):
            self._serve_ide_file_get()
        elif self.path == "/ide" or self.path.startswith("/ide?"):
            self._serve_ide_html()
        elif self.path == "/chat" or self.path.startswith("/chat?"):
            self._serve_chat_html()
        elif self.path == "/actors" or self.path.startswith("/actors?"):
            self._serve_actors_html()
        elif self.path.startswith("/api/actors"):
            self._serve_actors_json()
        elif self.path.startswith("/api/programs"):
            self._serve_programs_json()
        elif self.path.startswith("/api/program"):
            self._serve_program_json()
        elif self.path.startswith("/api/console"):
            self._serve_console_json()
        elif self.path == "/" or self.path.startswith("/?"):
            self._serve_html()
        else:
            self.send_error(404, "Not Found")

    def _serve_chat_html(self):
        body = _CHAT_HTML.encode("utf-8")
        self._send_bytes(200, "text/html; charset=utf-8", body)

    # ---- IDE: list / read / write / run ----

    def _serve_ide_files(self):
        """List every .abcl file under the workspace, grouped by
        directory."""
        out = []
        for dirpath, dirnames, filenames in os.walk(_IDE_ROOT):
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(("_", ".", "__"))]
            for fn in sorted(filenames):
                if not fn.endswith(".abcl"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, _IDE_ROOT)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = 0
                out.append({"path": rel, "size": size})
        body = json.dumps({"files": out}).encode("utf-8")
        self._send_bytes(200, "application/json", body)

    def _serve_ide_file_get(self):
        from urllib.parse import parse_qs, urlsplit
        q = parse_qs(urlsplit(self.path).query)
        rel = (q.get("path") or [""])[0]
        full = _ide_safe_path(rel)
        if full is None or not os.path.isfile(full):
            return self.send_error(404, f"file not found: {rel}")
        try:
            content = open(full).read()
        except OSError as e:
            return self.send_error(500, f"read error: {e}")
        body = json.dumps({"path": rel, "content": content}).encode("utf-8")
        self._send_bytes(200, "application/json", body)

    def do_POST(self):
        if self.path.startswith("/api/peer/register"):
            self._handle_register()
        elif self.path.startswith("/api/file/save"):
            self._handle_ide_save()
        elif self.path.startswith("/api/run"):
            self._handle_ide_run()
        elif self.path.startswith("/api/chat/send"):
            self._handle_chat_send()
        elif self.path.startswith("/api/control"):
            self._handle_control()
        elif self.path.startswith("/api/load"):
            self._handle_load()
        else:
            self.send_error(404, "Not Found")

    def _serve_programs_json(self):
        cur_key = _selected_key
        if not cur_key:
            with _introspect_lock:
                cur = _program_path
            cur_key = os.path.basename(cur) if cur else ""
        progs = [{"key": p["key"], "label": p["label"]} for p in _PROGRAMS]
        self._send_bytes(200, "application/json",
                         json.dumps({"programs": progs, "current": cur_key}).encode("utf-8"))

    def _handle_load(self):
        data = self._read_json_body() or {}
        key = str(data.get("program", ""))
        ok = False
        try:
            ok = load_program(key)
        except Exception:
            ok = False
        self._send_bytes(200, "application/json",
                         json.dumps({"ok": ok, "program": key}).encode("utf-8"))

    def _handle_control(self):
        """Start / pause / resume the actor scheduler from the dashboard.
        Body: {"action": "start" | "pause" | "resume"}."""
        data = self._read_json_body() or {}
        action = str(data.get("action", "")).lower()
        try:
            import aipl_runtime
            if action in ("pause", "suspend"):
                aipl_runtime.pause_all()
            elif action in ("resume", "run"):
                aipl_runtime.resume_all()
            elif action in ("start", "restart"):
                # run the program selected in the dropdown (or the current one)
                key = str(data.get("program", "")) or _selected_key
                if not key:
                    with _introspect_lock:
                        cp = _program_path
                    key = os.path.basename(cp) if cp else ""
                if key:
                    load_program(key)
            elif action in ("stop", "abort"):
                stop_program()
            paused = aipl_runtime.is_paused()
        except Exception:
            paused = False
        with _introspect_lock:
            started = _interp_ref is not None
        self._send_bytes(200, "application/json",
                         json.dumps({"paused": paused, "stopped": _program_stopped,
                                     "started": started}).encode("utf-8"))

    def _handle_chat_send(self):
        data = self._read_json_body()
        if data is None:
            return
        messages = data.get("messages")
        if not isinstance(messages, list):
            return self.send_error(400, "messages must be an array")
        system = data.get("system")
        if system is not None and not isinstance(system, str):
            return self.send_error(400, "system must be a string")
        model = data.get("model")
        try:
            from aipl_ai import chat_ai, get_usage
            reply = chat_ai(messages, system=system, model=model or None)
            body = json.dumps({
                "ok": True, "reply": reply, "usage": get_usage(),
            }).encode("utf-8")
            self._send_bytes(200, "application/json", body)
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode("utf-8")
            self._send_bytes(500, "application/json", body)

    def _read_json_body(self) -> "dict | None":
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        body = self.rfile.read(length).decode("utf-8") if length > 0 else ""
        try:
            data = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError):
            self.send_error(400, "bad json")
            return None
        if not isinstance(data, dict):
            self.send_error(400, "json body must be an object")
            return None
        return data

    def _handle_ide_save(self):
        data = self._read_json_body()
        if data is None:
            return
        rel = str(data.get("path", ""))
        content = str(data.get("content", ""))
        full = _ide_safe_path(rel)
        if full is None:
            return self.send_error(400, "invalid path")
        try:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(content)
        except OSError as e:
            return self.send_error(500, f"write error: {e}")
        body = json.dumps({"ok": True, "path": rel,
                           "size": len(content)}).encode("utf-8")
        self._send_bytes(200, "application/json", body)

    def _handle_ide_run(self):
        """Run a .abcl program through abcl_main.py and return the
        captured stdout+stderr.  Bounded to ABCL_IDE_RUN_TIMEOUT
        seconds (default 8) so a runaway sample can't tie up the
        dashboard."""
        data = self._read_json_body()
        if data is None:
            return
        rel = str(data.get("path", ""))
        full = _ide_safe_path(rel)
        if full is None or not os.path.isfile(full):
            return self.send_error(404, f"file not found: {rel}")
        try:
            timeout = float(os.environ.get("ABCL_IDE_RUN_TIMEOUT", "8"))
        except ValueError:
            timeout = 8.0
        cmd = [sys.executable, os.path.join(_IDE_ROOT, "abcl_main.py"),
               "--timeout", str(timeout), full]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout + 4, cwd=_IDE_ROOT)
            out = (r.stdout or "") + (r.stderr or "")
            ok = (r.returncode == 0)
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or "") + (e.stderr or "") + "\n[ide] run timed out"
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            ok = False
        body = json.dumps({"ok": ok, "output": out}).encode("utf-8")
        self._send_bytes(200, "application/json", body)

    def _serve_healthz(self):
        body = json.dumps({
            "status": "ok",
            "subscribers": abcl_events.subscriber_count(),
        }).encode("utf-8")
        self._send_bytes(200, "application/json", body)

    def _serve_topology(self):
        edges = abcl_events.topology_snapshot()
        edges.sort(key=lambda e: -e["count"])
        body = json.dumps({"edges": edges}).encode("utf-8")
        self._send_bytes(200, "application/json", body)

    # (do_POST is defined earlier with the IDE routes — peer
    #  registration is handled there too.)

    def _handle_register(self):
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        body = self.rfile.read(length).decode("utf-8") if length > 0 else ""
        try:
            payload = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError) as e:
            return self.send_error(400, f"bad json: {e}")
        host = str(payload.get("host", "")).strip()
        port = payload.get("port")
        if not host or not isinstance(port, int):
            return self.send_error(400, "host (str) and port (int) required")
        register_peer(f"{host}:{port}")
        body_resp = json.dumps({"ok": True, "peers": _peer_dashboards()}).encode("utf-8")
        self._send_bytes(200, "application/json", body_resp)

    def _serve_aggregate(self):
        peers = _peer_dashboards()
        nodes = []
        # Self first
        local = abcl_ai.get_usage()
        try:
            local_budget = abcl_ai._get_budget()  # type: ignore[attr-defined]
        except Exception:
            local_budget = 0
        local["budget"]    = local_budget
        local["remaining"] = abcl_ai.get_remaining()
        nodes.append({"name": "self", "ok": True, "usage": local})
        # Peers
        for hp in peers:
            payload = _fetch_peer_usage(hp)
            nodes.append({"name": hp, "ok": payload is not None,
                          "usage": payload or {}})
        # Aggregate the truthy ones
        keys = ("calls", "input_tokens", "output_tokens", "total_tokens")
        agg = {k: 0 for k in keys}
        agg["cost_usd"] = 0.0
        for n in nodes:
            u = n.get("usage", {}) or {}
            for k in keys:
                v = u.get(k, 0)
                if isinstance(v, int):
                    agg[k] += v
            c = u.get("cost_usd", 0)
            if isinstance(c, (int, float)):
                agg["cost_usd"] += float(c)
        body = json.dumps({"nodes": nodes, "aggregate": agg}).encode("utf-8")
        self._send_bytes(200, "application/json", body)

    def _serve_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = abcl_events.subscribe()
        try:
            while True:
                try:
                    evt = q.get(timeout=15)
                except queue.Empty:
                    # Heartbeat so proxies don't drop the connection.
                    try:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        return
                    continue
                try:
                    body = ("data: " + json.dumps(evt) + "\n\n").encode("utf-8")
                    self.wfile.write(body)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return
        finally:
            abcl_events.unsubscribe(q)

    def _serve_html(self):
        body = _HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ── Actor / program introspection (the JS-I-style live view) ──────
    def _serve_actors_html(self):
        self._send_bytes(200, "text/html; charset=utf-8",
                         _ACTORS_HTML.encode("utf-8"))

    def _serve_actors_json(self):
        with _introspect_lock:
            interp = _interp_ref
        actors = []
        try:
            actors = interp.scheduler.all() if interp is not None else []
        except Exception:
            actors = []
        try:
            import aipl_runtime
            _paused = aipl_runtime.is_paused()
        except Exception:
            _paused = False
        out = {"paused": _paused, "stopped": _program_stopped,
               "started": interp is not None, "actors": []}
        for a in actors:
            try:
                cls = getattr(getattr(a, "cls", None), "name", "?")
                fields = {}
                for k, v in (getattr(a, "fields", {}) or {}).items():
                    fields[str(k)] = _json_safe(v)
                try:
                    mbox = a.mailbox._q.qsize()
                except Exception:
                    mbox = 0
                stopped = bool(getattr(a, "_stopped", False))
                state = "stopped" if stopped else ("busy" if mbox > 0 else "idle")
                th = getattr(a, "_thread", None)
                tid = getattr(th, "ident", None) if th is not None else None
                alive = bool(th.is_alive()) if th is not None else False
                out["actors"].append({
                    "name":    str(getattr(a, "name", "?")),
                    "class":   str(cls),
                    "state":   state,
                    "mailbox": mbox,
                    "thread":  tid,
                    "alive":   alive,
                    "fields":  fields,
                })
            except Exception:
                continue
        self._send_bytes(200, "application/json",
                         json.dumps(out).encode("utf-8"))

    def _serve_console_json(self):
        """Return console lines newer than ?since=<head>.  The client tracks
        the returned head and only appends the new tail each poll."""
        since = 0
        q = self.path.split("?", 1)
        if len(q) == 2:
            for kv in q[1].split("&"):
                if kv.startswith("since="):
                    try:
                        since = int(kv[6:])
                    except ValueError:
                        since = 0
        with _console_lock:
            head = _console_head
            buffered = len(_console_lines)
            first = head - buffered          # head index of _console_lines[0]
            if since < first:
                since = first                # client fell behind the ring
            tail = _console_lines[since - first:] if since <= head else []
            lines = list(tail)
        self._send_bytes(200, "application/json",
                         json.dumps({"head": head, "lines": lines}).encode("utf-8"))

    def _serve_program_json(self):
        with _introspect_lock:
            interp = _interp_ref
            src    = _program_source
            path   = _program_path
        classes = []
        try:
            prog = interp.program if interp is not None else None
            for d in (getattr(prog, "decls", []) or []):
                if d.__class__.__name__ == "ClassDecl":
                    classes.append({
                        "name":    getattr(d, "name", "?"),
                        "methods": [getattr(m, "name", "?")
                                    for m in (getattr(d, "methods", []) or [])],
                    })
        except Exception:
            pass
        body = {"path": path, "source": src, "classes": classes}
        self._send_bytes(200, "application/json",
                         json.dumps(body).encode("utf-8"))

    def _serve_ide_html(self):
        body = _IDE_HTML.encode("utf-8")
        self._send_bytes(200, "text/html; charset=utf-8", body)

    def _serve_json(self):
        usage = abcl_ai.get_usage()
        # Augment with budget info — useful for the page header.
        budget = 0
        try:
            budget = abcl_ai._get_budget()  # type: ignore[attr-defined]
        except Exception:
            pass
        usage["budget"] = budget
        usage["remaining"] = abcl_ai.get_remaining()
        body = json.dumps(usage).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


_IDE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>AIPL Web IDE</title>
<style>
  html, body { margin: 0; padding: 0; height: 100%;
               font-family: ui-monospace, Menlo, Consolas, monospace;
               color: #ddd; background: #0e1116; }
  header { padding: 0.6rem 1rem; background: #11161e; border-bottom: 1px solid #223;
           display: flex; align-items: center; gap: 1rem; }
  header h1 { font-size: 0.95rem; color: #8af; margin: 0; }
  header a { color: #6af; text-decoration: none; font-size: 0.85rem; }
  #wrap { display: grid; grid-template-columns: 220px 1fr; height: calc(100% - 41px); }
  #files { background: #11161e; border-right: 1px solid #223; padding: 0.5rem 0;
           overflow-y: auto; font-size: 0.78rem; }
  .group  { color: #6a8; padding: 0.4rem 0.7rem 0.2rem; }
  .file   { padding: 0.18rem 0.7rem; cursor: pointer; color: #cde; }
  .file:hover { background: #1a2332; }
  .file.active { background: #1f2c3e; color: #fff; }
  #right { display: grid; grid-template-rows: 1fr 36px 38% ; min-height: 0; }
  #editor { width: 100%; height: 100%; box-sizing: border-box;
            background: #050810; color: #cde; border: 0; outline: 0;
            padding: 0.6rem 0.8rem; resize: none; font: 0.82rem ui-monospace, Menlo, monospace;
            tab-size: 2; }
  #bar { background: #11161e; border-top: 1px solid #223; border-bottom: 1px solid #223;
         display: flex; align-items: center; gap: 0.5rem; padding: 0 0.7rem;
         font-size: 0.78rem; color: #889; }
  #bar button { background: #1c2a3e; color: #cde; border: 1px solid #335;
                padding: 0.18rem 0.7rem; cursor: pointer;
                font: inherit; }
  #bar button:hover { background: #28395a; }
  #bar .right { margin-left: auto; }
  #out { background: #050810; color: #aab; padding: 0.6rem 0.8rem;
         font-size: 0.78rem; white-space: pre-wrap; overflow-y: auto;
         border-top: 1px solid #223; }
  .err { color: #f88; }
  .ok  { color: #6f8; }
</style></head>
<body>
<header>
  <h1>AIPL Web IDE</h1>
  <a href="/">← dashboard</a>
  <span id="path" style="color:#667;font-size:0.78rem"></span>
</header>
<div id="wrap">
  <nav id="files"><div style="color:#667;padding:0.5rem 0.7rem">loading…</div></nav>
  <section id="right">
    <textarea id="editor" spellcheck="false" placeholder="Pick a file on the left or type a fresh program here."></textarea>
    <div id="bar">
      <button id="save">Save</button>
      <button id="run">Run</button>
      <button id="fmt">Format</button>
      <span id="status" class="right"></span>
    </div>
    <pre id="out">(output will appear here)</pre>
  </section>
</div>
<script>
let currentPath = null;
const E = (id) => document.getElementById(id);

async function loadList() {
  const r = await fetch('/api/files', { cache: 'no-store' });
  const d = await r.json();
  const groups = {};
  for (const f of d.files) {
    const dir = f.path.includes('/') ? f.path.split('/').slice(0, -1).join('/') : '(root)';
    (groups[dir] = groups[dir] || []).push(f);
  }
  const html = Object.keys(groups).sort().map(dir => {
    const files = groups[dir]
      .map(f => `<div class="file" data-p="${f.path}">${f.path.split('/').pop()}</div>`)
      .join('');
    return `<div class="group">${dir}</div>${files}`;
  }).join('');
  E('files').innerHTML = html;
  for (const el of document.querySelectorAll('.file')) {
    el.addEventListener('click', () => openFile(el.dataset.p));
  }
}

async function openFile(p) {
  const r = await fetch('/api/file?path=' + encodeURIComponent(p), { cache: 'no-store' });
  if (!r.ok) { setStatus('open failed: ' + r.status, 'err'); return; }
  const d = await r.json();
  currentPath = p;
  E('editor').value = d.content;
  E('path').textContent = p;
  for (const el of document.querySelectorAll('.file')) el.classList.toggle('active', el.dataset.p === p);
  setStatus('opened (' + d.content.length + ' bytes)', 'ok');
}

function setStatus(msg, cls) {
  const s = E('status');
  s.textContent = msg;
  s.className = 'right ' + (cls || '');
  if (cls) setTimeout(() => { if (s.textContent === msg) s.textContent = ''; }, 3500);
}

async function save() {
  if (!currentPath) { setStatus('no file open', 'err'); return; }
  const r = await fetch('/api/file/save', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ path: currentPath, content: E('editor').value }),
  });
  if (r.ok) setStatus('saved', 'ok'); else setStatus('save failed: ' + r.status, 'err');
}

async function run() {
  if (!currentPath) { setStatus('no file open', 'err'); return; }
  await save();
  E('out').textContent = 'running…';
  const r = await fetch('/api/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ path: currentPath }),
  });
  const d = await r.json();
  E('out').textContent = d.output || '(no output)';
  setStatus(d.ok ? 'done' : 'failed', d.ok ? 'ok' : 'err');
}

async function fmt() {
  // Lightweight client-side reformat — just normalises blank lines.
  // The real formatter is abcl_fmt.py; expose later via /api/fmt.
  const t = E('editor').value;
  E('editor').value = t.replace(/\\n{3,}/g, '\\n\\n').replace(/[ \\t]+$/gm, '');
  setStatus('whitespace tidied (full fmt via abcl_fmt CLI)', 'ok');
}

E('save').addEventListener('click', save);
E('run').addEventListener('click', run);
E('fmt').addEventListener('click', fmt);

// Cmd-S / Ctrl-S to save, Cmd-Enter to run.
document.addEventListener('keydown', (e) => {
  const mod = e.metaKey || e.ctrlKey;
  if (mod && e.key === 's') { e.preventDefault(); save(); }
  if (mod && e.key === 'Enter') { e.preventDefault(); run(); }
});

loadList();
</script>
</body></html>
"""


_CHAT_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>AIPL Chat</title>
<style>
  html, body { margin: 0; padding: 0; height: 100%;
               font-family: ui-monospace, Menlo, Consolas, monospace;
               color: #ddd; background: #0e1116; }
  header { padding: 0.6rem 1rem; background: #11161e;
           border-bottom: 1px solid #223;
           display: flex; align-items: center; gap: 1rem; }
  header h1 { font-size: 0.95rem; color: #8af; margin: 0; }
  header a  { color: #6af; text-decoration: none; font-size: 0.85rem; }
  #wrap { display: grid; grid-template-rows: auto 1fr auto;
          height: calc(100% - 41px); }
  #sysbar { padding: 0.4rem 0.8rem; border-bottom: 1px solid #223;
            background: #11161e; font-size: 0.78rem; color: #889;
            display: flex; gap: 0.5rem; align-items: center; }
  #sysbar input { flex: 1; background: #050810; color: #cde;
                  border: 1px solid #223; padding: 0.25rem 0.5rem;
                  font: inherit; }
  #sysbar select { background: #050810; color: #cde;
                   border: 1px solid #223; padding: 0.2rem; font: inherit; }
  #log { padding: 0.6rem 0.8rem; overflow-y: auto;
         display: flex; flex-direction: column; gap: 0.6rem;
         font-size: 0.85rem; }
  .msg { padding: 0.55rem 0.8rem; border-radius: 0.4rem;
         max-width: 70ch; white-space: pre-wrap; line-height: 1.4; }
  .user { align-self: flex-end; background: #1c2a3e; color: #cde;
          border: 1px solid #335; }
  .ass  { align-self: flex-start; background: #122418; color: #cfe;
          border: 1px solid #284; }
  .err  { align-self: flex-start; background: #2a1212; color: #fcc;
          border: 1px solid #844; }
  .role { font-size: 0.7rem; color: #889; margin-bottom: 0.15rem; }
  #compose { background: #11161e; border-top: 1px solid #223;
             padding: 0.6rem 0.8rem; display: flex; gap: 0.5rem;
             align-items: flex-end; }
  #compose textarea { flex: 1; background: #050810; color: #cde;
                      border: 1px solid #223; outline: 0;
                      padding: 0.5rem; resize: none; min-height: 2.4rem;
                      max-height: 10rem; font: 0.85rem ui-monospace, Menlo, monospace; }
  #compose button { background: #1c2a3e; color: #cde;
                    border: 1px solid #335; padding: 0.4rem 0.9rem;
                    cursor: pointer; font: inherit; }
  #compose button:disabled { opacity: 0.5; cursor: progress; }
  #stat { font-size: 0.72rem; color: #667; padding: 0 0.8rem 0.4rem; }
</style></head>
<body>
<header>
  <h1>AIPL Chat</h1>
  <a href="/">← dashboard</a>
  <a href="/ide">→ Web IDE</a>
</header>
<div id="wrap">
  <div id="sysbar">
    system:
    <input id="sys" placeholder="(optional system prompt — e.g. &quot;Reply in Japanese, briefly&quot;)"/>
    model:
    <input id="model" placeholder="(blank → provider default)" style="max-width:18rem"/>
    <button id="reset">Reset</button>
  </div>
  <main id="log"></main>
  <div id="compose">
    <textarea id="msg" placeholder="Type a message — Enter to send, Shift-Enter for newline"></textarea>
    <button id="send">Send</button>
  </div>
</div>
<div id="stat"></div>
<script>
const log = document.getElementById('log');
const stat = document.getElementById('stat');
const sysIn = document.getElementById('sys');
const modelIn = document.getElementById('model');
const msgEl = document.getElementById('msg');
const sendBtn = document.getElementById('send');

let history = [];

function bubble(role, text, klass) {
  const div = document.createElement('div');
  div.className = 'msg ' + klass;
  const r = document.createElement('div');
  r.className = 'role';
  r.textContent = role;
  const t = document.createElement('div');
  t.textContent = text;
  div.appendChild(r);
  div.appendChild(t);
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return t;
}

async function send() {
  const text = msgEl.value.trim();
  if (!text) return;
  msgEl.value = '';
  bubble('you', text, 'user');
  history.push({ role: 'user', content: text });
  sendBtn.disabled = true;
  const placeholder = bubble('assistant…', '', 'ass');
  try {
    const r = await fetch('/api/chat/send', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        messages: history,
        system: sysIn.value || null,
        model: modelIn.value || null,
      }),
    });
    const d = await r.json();
    if (d.ok) {
      placeholder.textContent = d.reply;
      history.push({ role: 'assistant', content: d.reply });
      const u = d.usage || {};
      stat.textContent = `calls=${u.calls||0} in=${u.input_tokens||0} out=${u.output_tokens||0} cost=$${(u.cost_usd||0).toFixed(6)}`;
    } else {
      placeholder.textContent = '[error] ' + (d.error || 'unknown');
      placeholder.parentElement.className = 'msg err';
      // Drop the failed user turn so retry doesn't double up
      history.pop();
    }
  } catch (e) {
    placeholder.textContent = '[error] ' + e;
    placeholder.parentElement.className = 'msg err';
    history.pop();
  } finally {
    sendBtn.disabled = false;
    msgEl.focus();
  }
}

sendBtn.addEventListener('click', send);
msgEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

document.getElementById('reset').addEventListener('click', () => {
  history = [];
  log.innerHTML = '';
  stat.textContent = '';
});

msgEl.focus();
</script>
</body></html>
"""


_ACTORS_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Py-I — AIPL actors</title>
<style>
 body{font-family:ui-monospace,Menlo,Consolas,monospace;background:#0b0f14;color:#d8dee9;margin:0;padding:16px}
 h1{color:#88c0d0;font-size:18px;margin:0 0 6px} h2{color:#a3be8c;font-size:14px;margin:18px 0 6px}
 .meta{color:#7a8a99;font-size:12px;margin-bottom:8px}
 table{border-collapse:collapse;width:100%;font-size:13px}
 th,td{border:1px solid #2a3340;padding:4px 8px;text-align:left;vertical-align:top}
 th{background:#1a2430;color:#88c0d0;position:sticky;top:0}
 td.busy{color:#ebcb8b;font-weight:bold} td.idle{color:#7a8a99} td.stopped{color:#bf616a}
 .fields{color:#8fbcbb;white-space:pre-wrap}
 pre{background:#11161d;border:1px solid #2a3340;padding:10px;overflow:auto;max-height:340px;font-size:12px;color:#cdd6e0}
 .cls{color:#b48ead}
 .bar{margin:8px 0 4px} button{font-family:inherit;font-size:13px;padding:6px 14px;margin-right:8px;
   border:1px solid #3b4757;border-radius:5px;background:#1a2430;color:#d8dee9;cursor:pointer}
 button:hover{background:#243042} #b_start{border-color:#a3be8c} #b_pause{border-color:#ebcb8b}
 #b_resume{border-color:#88c0d0} #b_stop{border-color:#bf616a}
 #runstate{font-weight:bold;margin-left:8px} .running{color:#a3be8c} .paused{color:#ebcb8b}
 .stopped{color:#bf616a} .notstarted{color:#7a8a99}
</style></head><body>
<h1>Py-I &mdash; AIPL interpreter (live)</h1>
<div class="bar">
 <label for="progsel">Program:</label>
 <select id="progsel" style="font-family:inherit;font-size:13px;padding:5px;background:#11161d;color:#d8dee9;border:1px solid #3b4757;border-radius:5px;min-width:340px"></select>
 <button id="b_switch" onclick="switchProgram()" style="border-color:#b48ead">Switch / Load</button>
</div>
<div class="bar">
 <button id="b_start" onclick="ctl('start')">&#9654; Start</button>
 <button id="b_pause" onclick="ctl('pause')">&#10073;&#10073; Suspend</button>
 <button id="b_resume" onclick="ctl('resume')">&#8635; Resume</button>
 <button id="b_stop" onclick="ctl('stop')">&#9632; End</button>
 <span id="runstate" class="notstarted">not started</span>
</div>
<div class="meta">program: <span id="path">(loading)</span> &nbsp;|&nbsp; actors: <b id="count">0</b>
 &nbsp;|&nbsp; classes: <span id="classes" class="cls"></span> &nbsp;|&nbsp; updated <span id="ts"></span></div>
<h2>Running actors</h2>
<table><thead><tr><th>name</th><th>class</th><th>state</th><th>mailbox</th><th>thread</th><th>fields (state)</th></tr></thead>
<tbody id="abody"><tr><td colspan="5">(loading)</td></tr></tbody></table>
<h2>Console &mdash; print() output</h2>
<pre id="console" style="max-height:300px;color:#40ff80">(waiting for output...)</pre>
<h2>Current program</h2>
<pre id="src">(loading)</pre>
<script>
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
async function loadProg(){
 try{ const p=await (await fetch('/api/program')).json();
  document.getElementById('path').textContent=p.path||'(inline)';
  document.getElementById('classes').textContent=(p.classes||[]).map(c=>c.name).join(', ')||'(none)';
  document.getElementById('src').textContent=p.source||'(source unavailable)';
 }catch(e){}
}
function setState(paused,stopped,started){
 const el=document.getElementById('runstate');
 let s,cls;
 if(started===false){s='not started';cls='notstarted';}
 else if(stopped){s='ended';cls='stopped';}
 else if(paused){s='paused';cls='paused';}
 else {s='running';cls='running';}
 el.textContent=s; el.className=cls;
}
async function ctl(action){
 const body={action};
 if(action==='start'){ const sel=document.getElementById('progsel');
   if(sel&&sel.value) body.program=sel.value;
   conSince=0; document.getElementById('console').textContent=''; }
 try{ const r=await fetch('/api/control',{method:'POST',
       headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json(); setState(d.paused,d.stopped,d.started);
  if(action==='start'){ setTimeout(tick,400); setTimeout(loadProg,500); }
 }catch(e){}
}
async function tick(){
 try{ const a=await (await fetch('/api/actors')).json();
  document.getElementById('count').textContent=a.actors.length;
  document.getElementById('ts').textContent=new Date().toLocaleTimeString();
  setState(a.paused,a.stopped,a.started);
  const rows=a.actors.map(x=>{
   const f=Object.entries(x.fields||{}).map(([k,v])=>k+'='+esc(JSON.stringify(v))).join('   ');
   const th=(x.alive!==false&&x.thread!=null)?('#'+x.thread):'(dead)';
   return '<tr><td>'+esc(x.name)+'</td><td class="cls">'+esc(x['class'])+'</td>'+
          '<td class="'+x.state+'">'+x.state+'</td><td>'+x.mailbox+'</td>'+
          '<td>'+esc(th)+'</td>'+
          '<td class="fields">'+f+'</td></tr>';
  }).join('');
  document.getElementById('abody').innerHTML=rows||'<tr><td colspan="5">(no actors)</td></tr>';
 }catch(e){}
}
let conSince=0;
async function conTick(){
 try{ const c=await (await fetch('/api/console?since='+conSince)).json();
  conSince=c.head;
  if(c.lines && c.lines.length){
   const el=document.getElementById('console');
   if(el.textContent==='(waiting for output...)') el.textContent='';
   const atBottom=el.scrollHeight-el.scrollTop-el.clientHeight<40;
   el.textContent += c.lines.join('\\n')+'\\n';
   if(el.textContent.length>40000) el.textContent=el.textContent.slice(-40000);
   if(atBottom) el.scrollTop=el.scrollHeight;
  }
 }catch(e){}
}
async function loadPrograms(){
 try{ const p=await (await fetch('/api/programs')).json();
  const sel=document.getElementById('progsel');
  if(document.activeElement===sel) return;        // don't fight the user
  sel.innerHTML=(p.programs||[]).map(x=>
    '<option value="'+esc(x.key)+'"'+(x.key===p.current?' selected':'')+'>'+esc(x.label)+'</option>').join('');
 }catch(e){}
}
async function switchProgram(){
 const sel=document.getElementById('progsel');
 const key=sel.value; if(!key) return;
 const b=document.getElementById('b_switch'); b.disabled=true; b.textContent='Loading...';
 try{ await fetch('/api/load',{method:'POST',headers:{'Content-Type':'application/json'},
       body:JSON.stringify({program:key})});
  conSince=0; document.getElementById('console').textContent='';
 }catch(e){}
 setTimeout(()=>{b.disabled=false;b.textContent='Switch / Load';loadProg();},800);
}
loadPrograms(); loadProg(); tick(); conTick();
setInterval(tick,1000); setInterval(loadProg,5000); setInterval(conTick,500); setInterval(loadPrograms,5000);
</script></body></html>
"""


def start(port: int) -> None:
    """Start the dashboard server on a daemon thread.  Returns once
    the listen socket is bound; the thread runs until the program
    exits.  Threading server so an open SSE connection on /events
    doesn't block /usage.json polling."""
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    t = threading.Thread(
        target=server.serve_forever,
        name=f"abcl-dashboard-{port}",
        daemon=True,
    )
    t.start()
    print(f"[dashboard] http://127.0.0.1:{port}/")
