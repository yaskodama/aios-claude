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
    "bounded_buffer.abcl": "Bounded buffer (local, 2 producers + 2 consumers)",
    # rpi4 (xinu-rpi4 @ .100, HTTP /actor gateway, on-device cc JIT):
    "mac_diners_rpi4.abcl": "Dining Philosophers (3 Mac + 2 Xinu rpi4, dynamic JIT)",
    "mac_only_diners.abcl": "Dining Philosophers (Mac only, 5 local)",
    "xinu_phil.abcl":       "Xinu rpi4 philosophers (P4, P5 — resident)",
    "wine_glass_rpi4.abcl":   "Rotating wine glass 2D (Xinu rpi4 Graphics window, JIT)",
    "wine_glass3d_rpi4.abcl": "Rotating wine glass 3D solid of revolution (Xinu rpi4, JIT)",
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
    if isinstance(v, (list, tuple)):         # arrays (e.g. a ring buffer's slots)
        return [_json_safe(x) for x in v]
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
  &nbsp;<a style="color:#6af" href="/chat">→ Chat</a>
  &nbsp;<a style="color:#fa6" href="/layout">→ Xinu 設定画面</a>
  &nbsp;<a style="color:#fa6" href="/shell">→ Xinu Shell</a>
  &nbsp;<a style="color:#6cf" href="/pi3">→ Pi3 Xinu 画面設計</a></small></h1>
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
        elif self.path == "/layout" or self.path.startswith("/layout?"):
            self._serve_layout_html()
        elif self.path == "/shell" or self.path.startswith("/shell?"):
            self._serve_shell_html()
        elif self.path == "/pi3" or self.path.startswith("/pi3?"):
            self._serve_pi3_html()
        elif self.path.startswith("/api/pi3/browse"):
            self._serve_pi3_browse()
        elif self.path.startswith("/api/pi3/desktop"):
            self._serve_pi3_desktop()
        elif self.path.startswith("/api/xinu/type"):
            self._serve_xinu_type()
        elif self.path.startswith("/api/xinu/click"):
            self._serve_xinu_click()
        elif self.path.startswith("/api/layout/windows"):
            self._serve_layout_windows()
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
        elif self.path.startswith("/api/layout/send"):
            self._handle_layout_send()
        elif self.path.startswith("/api/load"):
            self._handle_load()
        elif self.path.startswith("/api/speed"):
            self._handle_speed()
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

    def _handle_speed(self):
        """Live-tune the per-item delay (seconds) of the running bounded-buffer
        actors from the dashboard sliders.  Body: {"produce_ms", "consume_ms"}.
        The actor reads its own `delay` field on each loop, so writing the field
        from here takes effect on the next item without restarting anything."""
        data = self._read_json_body() or {}

        def _sec(key):
            v = data.get(key)
            try:
                return max(0.0, float(v) / 1000.0)
            except (TypeError, ValueError):
                return None

        p_sec = _sec("produce_ms")
        c_sec = _sec("consume_ms")
        with _introspect_lock:
            interp = _interp_ref
        try:
            actors = interp.scheduler.all() if interp is not None else []
        except Exception:
            actors = []
        applied = {"Producer": 0, "Consumer": 0}
        for a in actors:
            cls = getattr(getattr(a, "cls", None), "name", "")
            try:
                fields = getattr(a, "fields", None)
                if fields is None or "delay" not in fields:
                    continue
                if cls == "Producer" and p_sec is not None:
                    fields["delay"] = p_sec; applied["Producer"] += 1
                elif cls == "Consumer" and c_sec is not None:
                    fields["delay"] = c_sec; applied["Consumer"] += 1
            except Exception:
                continue
        self._send_bytes(200, "application/json",
                         json.dumps({"ok": True, "applied": applied}).encode("utf-8"))

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

    # ---- Xinu window-layout designer (all comms in AIPL) ----
    def _serve_layout_html(self):
        html = _LAYOUT_HTML.replace("XINUHOST", _LAYOUT_XINU_HOST)
        self._send_bytes(200, "text/html; charset=utf-8", html.encode("utf-8"))

    def _serve_layout_windows(self):
        """Proxy the bare-metal Xinu /windows inventory (server-side fetch so
        the browser isn't blocked by cross-origin to the Pi)."""
        host = _LAYOUT_XINU_HOST
        try:
            with urllib.request.urlopen("http://%s/windows" % host, timeout=6) as r:
                raw = r.read()
            self._send_bytes(200, "application/json", raw)
        except Exception as e:
            self._send_bytes(200, "application/json",
                             json.dumps({"error": str(e), "windows": []}).encode("utf-8"))

    def _proxy_xinu(self, path_with_query: str) -> bytes:
        """Forward a GET to the bare-metal Xinu's HTTP server.  Same server-side
        fetch pattern as _serve_layout_windows — sidesteps browser CORS."""
        host = _LAYOUT_XINU_HOST
        url = "http://%s%s" % (host, path_with_query)
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                return r.read()
        except Exception as e:
            return ("proxy error: %s" % e).encode("utf-8")

    def _serve_xinu_type(self):
        """Forward /api/xinu/type?... → http://XINUHOST/type?... ."""
        from urllib.parse import urlsplit
        q = urlsplit(self.path).query
        suffix = ("?" + q) if q else ""
        body = self._proxy_xinu("/type" + suffix)
        self._send_bytes(200, "text/plain; charset=utf-8", body)

    def _serve_xinu_click(self):
        """Forward /api/xinu/click?... → http://XINUHOST/click?... ."""
        from urllib.parse import urlsplit
        q = urlsplit(self.path).query
        suffix = ("?" + q) if q else ""
        body = self._proxy_xinu("/click" + suffix)
        self._send_bytes(200, "text/plain; charset=utf-8", body)

    def _serve_shell_html(self):
        html = _SHELL_HTML.replace("XINUHOST", _LAYOUT_XINU_HOST)
        self._send_bytes(200, "text/html; charset=utf-8", html.encode("utf-8"))

    # ---- Pi 3 (arm-rpi3) Xinu framebuffer "browser" screen-design page ----
    def _serve_pi3_html(self):
        html = _PI3_HTML.replace("PI3HOST", _PI3_XINU_HOST)
        self._send_bytes(200, "text/html; charset=utf-8", html.encode("utf-8"))

    def _serve_pi3_browse(self):
        """Proxy the designer's geometry to the Pi 3 Xinu /api/wifi/browse so the
        framebuffer window is drawn at the designed position/size (server-side
        fetch sidesteps browser CORS to the Pi)."""
        from urllib.parse import urlsplit
        q = urlsplit(self.path).query
        url = "http://%s/api/wifi/browse%s" % (_PI3_XINU_HOST, ("?" + q) if q else "")
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                bytes_hdr = r.headers.get("X-Wifi-BrowseBytes", "?")
                body = r.read()
            out = {"ok": True, "bytes": bytes_hdr, "len": len(body)}
        except Exception as e:
            out = {"ok": False, "error": str(e)}
        self._send_bytes(200, "application/json", json.dumps(out).encode("utf-8"))

    def _serve_pi3_desktop(self):
        """Proxy the multi-window layout to the Pi 3 /api/wifi/desktop."""
        from urllib.parse import urlsplit
        q = urlsplit(self.path).query
        url = "http://%s/api/wifi/desktop%s" % (_PI3_XINU_HOST, ("?" + q) if q else "")
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                bytes_hdr = r.headers.get("X-Wifi-BrowseBytes", "?")
                body = r.read()
            out = {"ok": True, "bytes": bytes_hdr, "len": len(body)}
        except Exception as e:
            out = {"ok": False, "error": str(e)}
        self._send_bytes(200, "application/json", json.dumps(out).encode("utf-8"))

    def _handle_layout_send(self):
        """Apply a designed layout to Xinu.  The 'やり取り' is all AIPL: we
        GENERATE an AIPL program of remote_now(...) move/resize calls and run
        it through the Py-I interpreter, which ships them to the resident
        Layout actor over xinujit:// (the actor calls the wm window builtins)."""
        data = self._read_json_body() or {}
        wins = data.get("windows", [])
        host = str(data.get("host") or _LAYOUT_XINU_HOST)
        proj = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        layout_abcl = os.path.join(
            proj, "aice-pi-evolution/experiments/2026-05-29_dining_rpi4/pi/xinu_layout.abcl")
        layout_c = "/tmp/xinu_layout.c"
        if not os.path.exists(layout_c):
            subprocess.run(["dune", "exec", "src/aipl2c.exe", "--", layout_abcl,
                            "--xinu-jit", "--no-typecheck", "-o", layout_c],
                           cwd=proj, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        lines = ['var pi = "xinujit://%s";' % host,
                 'print(remote_now(pi, "_", "loadfile", "%s"));' % layout_c]
        for w in wins:
            try:
                i = int(w["id"]); x = int(w["x"]); y = int(w["y"])
                ww = int(w["w"]); hh = int(w["h"])
            except (KeyError, ValueError, TypeError):
                continue
            lines.append('remote_now(pi, "0", "resize", %d, %d, %d);' % (i, ww, hh))
            lines.append('remote_now(pi, "0", "move", %d, %d, %d);' % (i, x, y))
            try:
                fs = int(w.get("fs", 1))
                if fs < 1: fs = 1
                if fs > 4: fs = 4
                lines.append('remote_now(pi, "0", "font", %d, %d);' % (i, fs))
            except (ValueError, TypeError):
                pass
        lines.append('print("layout sent");')
        prog = "\n".join(lines) + "\n"
        sendf = "/tmp/layout_send.abcl"
        with open(sendf, "w") as fh:
            fh.write(prog)
        ok = False
        out = ""
        try:
            r = subprocess.run([sys.executable,
                                os.path.join(proj, "src/python-aipl/aipl_main.py"), sendf],
                               cwd=proj, capture_output=True, text=True, timeout=60)
            ok = (r.returncode == 0)
            out = (r.stdout or "") + (r.stderr or "")
        except Exception as e:
            out = "run failed: %s" % e
        self._send_bytes(200, "application/json",
                         json.dumps({"ok": ok, "log": out[-2000:], "program": prog}).encode("utf-8"))

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


_LAYOUT_XINU_HOST = "192.168.3.100"
# Pi 3 (arm-rpi3) Xinu WiFi/HTTP server — the framebuffer "browser" lives here.
_PI3_XINU_HOST = "192.168.3.50:8080"

# Xinu shell-input UI.  Type into the bare-metal Pi 4's `Shell (UART)` window
# from the browser.  Hits /api/xinu/type (server-side proxy → Pi's /type) so
# CORS isn't a problem.  Includes a button strip for the special keys the Pi
# now handles (Enter, Esc, Backspace, arrows for history/clear, Ctrl-U,
# Ctrl-C) plus a mouse-delta sender that forwards to /api/xinu/click.
_SHELL_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Xinu Shell Input (XINUHOST)</title>
<style>
 body{font-family:ui-monospace,Menlo,Consolas,monospace;background:#0b0f14;color:#d8dee9;margin:0;padding:16px;max-width:880px}
 h2{margin:0 0 8px;color:#8af}
 small{color:#778}
 #line{width:560px;font:inherit;background:#111722;color:#dde;border:1px solid #345;border-radius:4px;padding:6px 8px}
 button{font:inherit;background:#243;color:#d8ffd8;border:1px solid #4a6;border-radius:4px;padding:4px 10px;cursor:pointer;margin:2px}
 button.send{background:#354a7a;color:#dde8ff;border-color:#6a8}
 button.key{background:#332;color:#fde;border-color:#864}
 #log{background:#050810;color:#9ab;padding:8px;border:1px solid #223;height:240px;overflow-y:auto;white-space:pre-wrap;font-size:0.85rem;margin-top:10px}
 .row{margin:10px 0}
 .row label{color:#aaa;margin-right:8px}
 input.num{width:60px;font:inherit;background:#111722;color:#dde;border:1px solid #345;border-radius:4px;padding:4px 6px}
 a{color:#6af}
</style></head><body>
<h2>Xinu Shell Input — XINUHOST</h2>
<small>Types into the bare-metal Pi 4's <code>Shell (UART)</code> wm-window (xhci_keyboard_event hook).
&nbsp;<a href="/">← Dashboard</a>  &nbsp;<a href="/layout">→ Xinu 設定画面</a></small>

<div class="row">
  <input id="line" type="text" autofocus placeholder="type a shell command and press Enter…">
  <button class="send" id="send">Send + Enter</button>
</div>

<div class="row">
  <strong style="color:#aaa">Keys:</strong>
  <button class="key" data-key="enter">Enter ↵</button>
  <button class="key" data-key="bs">⌫ Backspace</button>
  <button class="key" data-key="esc">Esc</button>
  <button class="key" data-key="tab">Tab</button>
  <button class="key" data-key="up">↑ (history)</button>
  <button class="key" data-key="down">↓ (clear)</button>
  <button class="key" data-key="left">←</button>
  <button class="key" data-key="right">→</button>
  <button class="key" data-key="home">Home</button>
  <button class="key" data-key="end">End</button>
  <button class="key" data-key="ctrl-c">Ctrl-C</button>
  <button class="key" data-key="ctrl-u">Ctrl-U</button>
  <button class="key" data-key="ctrl-l">Ctrl-L</button>
</div>

<div class="row">
  <strong style="color:#aaa">Mouse:</strong>
  <label>dx<input class="num" id="dx" type="number" value="0"></label>
  <label>dy<input class="num" id="dy" type="number" value="0"></label>
  <label>btn
    <select id="btn" style="font:inherit;background:#111722;color:#dde;border:1px solid #345;border-radius:4px;padding:3px">
      <option value="0">none</option>
      <option value="1">Left</option>
      <option value="2">Right</option>
      <option value="4">Middle</option>
    </select>
  </label>
  <button class="send" id="click">Send move/click</button>
</div>

<div id="log"></div>

<script>
const logEl = document.getElementById('log');
function log(s) {
  const ts = new Date().toLocaleTimeString();
  logEl.textContent = '[' + ts + '] ' + s.trim() + '\\n' + logEl.textContent;
}
async function sendType(text, key) {
  const p = new URLSearchParams();
  if (text) p.set('t', text);
  if (key)  p.set('key', key);
  try {
    const r = await fetch('/api/xinu/type?' + p.toString());
    log((text ? ('t="'+text+'" ') : '') + (key ? ('key='+key+' ') : '') + '→ ' + await r.text());
  } catch (e) {
    log('ERR ' + e);
  }
}
document.getElementById('send').onclick = async () => {
  const t = document.getElementById('line').value;
  document.getElementById('line').value = '';
  await sendType(t, 'enter');
};
document.getElementById('line').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); document.getElementById('send').click(); }
});
document.querySelectorAll('button.key').forEach(b => {
  b.onclick = () => sendType('', b.dataset.key);
});
document.getElementById('click').onclick = async () => {
  const dx = document.getElementById('dx').value || 0;
  const dy = document.getElementById('dy').value || 0;
  const btn = document.getElementById('btn').value || 0;
  try {
    const r = await fetch('/api/xinu/click?dx=' + dx + '&dy=' + dy + '&btn=' + btn);
    log('mouse dx='+dx+' dy='+dy+' btn='+btn+' → ' + await r.text());
  } catch (e) {
    log('ERR ' + e);
  }
};
log('ready — Xinu host: XINUHOST');
</script>
</body></html>
"""

# Xinu window-layout designer.  Drag/resize the window rectangles over a scaled
# view of the Xinu virtual desktop, then 送信 (Send) — the dashboard generates
# an AIPL program of remote_now(...) move/resize calls and runs it, so the
# whole exchange to the bare-metal Pi is in AIPL.
_LAYOUT_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Py-I — Xinu screen layout designer</title>
<style>
 body{font-family:ui-monospace,Menlo,Consolas,monospace;background:#0b0f14;color:#d8dee9;margin:0;padding:16px}
 h2{margin:0 0 8px}
 #bar{margin:8px 0}
 button{font:inherit;background:#243; color:#d8ffd8; border:1px solid #4a6; border-radius:6px; padding:6px 14px; cursor:pointer}
 button.send{background:#354a7a;color:#dde8ff;border-color:#6a8}
 #desk{position:relative;background:#003366;border:1px solid #355;margin-top:10px}
 #screen{position:absolute;border:1px dashed #7aa;pointer-events:none;color:#9bd;font-size:10px}
 .win{position:absolute;background:rgba(40,30,60,0.85);border:1px solid #b8e;border-radius:3px;
      box-sizing:border-box;overflow:hidden;cursor:move;font-size:11px}
 .win .t{background:#503070;color:#fff;padding:1px 4px;white-space:nowrap;overflow:hidden}
 .win .t button.fb{font:inherit;font-size:10px;line-height:1;padding:0 5px;margin-left:2px;
      background:#71539a;color:#fff;border:1px solid #a8e;border-radius:3px;cursor:pointer}
 .win .sz{padding:2px 4px;color:#bcd;font-size:10px;pointer-events:none}
 .win .h{position:absolute;right:0;bottom:0;width:12px;height:12px;background:#b8e;cursor:nwse-resize}
 #log{white-space:pre-wrap;background:#0d1117;border:1px solid #333;border-radius:6px;
      padding:8px;margin-top:10px;max-height:160px;overflow:auto;font-size:12px}
 .muted{color:#8aa}
</style></head><body>
<h2>Xinu screen layout designer <span class=muted style="font-size:13px">(host XINUHOST)</span></h2>
<div class=muted>Drag a window to move it; drag the corner handle to resize; +/- changes its font size. The frame is the Xinu 1024×768 screen.</div>
<div id=bar>
  <button onclick="reload()">↻ Xinuから取得 (Reload)</button>
  <button class=send onclick="send()">送信 (Send) →</button>
  <span id=status class=muted></span>
</div>
<div id=desk></div>
<div id=log class=muted>ready.</div>
<script>
const DW=1024, DH=768, SCALE=0.55;          // the 1024x768 visible Xinu screen
const SW=1024, SH=768;
let wins=[];                                 // [{id,name,x,y,w,h}]
const desk=document.getElementById('desk'), status=document.getElementById('status'), logEl=document.getElementById('log');
desk.style.width=(DW*SCALE)+'px'; desk.style.height=(DH*SCALE)+'px';

function log(s){ logEl.textContent = s; }
function render(){
  desk.innerHTML='';
  wins.forEach((w,idx)=>{
    const d=document.createElement('div'); d.className='win'; d.dataset.i=idx;
    d.style.left=(w.x*SCALE)+'px'; d.style.top=(w.y*SCALE)+'px';
    d.style.width=(w.w*SCALE)+'px'; d.style.height=(w.h*SCALE)+'px';
    if(!w.fs){ w.fs=1; }
    const t=document.createElement('div'); t.className='t';
    const nm=document.createElement('span'); nm.textContent=w.id+': '+w.name+'  A'+w.fs; t.appendChild(nm);
    const bm=document.createElement('button'); bm.className='fb'; bm.textContent='-';
    const bp=document.createElement('button'); bp.className='fb'; bp.textContent='+';
    bm.onmousedown=e=>e.stopPropagation(); bp.onmousedown=e=>e.stopPropagation();
    bm.onclick=e=>{ e.stopPropagation(); w.fs=Math.max(1,w.fs-1); render(); };
    bp.onclick=e=>{ e.stopPropagation(); w.fs=Math.min(4,w.fs+1); render(); };
    t.appendChild(bm); t.appendChild(bp); d.appendChild(t);
    // hint: scale the title font so the size is visible in the designer too
    t.style.fontSize=(11+(w.fs-1)*4)+'px';
    // live size + position readout (updates as you drag / resize)
    const sz=document.createElement('div'); sz.className='sz';
    sz.textContent=w.w+'x'+w.h+'  ('+w.x+','+w.y+')';
    d.appendChild(sz);
    const h=document.createElement('div'); h.className='h'; d.appendChild(h);
    desk.appendChild(d);
    d.addEventListener('mousedown', e=>{ if(e.target===h) startResize(e,idx); else startMove(e,idx); });
  });
}
function startMove(e,idx){
  e.preventDefault();
  const w=wins[idx], sx=e.clientX, sy=e.clientY, ox=w.x, oy=w.y;
  function mv(ev){ w.x=Math.max(0,Math.round(ox+(ev.clientX-sx)/SCALE)); w.y=Math.max(0,Math.round(oy+(ev.clientY-sy)/SCALE)); render(); }
  function up(){ document.removeEventListener('mousemove',mv); document.removeEventListener('mouseup',up); }
  document.addEventListener('mousemove',mv); document.addEventListener('mouseup',up);
}
function startResize(e,idx){
  e.preventDefault(); e.stopPropagation();
  const w=wins[idx], sx=e.clientX, sy=e.clientY, ow=w.w, oh=w.h;
  function mv(ev){ w.w=Math.max(40,Math.round(ow+(ev.clientX-sx)/SCALE)); w.h=Math.max(24,Math.round(oh+(ev.clientY-sy)/SCALE)); render(); }
  function up(){ document.removeEventListener('mousemove',mv); document.removeEventListener('mouseup',up); }
  document.addEventListener('mousemove',mv); document.addEventListener('mouseup',up);
}
async function reload(){
  status.textContent='loading from Xinu...';
  try{
    const r=await fetch('/api/layout/windows'); const j=await r.json();
    if(Array.isArray(j)){ wins=j; } else if(j.windows){ wins=j.windows; } else { wins=[]; }
    if(j.error){ log('Xinu /windows error: '+j.error+' (load a program on Xinu? Pi reachable?)'); }
    else { log('loaded '+wins.length+' windows from Xinu.'); }
    status.textContent=wins.length+' windows';
    render();
  }catch(e){ log('reload failed: '+e); status.textContent='error'; }
}
async function send(){
  status.textContent='sending (AIPL)...';
  const payload={host:'XINUHOST', windows:wins.map(w=>({id:w.id,x:w.x,y:w.y,w:w.w,h:w.h,fs:w.fs||1}))};
  try{
    const r=await fetch('/api/layout/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const j=await r.json();
    status.textContent = j.ok ? 'sent ✓' : 'send error';
    log('--- generated AIPL ---\\n'+(j.program||'')+'\\n--- run log ---\\n'+(j.log||''));
  }catch(e){ log('send failed: '+e); status.textContent='error'; }
}
reload();
</script></body></html>"""

# Pi 3 (arm-rpi3) Xinu framebuffer "browser" screen-design page.  Drag/resize a
# single window over a scaled 1024x768 view of the Pi 3 HDMI screen, set the URL,
# then 送信 — we forward the geometry to the Pi 3's /api/wifi/browse so the
# bare-metal kernel fetches the page and draws the window there.
_PI3_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Py-I — Pi3 Xinu screen design</title>
<style>
 body{font-family:ui-monospace,Menlo,Consolas,monospace;background:#0b0f14;color:#d8dee9;margin:0;padding:16px}
 h2{margin:0 0 8px} .muted{color:#8aa}
 #bar{margin:8px 0} label{font-size:13px;color:#9bd}
 input{font:inherit;background:#11161d;color:#d8dee9;border:1px solid #3b4757;border-radius:5px;padding:4px 8px}
 button{font:inherit;background:#243;color:#d8ffd8;border:1px solid #4a6;border-radius:6px;padding:6px 14px;cursor:pointer}
 button.send{background:#354a7a;color:#dde8ff;border-color:#6a8}
 #desk{position:relative;background:#402000;border:1px solid #553;margin-top:10px}
 .win{position:absolute;background:#fff;border:2px solid #000;border-radius:2px;box-sizing:border-box;
      overflow:hidden;cursor:move}
 .win .t{background:#0050c0;color:#fff;padding:1px 5px;white-space:nowrap;overflow:hidden;font-size:11px}
 .win .b{color:#222;font-size:9px;padding:2px 4px;pointer-events:none}
 .win .sz{position:absolute;left:4px;bottom:2px;color:#666;font-size:9px;pointer-events:none}
 .win .h{position:absolute;right:0;bottom:0;width:12px;height:12px;background:#0050c0;cursor:nwse-resize}
 #log{white-space:pre-wrap;background:#0d1117;border:1px solid #333;border-radius:6px;padding:8px;margin-top:10px;
      max-height:160px;overflow:auto;font-size:12px}
</style></head><body>
<h2>Pi3 Xinu screen design <span class=muted style="font-size:13px">(framebuffer browser &mdash; host PI3HOST)</span></h2>
<div class=muted>Pi 3 bare-metal Xinu の HDMI 画面(1024&times;768)に出す 3 つのウィンドウ
 (Browser / Soft keyboard / Shell) の配置をデザインします。各ウィンドウをドラッグで移動、右下ハンドルでリサイズ。
 URL を入れて 送信 すると Pi 3 が 3 窓を描画し、Browser はそのページを取得して表示します。</div>
<div id=bar>
  <label>URL host: <input id=host value="kodamay.org" size=18></label>
  <label>IP: <input id=ip value="160.251.151.122" size=15></label>
  <button class=send onclick="send()">送信 (Send to Pi3) &rarr;</button>
  <button id=livebtn onclick="toggleLive()">&#9679; Live: OFF</button>
  <button onclick="reset_()">&#8635; reset</button>
  <span id=status class=muted></span>
</div>
<div id=desk></div>
<div id=log class=muted>ready. (Pi 3 must be WiFi-connected + DHCP'd first)</div>
<script>
const DW=1024, DH=768, SCALE=1.1;     // ~2x of the previous 0.6 preview
let LIVE=false, liveFetched=false, liveTimer=null;
const desk=document.getElementById('desk'), status=document.getElementById('status'), logEl=document.getElementById('log');
desk.style.width=(DW*SCALE)+'px'; desk.style.height=(DH*SCALE)+'px';
// Three windows like the Pi 4 desktop: Browser, Soft keyboard, Shell.
const DEF={ b:{x:40,y:40,w:560,h:360}, k:{x:40,y:440,w:720,h:260}, s:{x:620,y:40,w:380,h:260} };
let W={ b:{...DEF.b}, k:{...DEF.k}, s:{...DEF.s} };
const TITLES={ b:'Xinu Browser', k:'Soft keyboard', s:'Shell (UART)' };
const TBAR ={ b:'#0050c0', k:'#504030', s:'#705030' };
function log(s){ logEl.textContent=s; }
function render(){
  desk.innerHTML='';
  for(const id of ['s','k','b']){            // shell/keyboard under, browser on top
    const w=W[id];
    const d=document.createElement('div'); d.className='win'; d.dataset.id=id;
    d.style.left=(w.x*SCALE)+'px'; d.style.top=(w.y*SCALE)+'px';
    d.style.width=(w.w*SCALE)+'px'; d.style.height=(w.h*SCALE)+'px';
    const t=document.createElement('div'); t.className='t'; t.style.background=TBAR[id];
    t.textContent = id==='b' ? (TITLES.b+'   http://'+document.getElementById('host').value+'/') : TITLES[id];
    const b=document.createElement('div'); b.className='b';
    b.textContent = id==='b' ? '(page text)' : (id==='k' ? '[1234567890] [QWERTY…] [SPACE Enter]' : 'xsh $ _');
    const sz=document.createElement('div'); sz.className='sz'; sz.textContent=w.w+'x'+w.h+' ('+w.x+','+w.y+')';
    const h=document.createElement('div'); h.className='h';
    d.appendChild(t); d.appendChild(b); d.appendChild(sz); d.appendChild(h); desk.appendChild(d);
    d.addEventListener('mousedown', e=>{ if(e.target===h) startResize(e,id); else startMove(e,id); });
  }
}
function startMove(e,id){ e.preventDefault();
  const w=W[id], sx=e.clientX, sy=e.clientY, ox=w.x, oy=w.y;
  function mv(ev){ w.x=Math.max(0,Math.round(ox+(ev.clientX-sx)/SCALE)); w.y=Math.max(0,Math.round(oy+(ev.clientY-sy)/SCALE)); render(); }
  function up(){ document.removeEventListener('mousemove',mv); document.removeEventListener('mouseup',up); liveSync(); }
  document.addEventListener('mousemove',mv); document.addEventListener('mouseup',up);
}
function startResize(e,id){ e.preventDefault(); e.stopPropagation();
  const w=W[id], sx=e.clientX, sy=e.clientY, ow=w.w, oh=w.h;
  function mv(ev){ w.w=Math.max(80,Math.round(ow+(ev.clientX-sx)/SCALE)); w.h=Math.max(60,Math.round(oh+(ev.clientY-sy)/SCALE)); render(); }
  function up(){ document.removeEventListener('mousemove',mv); document.removeEventListener('mouseup',up); liveSync(); }
  document.addEventListener('mousemove',mv); document.addEventListener('mouseup',up);
}
function reset_(){ W={ b:{...DEF.b}, k:{...DEF.k}, s:{...DEF.s} }; render(); liveSync(); }
function toggleLive(){
  LIVE=!LIVE;
  document.getElementById('livebtn').textContent=(LIVE?'\\u25CF Live: ON':'\\u25CF Live: OFF');
  document.getElementById('livebtn').style.background=LIVE?'#3a7a4a':'';
  if(LIVE){ liveFetched=false; doSend(true); }   // first live send fetches the page
}
function liveSync(){            // debounced auto-send while Live is ON
  if(!LIVE) return;
  if(liveTimer) clearTimeout(liveTimer);
  liveTimer=setTimeout(()=>doSend(!liveFetched), 350);  // after first fetch, redraw from cache (fast)
}
function send(){ doSend(true); }    // manual 送信 always (re-)fetches the page
async function doSend(fetchPage){
  status.textContent = fetchPage ? 'sending (fetch)...' : 'live sync...';
  const host=encodeURIComponent(document.getElementById('host').value);
  const ip=encodeURIComponent(document.getElementById('ip').value);
  const q='?host='+host+'&ip='+ip+'&fetch='+(fetchPage?1:0)
    +'&bx='+W.b.x+'&by='+W.b.y+'&bw='+W.b.w+'&bh='+W.b.h
    +'&kx='+W.k.x+'&ky='+W.k.y+'&kw='+W.k.w+'&kh='+W.k.h
    +'&sx='+W.s.x+'&sy='+W.s.y+'&sw='+W.s.w+'&sh='+W.s.h;
  try{
    const r=await fetch('/api/pi3/desktop'+q); const j=await r.json();
    if(j.ok){ if(fetchPage) liveFetched=true;
      status.textContent=(LIVE?'live ✓':'drawn on Pi3 ✓');
      log('Pi3 drew the 3 windows'+(fetchPage?' (browser fetched '+j.bytes+' bytes)':' (live move, cached page)')+'.'); }
    else { status.textContent='error'; log('send failed: '+j.error+'\\n(Pi 3 connected to WiFi + DHCP done?)'); }
  }catch(e){ status.textContent='error'; log('send failed: '+e); }
}
document.getElementById('host').addEventListener('input',render);
render();
</script></body></html>"""

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
<h2>Visualization</h2>
<canvas id="viz" width="760" height="360"
  style="background:#0b0f14;border:1px solid #2a3340;border-radius:6px;display:block;max-width:100%"></canvas>
<div style="color:#7a8a99;font-size:11px;margin:4px 0 0">
  philosophers around the ring (blue=thinking, amber=hungry/waiting, green=eating,
  grey=done/stopped); forks shown between them, with a green arrow pointing to
  the philosopher currently holding the fork.
  Remote programs only show the local (Mac) actors here.
</div>
<div id="speedctl" style="display:none;margin:8px 0 0;padding:8px 10px;background:#11161d;border:1px solid #2a3340;border-radius:6px;max-width:760px">
  <div style="color:#cdd6e0;font-size:12px;margin-bottom:6px">Bounded-buffer speed &mdash; drag to retune the running actors (left = faster, right = slower)</div>
  <label style="display:flex;align-items:center;gap:8px;color:#81a1c1;font-size:12px;margin:3px 0">
    <span style="width:120px">Producer interval</span>
    <input id="pspeed" type="range" min="50" max="2000" step="10" value="300" oninput="pushSpeed()" style="flex:1">
    <span id="pspeedv" style="width:58px;text-align:right">300 ms</span>
  </label>
  <label style="display:flex;align-items:center;gap:8px;color:#a3be8c;font-size:12px;margin:3px 0">
    <span style="width:120px">Consumer interval</span>
    <input id="cspeed" type="range" min="50" max="2000" step="10" value="500" oninput="pushSpeed()" style="flex:1">
    <span id="cspeedv" style="width:58px;text-align:right">500 ms</span>
  </label>
</div>
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
  if(action==='start'){ setTimeout(tick,400); setTimeout(loadProg,500); setTimeout(pushSpeed,800); }
 }catch(e){}
}
async function pushSpeed(){
 const pe=document.getElementById('pspeed'), ce=document.getElementById('cspeed');
 if(!pe||!ce) return;
 const p=+pe.value, c=+ce.value;
 document.getElementById('pspeedv').textContent=p+' ms';
 document.getElementById('cspeedv').textContent=c+' ms';
 try{ await fetch('/api/speed',{method:'POST',headers:{'Content-Type':'application/json'},
       body:JSON.stringify({produce_ms:p,consume_ms:c})}); }catch(e){}
}
function philColor(p){
 const f=p.fields||{}; const st=String(f.status||'').toLowerCase();
 if(p.state==='stopped'||st.indexOf('done')>=0||st.indexOf('terminat')>=0) return '#7a8a99';
 if(st.indexOf('eat')>=0) return '#a3be8c';
 if(st.indexOf('wait')>=0||st.indexOf('took')>=0||st.indexOf('fork')>=0) return '#ebcb8b';
 if(st.indexOf('think')>=0) return '#81a1c1';
 return p.state==='busy' ? '#ebcb8b' : '#81a1c1';
}
function drawArrow(ctx,x1,y1,x2,y2,color){
 const dx=x2-x1, dy=y2-y1, len=Math.hypot(dx,dy); if(len<1) return;
 const ux=dx/len, uy=dy/len;
 const sx=x1+ux*9, sy=y1+uy*9;       // start just outside the fork marker
 const ex=x2-ux*24, ey=y2-uy*24;      // stop at the philosopher node edge
 ctx.strokeStyle=color; ctx.fillStyle=color; ctx.lineWidth=2.5;
 ctx.beginPath(); ctx.moveTo(sx,sy); ctx.lineTo(ex,ey); ctx.stroke();
 const ah=9, aa=Math.atan2(ey-sy,ex-sx);
 ctx.beginPath(); ctx.moveTo(ex,ey);
 ctx.lineTo(ex-ah*Math.cos(aa-0.45), ey-ah*Math.sin(aa-0.45));
 ctx.lineTo(ex-ah*Math.cos(aa+0.45), ey-ah*Math.sin(aa+0.45));
 ctx.closePath(); ctx.fill();
}
// ── bounded-buffer view ───────────────────────────────────────────────
// Producers on the left, consumers on the right, the buffer's ring of
// slots in the middle (filled boxes = live items, drained from `head`).
function pcColor(a){
 const f=a.fields||{}; const st=String(f.status||'').toLowerCase();
 if(a.state==='stopped'||st.indexOf('done')>=0||st.indexOf('terminat')>=0) return '#7a8a99';
 if(st.indexOf('block')>=0||st.indexOf('wait')>=0||st.indexOf('full')>=0||st.indexOf('empty')>=0) return '#ebcb8b';
 return '#81a1c1';   // producing / consuming
}
function flowArrow(ctx,x1,y1,x2,y2,color){
 ctx.strokeStyle=color; ctx.fillStyle=color; ctx.lineWidth=2;
 ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke();
 const mx=(x1+x2)/2, my=(y1+y2)/2, a=Math.atan2(y2-y1,x2-x1), ah=7;
 ctx.beginPath(); ctx.moveTo(mx,my);
 ctx.lineTo(mx-ah*Math.cos(a-0.5), my-ah*Math.sin(a-0.5));
 ctx.lineTo(mx-ah*Math.cos(a+0.5), my-ah*Math.sin(a+0.5));
 ctx.closePath(); ctx.fill();
}
function drawBuffer(ctx,W,H,actors,buf){
 const cx=W/2, cy=H/2;
 const prods=actors.filter(a=>a['class']==='Producer');
 const cons =actors.filter(a=>a['class']==='Consumer');
 const bf=buf.fields||{};
 const cap=Number(bf.cap)||5, count=Number(bf.count)||0;
 const head=Number(bf.head)||0, tail=Number(bf.tail)||0;
 const slots=Array.isArray(bf.slots)?bf.slots:[];
 const occ=new Array(cap).fill(false);
 for(let k=0;k<count;k++) occ[((head+k)%cap+cap)%cap]=true;
 const hIdx=((head%cap)+cap)%cap, tIdx=((tail%cap)+cap)%cap;
 const clamp=(v,lo,hi)=>Math.max(lo,Math.min(hi,v));
 // buffer as a single wide row spanning the canvas; producers feed it from
 // above, consumers drain it below.
 const margin=16, gap=4;
 const bw=Math.max(12, Math.min(46, Math.floor((W-2*margin-(cap-1)*gap)/cap)));
 const bh=40;
 const rowW=cap*bw+(cap-1)*gap, gx=cx-rowW/2, gy=cy-bh/2;
 ctx.textAlign='center';
 ctx.fillStyle='#cdd6e0'; ctx.font='12px monospace';
 ctx.fillText('bounded buffer   '+count+'/'+cap+'   head='+hIdx+'   tail='+tIdx, cx, gy-12);
 for(let i=0;i<cap;i++){
  const bx=gx+i*(bw+gap);
  ctx.fillStyle=occ[i]?'#2e4b2e':'#11161d'; ctx.fillRect(bx,gy,bw,bh);
  ctx.lineWidth=2;
  ctx.strokeStyle = (i===hIdx)?'#88c0d0' : (i===tIdx)?'#d08770' : (occ[i]?'#a3be8c':'#2a3340');
  ctx.strokeRect(bx,gy,bw,bh);
  if(occ[i] && slots[i]!==undefined && bw>=18){
   ctx.fillStyle='#e5e9f0'; ctx.font=(bw>=28?'12px':'9px')+' monospace'; ctx.textBaseline='middle';
   ctx.fillText(String(slots[i]), bx+bw/2, gy+bh/2); ctx.textBaseline='alphabetic';
  }
 }
 ctx.font='10px monospace'; ctx.fillStyle='#88c0d0'; ctx.textAlign='center';
 ctx.fillText('head = next read (cyan)', cx-90, gy+bh+16);
 ctx.fillStyle='#d08770'; ctx.fillText('tail = next write (orange)', cx+90, gy+bh+16);
 // producers across the top, consumers across the bottom
 const placeRow=(list,y,x0,x1)=>{
  const n=list.length; if(!n) return [];
  if(n===1) return [{a:list[0],x:(x0+x1)/2,y}];
  return list.map((a,i)=>({a,x:x0+(x1-x0)*i/(n-1),y}));
 };
 const xspread=Math.min(140, cx-40);
 const P=placeRow(prods, gy-72, cx-xspread, cx+xspread);
 const C=placeRow(cons,  gy+bh+72, cx-xspread, cx+xspread);
 P.forEach(o=>flowArrow(ctx,o.x,o.y+20, clamp(o.x,gx+bw/2,gx+rowW-bw/2),gy-5, pcColor(o.a)));
 C.forEach(o=>flowArrow(ctx, clamp(o.x,gx+bw/2,gx+rowW-bw/2),gy+bh+5, o.x,o.y-20, pcColor(o.a)));
 const node=(o,prefix,sub)=>{
  const f=o.a.fields||{};
  ctx.beginPath(); ctx.arc(o.x,o.y,20,0,2*Math.PI);
  ctx.fillStyle=pcColor(o.a); ctx.fill();
  ctx.lineWidth=2; ctx.strokeStyle='#0b0f14'; ctx.stroke();
  ctx.fillStyle='#0b0f14'; ctx.font='bold 11px monospace'; ctx.textAlign='center';
  ctx.fillText(prefix+(f.id!==undefined?f.id:''), o.x, o.y+1);
  ctx.fillStyle='#cdd6e0'; ctx.font='10px monospace';
  const s=sub(f); if(s) ctx.fillText(s, o.x, o.y-28);
  const lbl=String(f.status||''); if(lbl){ ctx.fillStyle='#8fbcbb'; ctx.font='9px monospace';
   ctx.fillText(lbl.slice(0,20), o.x, o.y-40); }
 };
 P.forEach(o=>node(o,'P',f=>(f.made!==undefined?('made '+f.made+(f.target!==undefined?'/'+f.target:'')):'')));
 // consumer sub-label sits below its node (room there); status above.
 const cnode=(o)=>{
  const f=o.a.fields||{};
  ctx.beginPath(); ctx.arc(o.x,o.y,20,0,2*Math.PI);
  ctx.fillStyle=pcColor(o.a); ctx.fill();
  ctx.lineWidth=2; ctx.strokeStyle='#0b0f14'; ctx.stroke();
  ctx.fillStyle='#0b0f14'; ctx.font='bold 11px monospace'; ctx.textAlign='center';
  ctx.fillText('C'+(f.id!==undefined?f.id:''), o.x, o.y+1);
  ctx.fillStyle='#cdd6e0'; ctx.font='10px monospace';
  if(f.got!==undefined) ctx.fillText('got '+f.got, o.x, o.y+33);
  const lbl=String(f.status||''); if(lbl){ ctx.fillStyle='#8fbcbb'; ctx.font='9px monospace';
   ctx.fillText(lbl.slice(0,20), o.x, o.y+45); }
 };
 C.forEach(cnode);
 ctx.fillStyle='#7a8a99'; ctx.font='11px monospace'; ctx.textAlign='center';
 ctx.fillText('producers', cx, 14); ctx.fillText('consumers', cx, H-6);
}
function drawViz(actors){
 const cv=document.getElementById('viz'); if(!cv) return;
 const ctx=cv.getContext('2d'); const W=cv.width,H=cv.height;
 ctx.clearRect(0,0,W,H);
 const bufs=actors.filter(a=>a['class']==='Buffer');
 if(bufs.length){ drawBuffer(ctx,W,H,actors,bufs[0]); return; }
 const phils=actors.filter(a=>a['class']==='Philosopher'||a['class']==='Node');
 const forks=actors.filter(a=>a['class']==='Fork');
 const cx=W/2, cy=H/2, R=Math.min(W,H)*0.33;
 const n=phils.length||1;
 // pass 1: philosopher positions, indexed by their pid (id / my_id) so a held
 // fork can draw an arrow to its holder.
 const posById={};
 const philData=phils.map((p,i)=>{
  const ang=(i/n)*2*Math.PI - Math.PI/2;
  const px=cx+Math.cos(ang)*R, py=cy+Math.sin(ang)*R;
  const f=p.fields||{};
  const pid=(f.id!==undefined)?f.id:f.my_id;
  if(pid!==undefined && pid!==null) posById[pid]={x:px,y:py};
  return {p:p, px:px, py:py};
 });
 // each fork sits BETWEEN the two philosophers that actually use it (their
 // lo/hi reference it), so it's drawn adjacent to its real neighbours.
 const forkUsers={};
 philData.forEach(({p,px,py})=>{
  const f=p.fields||{};
  [f.lo,f.hi].forEach(ref=>{
   if(ref===undefined||ref===null) return;
   let nm=String(ref); const m=nm.match(/<actor (.+)>/); if(m) nm=m[1];
   (forkUsers[nm]=forkUsers[nm]||[]).push({x:px,y:py});
  });
 });
 const nf=forks.length;
 forks.forEach((fk,i)=>{
  let fx,fy;
  const u=forkUsers[fk.name];
  if(u && u.length){              // midpoint of its users, projected onto ring
   let mx=0,my=0; u.forEach(q=>{mx+=q.x;my+=q.y;}); mx/=u.length; my/=u.length;
   const a=Math.atan2(my-cy,mx-cx); fx=cx+Math.cos(a)*R; fy=cy+Math.sin(a)*R;
  }else{                          // fallback when users are unknown (remote)
   const a=(i/Math.max(nf,1))*2*Math.PI - Math.PI/2 - Math.PI/Math.max(nf,1);
   fx=cx+Math.cos(a)*R; fy=cy+Math.sin(a)*R;
  }
  const h=(fk.fields||{}).holder||0;
  if(h && h!==0 && posById[h]) drawArrow(ctx,fx,fy,posById[h].x,posById[h].y,'#a3be8c');
  const tang=Math.atan2(fy-cy,fx-cx);
  ctx.fillStyle=(h&&h!==0)?'#a3be8c':'#46505e';
  ctx.save(); ctx.translate(fx,fy); ctx.rotate(tang+Math.PI/2);
  ctx.fillRect(-3,-11,6,22); ctx.restore();
  ctx.fillStyle='#cdd6e0'; ctx.font='10px monospace'; ctx.textAlign='center';
  ctx.fillText(fk.name+(h?(' -> P'+h):''), fx, fy-14);
 });
 // pass 3: philosopher nodes on top.
 philData.forEach(({p,px,py})=>{
  ctx.beginPath(); ctx.arc(px,py,22,0,2*Math.PI);
  ctx.fillStyle=philColor(p); ctx.fill();
  ctx.lineWidth=2; ctx.strokeStyle='#0b0f14'; ctx.stroke();
  ctx.fillStyle='#0b0f14'; ctx.font='bold 12px monospace'; ctx.textAlign='center';
  ctx.fillText(p.name, px, py+1);
  const f=p.fields||{};
  const meals=(f.meals!==undefined)?f.meals:((f.meals_done!==undefined)?f.meals_done:((f.hops!==undefined)?f.hops:''));
  const tgt=(f.target!==undefined)?f.target:((f.meals_target!==undefined)?f.meals_target:'');
  ctx.fillStyle='#cdd6e0'; ctx.font='11px monospace';
  if(meals!=='') ctx.fillText('meal '+meals+(tgt!==''?('/'+tgt):''), px, py+38);
  const lbl=String(f.status||p.state||'');
  if(lbl){ ctx.fillStyle='#8fbcbb'; ctx.font='10px monospace'; ctx.fillText(lbl.slice(0,22), px, py+52); }
 });
 if(phils.length===0){ ctx.fillStyle='#7a8a99'; ctx.font='13px monospace'; ctx.textAlign='center';
   ctx.fillText('(no philosopher actors - press Start)', cx, cy); }
}
async function tick(){
 try{ const a=await (await fetch('/api/actors')).json();
  document.getElementById('count').textContent=a.actors.length;
  document.getElementById('ts').textContent=new Date().toLocaleTimeString();
  setState(a.paused,a.stopped,a.started);
  drawViz(a.actors);
  const isBuf=a.actors.some(x=>x['class']==='Buffer'||x['class']==='Producer'||x['class']==='Consumer');
  const sc=document.getElementById('speedctl'); if(sc) sc.style.display=isBuf?'block':'none';
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
