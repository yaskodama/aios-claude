"""AICE home — a portal page (kodama-lab.com style) linking to every AIPL
runtime dashboard / server built in this project.

Each card now has Start / Stop / Open buttons and a live status LED.  The
portal launches the documented dashboard commands itself (server-side
allowlist in TARGETS — no arbitrary commands), polls each port for liveness,
and can stop the processes it started.

Run:
    python3 src/aice_home.py            # serves http://127.0.0.1:8888/
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# repo root, derived from this file's location (src/aice_home.py)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Server-side allowlist. Only these ids can be started; the launch command and
# working directory are fixed here, never taken from the request.
TARGETS = [
    {
        "id": "pyi",
        "glyph": "Py&middot;I",
        "portlabel": ":8899/actors",
        "title": "Py-I &mdash; Python runtime",
        "desc": "Actor dashboard: dining philosophers, bounded buffer (capacity 20 + live speed sliders), token ring. Live actor table, console, ring/buffer visualization.",
        "addr": "127.0.0.1:8899/actors",
        "href": "http://127.0.0.1:8899/actors",
        "port": 8899,
        "cwd": REPO,
        "cmd": "python3 src/python-aipl/aipl_main.py --dashboard 8899 "
               "aice-pi-evolution/experiments/2026-05-27_dining_mac_xinu/local_diners.abcl",
    },
    {
        "id": "ocaml",
        "glyph": "OCaml",
        "portlabel": ":8080/dashboard",
        "title": "OCaml &mdash; web gateway",
        "desc": "Reference runtime. Program selector (philosophers / bounded buffer + speed sliders / ping-pong / counter / hello), actor table, console, buffer viz, and source view.",
        "addr": "localhost:8080/dashboard",
        "href": "http://localhost:8080/dashboard",
        "port": 8080,
        "cwd": REPO,
        "cmd": "dune build && { printf 'load src/gateway_launch.abcl\\ncompile\\n'; "
               "sleep 1000000; } | _build/default/src/repl_thread.exe",
    },
    {
        "id": "evo",
        "glyph": "Evolve",
        "portlabel": ":8700",
        "title": "Evolution pipeline",
        "desc": "Type a goal, then convert step by step: <b>goal &rarr; .aice &rarr; .ga.json &rarr; .aipl</b>. LLM-assisted, with a dropdown of past experiments.",
        "addr": "127.0.0.1:8700",
        "href": "http://127.0.0.1:8700/",
        "port": 8700,
        "cwd": os.path.join(REPO, "aice-evolution-v2"),
        "cmd": "python3 evolution_dashboard.py",
    },
    {
        "id": "node",
        "glyph": "JS&middot;Node",
        "portlabel": ":8090",
        "title": "JavaScript &mdash; Node server",
        "desc": "AIPL parsed &amp; run inside a Node process (<code>/api/run</code>). Editor + examples (incl. dining philosophers), type-check, console.",
        "addr": "localhost:8090",
        "href": "http://localhost:8090/",
        "port": 8090,
        "cwd": os.path.join(REPO, "src", "node-aipl-server"),
        "cmd": "node server.mjs",
    },
    {
        "id": "web",
        "glyph": "JS&middot;Web",
        "portlabel": ":8765",
        "title": "JavaScript &mdash; in-browser",
        "desc": "No backend interpreter: AIPL runs entirely in the browser. Demos &mdash; philosophers, bounded buffer (visual), rotating threads, cooperative AI chat, drone simulator.",
        "addr": "127.0.0.1:8765",
        "href": "http://127.0.0.1:8765/",
        "port": 8765,
        "cwd": os.path.join(REPO, "src", "browser-abcl"),
        "cmd": "python3 -m http.server 8765 --bind 127.0.0.1",
    },
    {
        "id": "genai",
        "glyph": "GenAI",
        "portlabel": ":7861",
        "title": "Local Generative AI",
        "desc": "Local LLM chat (Ollama: gemma3 / llama3.2 / gemma2), linked from the JS&middot;Web in-browser page. Runs entirely on this machine via the local Ollama API &mdash; no external network call.",
        "addr": "127.0.0.1:7861",
        "href": "http://127.0.0.1:7861/",
        "port": 7861,
        "cwd": REPO,
        "cmd": "local-genai/.venv/bin/python local-genai/ollama_chat.py",
    },
    {
        "id": "c",
        "glyph": "C",
        "portlabel": ":8095",
        "title": "C &mdash; native + multi-target",
        "desc": "AIPL &rarr; C &rarr; compiled native binary, showing generated source and stdout. Target selector: C / Erlang / Prolog / Go / Pony / Python / LLVM / OpenMP / Xinu.",
        "addr": "127.0.0.1:8095",
        "href": "http://127.0.0.1:8095/",
        "port": 8095,
        "cwd": REPO,
        "cmd": "dune build && python3 src/c_dashboard.py",
    },
]
TARGET_BY_ID = {t["id"]: t for t in TARGETS}

# id -> Popen for processes this portal launched (so we can stop them)
_PROCS: dict[str, subprocess.Popen] = {}


def _is_up(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.25)
        return s.connect_ex((host, port)) == 0


def _status() -> dict:
    out = {}
    for t in TARGETS:
        proc = _PROCS.get(t["id"])
        ours = proc is not None and proc.poll() is None
        out[t["id"]] = {"up": _is_up(t["port"]), "ours": ours}
    return out


def _start(tid: str) -> dict:
    t = TARGET_BY_ID.get(tid)
    if t is None:
        return {"ok": False, "error": "unknown target"}
    if _is_up(t["port"]):
        return {"ok": True, "already": True}
    logpath = f"/tmp/aice_{tid}.log"
    log = open(logpath, "ab")
    proc = subprocess.Popen(
        t["cmd"], shell=True, cwd=t["cwd"],
        stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    _PROCS[tid] = proc
    return {"ok": True, "pid": proc.pid, "log": logpath}


def _stop(tid: str) -> dict:
    proc = _PROCS.get(tid)
    if proc is None or proc.poll() is not None:
        return {"ok": False, "error": "not started by this portal — stop it manually"}
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    return {"ok": True}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(json.dumps(obj).encode("utf-8"), "application/json", code)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(_PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/status":
            self._json(_status())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        u = urlparse(self.path)
        tid = (parse_qs(u.query).get("target") or [""])[0]
        if u.path == "/api/start":
            self._json(_start(tid))
        elif u.path == "/api/stop":
            self._json(_stop(tid))
        elif u.path == "/api/shutdown":
            # Self-terminate the portal itself.  Used by the top-level
            # aios-claude/index.html Stop button.  We answer the HTTP
            # request first, then exit on a tiny background thread so
            # the browser sees a 200 instead of a connection-reset.
            import threading, time as _time, os as _os
            self._json({"ok": True, "shutting_down": True})
            def _bye():
                _time.sleep(0.2)
                _os._exit(0)
            threading.Thread(target=_bye, daemon=True).start()
        else:
            self.send_response(404)
            self.end_headers()


def _render_cards() -> str:
    out = []
    for t in TARGETS:
        out.append(f"""
  <div class="card" data-id="{t['id']}">
   <div class="thumb"><span class="glyph">{t['glyph']}</span><span class="port">{t['portlabel']}</span>
    <span class="status" data-status><span class="led"></span><span class="txt">…</span></span></div>
   <span class="arrow">&#8599;</span>
   <div class="body"><h3>{t['title']}</h3>
    <p>{t['desc']}</p>
    <span class="addr">{t['addr']}</span>
    <div class="controls">
     <button class="btn btn-start" data-start>Start</button>
     <button class="btn btn-stop" data-stop>Stop</button>
     <button class="btn btn-open" data-href="{t['href']}">Open &#8599;</button>
    </div></div>
  </div>""")
    return "".join(out)


_PAGE_TMPL = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AICE — AIPL Runtime Portal</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Noto+Sans+JP:wght@300;400;500;700&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
 :root{
  --bg-0:#fff; --surface:#fff; --surface-soft:#f7f9fd;
  --border:rgba(0,63,140,.14); --border-strong:rgba(0,63,140,.28);
  --text:#16223a; --text-dim:#4a5a78; --text-mute:#7c89a3;
  --primary:#003f8c; --primary-strong:#002a66; --primary-soft:#e6eef9;
  --accent:#f08300; --accent-strong:#d97200; --accent-soft:#fff1de;
  --grad:linear-gradient(135deg,#003f8c 0%,#2a6ec3 55%,#f08300 100%);
  --grad-soft:linear-gradient(135deg,rgba(0,63,140,.10) 0%,rgba(240,131,0,.10) 100%);
  --shadow-1:0 1px 2px rgba(15,30,60,.04),0 8px 24px rgba(15,30,60,.06);
  --radius:16px; --radius-lg:22px;
 }
 *{box-sizing:border-box} html,body{margin:0;padding:0}
 body{font-family:'Inter','Noto Sans JP',system-ui,-apple-system,sans-serif;color:var(--text);
  background:var(--bg-0);line-height:1.6;overflow-x:hidden;min-height:100vh;position:relative}
 .orb{position:fixed;border-radius:50%;filter:blur(70px);opacity:.5;z-index:-2;pointer-events:none}
 .orb.b{width:520px;height:520px;top:-160px;left:-120px;background:radial-gradient(circle,#003f8c 0%,transparent 60%)}
 .orb.o{width:480px;height:480px;bottom:-180px;right:-120px;background:radial-gradient(circle,#f08300 0%,transparent 60%)}
 .grid-overlay{position:fixed;inset:0;z-index:-1;pointer-events:none;opacity:.5;
  background-image:linear-gradient(rgba(0,63,140,.04) 1px,transparent 1px),linear-gradient(90deg,rgba(0,63,140,.04) 1px,transparent 1px);
  background-size:64px 64px}
 a{color:inherit;text-decoration:none}
 .container{max-width:1180px;margin:0 auto;padding:0 24px}
 header{position:sticky;top:0;z-index:10;backdrop-filter:blur(12px);
  background:rgba(255,255,255,.82);border-bottom:1px solid var(--border)}
 .barwrap{max-width:1180px;margin:0 auto;padding:14px 24px;display:flex;align-items:center;gap:14px}
 .brand{display:flex;align-items:center;gap:10px;font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:20px}
 .brand .dot{width:11px;height:11px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 4px var(--accent-soft)}
 .grad-text{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}
 .brand small{font-weight:500;font-size:12px;color:var(--text-mute);font-family:'Inter',sans-serif}
 .navlink{margin-left:auto;font-size:13px;color:var(--text-dim)}
 .navlink a{padding:6px 12px;border-radius:9px;border:1px solid var(--border)}
 .navlink a:hover{border-color:var(--accent);color:var(--accent-strong)}
 .hero{text-align:center;padding:60px 24px 30px;max-width:1180px;margin:0 auto}
 .eyebrow{display:inline-flex;align-items:center;gap:8px;font-family:'Space Grotesk',sans-serif;
  font-size:12.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent-strong);
  background:var(--accent-soft);border:1px solid rgba(240,131,0,.25);padding:6px 14px;border-radius:999px}
 .eyebrow .pulse{width:8px;height:8px;border-radius:50%;background:var(--accent);animation:pulse 1.8s infinite}
 @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(240,131,0,.5)}70%{box-shadow:0 0 0 8px rgba(240,131,0,0)}100%{box-shadow:0 0 0 0 rgba(240,131,0,0)}}
 .hero h1{font-family:'Space Grotesk',sans-serif;font-size:clamp(2.1rem,5vw,3.4rem);font-weight:700;
  letter-spacing:-.02em;margin:18px 0 10px;line-height:1.08}
 .hero p{max-width:680px;margin:0 auto;color:var(--text-dim);font-size:16px}
 .pills{display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin-top:18px}
 .pill{font-size:12.5px;color:var(--primary);background:var(--primary-soft);border:1px solid var(--border);
  padding:5px 12px;border-radius:999px}
 section{padding:30px 0}
 .sec-head{display:flex;align-items:baseline;gap:14px;margin-bottom:22px}
 .sec-head h2{font-family:'Space Grotesk',sans-serif;font-size:clamp(1.3rem,2.4vw,1.8rem);font-weight:600;
  margin:0;color:var(--primary);position:relative;padding-left:14px}
 .sec-head h2::before{content:'';position:absolute;left:0;top:50%;transform:translateY(-50%);
  width:4px;height:70%;background:var(--accent);border-radius:2px}
 .sec-head .ribbon{flex:1;height:1px;background:linear-gradient(to right,var(--border-strong),transparent)}
 .sec-head .num{font-family:'Space Grotesk',sans-serif;font-size:13px;color:var(--accent);font-weight:600;letter-spacing:.1em}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:18px}
 .card{position:relative;display:flex;flex-direction:column;border-radius:var(--radius);background:var(--surface);
  border:1px solid var(--border);overflow:hidden;transition:all .35s cubic-bezier(.2,.8,.2,1);box-shadow:var(--shadow-1)}
 .card::before{content:'';position:absolute;inset:0;border-radius:inherit;padding:1.5px;background:var(--grad);
  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;opacity:0;transition:opacity .35s;pointer-events:none}
 .card:hover{transform:translateY(-4px);border-color:transparent;box-shadow:0 18px 40px rgba(0,63,140,.18),0 0 0 1px rgba(240,131,0,.22)}
 .card:hover::before{opacity:1}
 .thumb{aspect-ratio:16/7;display:flex;align-items:center;justify-content:center;position:relative;
  background:var(--grad-soft);border-bottom:1px solid var(--border)}
 .thumb .glyph{font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:30px;letter-spacing:.02em;
  background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}
 .thumb .port{position:absolute;left:12px;bottom:10px;font-family:'Space Grotesk',monospace;font-size:12px;
  color:var(--primary-strong);background:rgba(255,255,255,.7);border:1px solid var(--border);padding:2px 8px;border-radius:7px}
 .thumb .status{position:absolute;right:12px;bottom:10px;display:flex;align-items:center;gap:6px;
  font-family:'Space Grotesk',monospace;font-size:11px;color:var(--text-mute);
  background:rgba(255,255,255,.7);border:1px solid var(--border);padding:2px 8px;border-radius:7px}
 .status .led{width:8px;height:8px;border-radius:50%;background:#c2ccdb;transition:all .3s}
 .status.up{color:#1c9c55}
 .status.up .led{background:#1faa59;box-shadow:0 0 0 3px rgba(31,170,89,.18)}
 .arrow{position:absolute;top:12px;right:12px;width:30px;height:30px;border-radius:50%;background:var(--accent);
  border:1px solid var(--accent-strong);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;
  opacity:0;transform:scale(.8);transition:all .3s;z-index:2}
 .card:hover .arrow{opacity:1;transform:scale(1)}
 .body{padding:15px 18px 18px;display:flex;flex-direction:column;gap:6px}
 .body h3{margin:0;font-size:16px;font-weight:600;color:var(--text)}
 .body p{margin:0;font-size:13px;color:var(--text-dim)}
 .body .addr{margin-top:4px;font-family:'Space Grotesk',monospace;font-size:12px;color:var(--accent-strong)}
 .controls{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
 .btn{font-family:'Inter',sans-serif;font-size:12.5px;font-weight:600;cursor:pointer;
  padding:7px 14px;border-radius:9px;border:1px solid var(--border);background:var(--surface);
  color:var(--text);transition:all .2s}
 .btn:hover{border-color:var(--accent);color:var(--accent-strong)}
 .btn:disabled{opacity:.45;cursor:not-allowed}
 .btn-start{background:var(--primary);color:#fff;border-color:var(--primary-strong)}
 .btn-start:hover:not(:disabled){background:var(--primary-strong);color:#fff}
 .linkcard .body{flex:1;justify-content:center}
 .btn-open{margin-left:auto;background:var(--accent);color:#fff;border-color:var(--accent-strong)}
 .btn-open:hover:not(:disabled){background:var(--accent-strong);color:#fff}
 .note{background:var(--surface-soft);border:1px solid var(--border);border-radius:var(--radius);
  padding:14px 18px;color:var(--text-dim);font-size:13px}
 .note code{background:var(--primary-soft);color:var(--primary-strong);padding:1px 6px;border-radius:6px;font-size:12px}
 .runtimes{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}
 .rt{border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;background:var(--surface)}
 .rt h4{margin:0 0 4px;font-size:14px;color:var(--primary)}
 .rt p{margin:0;font-size:12.5px;color:var(--text-dim)}
 footer{margin-top:40px;border-top:1px solid var(--border);background:var(--surface-soft)}
 .footwrap{max-width:1180px;margin:0 auto;padding:22px 24px;color:var(--text-mute);font-size:12.5px;
  display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px}
</style>
</head>
<body>
<div class="orb b"></div><div class="orb o"></div><div class="grid-overlay"></div>

<header>
 <div class="barwrap">
  <div class="brand"><span class="dot"></span><span class="grad-text">AICE</span>
   <small>AI&middot;Coevolution &mdash; AIPL Runtime Portal</small></div>
  <div class="navlink"><a href="#robot">Robot</a> <a href="#xinu">Xinu</a> <a href="#dashboards">Dashboards</a></div>
 </div>
</header>

<div class="hero">
 <span class="eyebrow"><span class="pulse"></span>Hosei &mdash; Kodama Lab</span>
 <h1>Welcome to <span class="grad-text">AICE</span></h1>
 <p>An actor-based concurrent language (AIPL) realised across many runtimes, with an
    evolutionary pipeline that designs the language itself: <b>goal &rarr; .aice &rarr; .ga.json &rarr; .aipl</b>.</p>
 <div class="pills">
  <span class="pill">AIPL actors</span><span class="pill">5 runtimes</span>
  <span class="pill">MAP-Elites evolution</span><span class="pill">AIPL &rarr; C / Erlang / Prolog / Go &hellip;</span>
 </div>
</div>

<section class="container" id="robot">
 <div class="sec-head"><h2>Robot</h2><span class="ribbon"></span><span class="num">VIDEO &middot; EDITOR</span></div>
 <div class="grid">
  <a class="card linkcard" target="_blank" rel="noopener" href="https://lecture.site44.com/index-ro03-editor2.html">
   <div class="thumb"><span class="glyph">&#129302;</span><span class="port">site44.com</span></div>
   <span class="arrow">&#8599;</span>
   <div class="body"><h3>ロボット動画 &mdash; Robot editor</h3>
    <p>Block-based robot programming &amp; video lecture, hosted at lecture.site44.com. Opens in a new tab.</p>
    <span class="addr">lecture.site44.com/index-ro03-editor2.html</span></div>
  </a>
 </div>
</section>

<section class="container" id="xinu">
 <div class="sec-head"><h2>Xinu (bare-metal Pi 4)</h2><span class="ribbon"></span><span class="num">LAYOUT &middot; SHELL</span></div>
 <!-- Both Xinu pages are sub-routes of the Py-I dashboard (port 8900),
      so Start/Stop targets the same `pyi` process — clicking Stop on
      either card stops the underlying Py-I, and Start launches it. -->
 <div class="grid">
  <div class="card" data-id="pyi">
   <div class="thumb"><span class="glyph">&#128736;</span><span class="port">:8900/layout</span>
    <span class="status" data-status><span class="led"></span><span class="txt">…</span></span></div>
   <span class="arrow">&#8599;</span>
   <div class="body"><h3>Xinu 設定画面 &mdash; Window layout designer</h3>
    <p>Drag/resize the wm-window rectangles over a scaled view of the Pi 4 virtual desktop, then 送信 &mdash; the dashboard generates an AIPL program of <code>remote_now</code> move/resize calls and applies them. Needs Py&middot;I running.</p>
    <span class="addr">127.0.0.1:8900/layout</span>
    <div class="controls">
     <button class="btn btn-start" data-start>Start</button>
     <button class="btn btn-stop" data-stop>Stop</button>
     <button class="btn btn-open" data-href="http://127.0.0.1:8900/layout">Open &#8599;</button>
    </div></div>
  </div>
  <div class="card" data-id="pyi">
   <div class="thumb"><span class="glyph">&#9000;</span><span class="port">:8900/shell</span>
    <span class="status" data-status><span class="led"></span><span class="txt">…</span></span></div>
   <span class="arrow">&#8599;</span>
   <div class="body"><h3>Xinu Shell &mdash; type into the running kernel</h3>
    <p>Send keyboard text and special keys (Enter / Esc / arrows for history / Ctrl-C / Ctrl-U &hellip;) plus mouse-delta clicks to the bare-metal Pi 4&rsquo;s <code>Shell (UART)</code> wm-window over HTTP. CORS sidestepped via the Py&middot;I server-side proxy.</p>
    <span class="addr">127.0.0.1:8900/shell</span>
    <div class="controls">
     <button class="btn btn-start" data-start>Start</button>
     <button class="btn btn-stop" data-stop>Stop</button>
     <button class="btn btn-open" data-href="http://127.0.0.1:8900/shell">Open &#8599;</button>
    </div></div>
  </div>
 </div>
</section>

<section class="container" id="dashboards">
 <div class="sec-head"><h2>Dashboards</h2><span class="ribbon"></span><span class="num">START &middot; STOP &middot; OPEN</span></div>
 <div class="grid">
<!--CARDS-->
 </div>
</section>

<section class="container">
 <div class="sec-head"><h2>Runtimes</h2><span class="ribbon"></span><span class="num">ONE LANGUAGE, MANY BACKENDS</span></div>
 <div class="runtimes">
  <div class="rt"><h4>Py-I</h4><p>Python reference interpreter with the live --dashboard.</p></div>
  <div class="rt"><h4>OCaml</h4><p>Canonical runtime; embedded web gateway + aipl2c transpiler.</p></div>
  <div class="rt"><h4>JS (Node)</h4><p>browser-abcl runtime hosted in Node, served over HTTP.</p></div>
  <div class="rt"><h4>JS (browser)</h4><p>Same runtime, executing client-side in the page.</p></div>
  <div class="rt"><h4>C</h4><p>AIPL &rarr; C via aipl2c, linked with abcl_nextgen_runtime.</p></div>
  <div class="rt"><h4>Transpile</h4><p>Erlang / Prolog / Go / Pony / Python / LLVM / OpenMP / Xinu source.</p></div>
 </div>
 <div class="note" style="margin-top:18px">
  各カードの <b>Start</b> ボタンでローカル開発サーバを起動できます（このポータルが起動コマンドを実行します）。
  緑の LED は稼働中、灰色は停止中。<b>Stop</b> はこのポータルが起動したプロセスのみ停止できます。
  OCaml / C は初回に <code>dune build</code> が走るため起動までに少し時間がかかります。
  手動の起動コマンド・ポート一覧は <code>docs/DASHBOARDS_NEXT_SESSION.md</code> を参照。
 </div>
</section>

<footer>
 <div class="footwrap">
  <span>AICE &mdash; AIPL multi-runtime portal &middot; Kodama Lab, Hosei University</span>
  <span>Copyright &copy; 2000&ndash;2026 &middot; styled after kodama-lab.com</span>
 </div>
</footer>

<script>
async function refresh(){
  let s={};
  try{ s = await (await fetch('/api/status')).json(); }catch(e){ return; }
  document.querySelectorAll('.card').forEach(card=>{
    const st = s[card.dataset.id] || {};
    const badge = card.querySelector('[data-status]');
    badge.classList.toggle('up', !!st.up);
    badge.querySelector('.txt').textContent = st.up ? 'running' : 'stopped';
    const start = card.querySelector('[data-start]');
    const stop  = card.querySelector('[data-stop]');
    if(start.dataset.busy!=='1'){ start.disabled = !!st.up; start.textContent = 'Start'; }
    stop.disabled = !st.ours;
  });
}
document.addEventListener('click', async (e)=>{
  const card = e.target.closest('.card'); if(!card) return;
  const id = card.dataset.id;
  if(e.target.matches('[data-href]')){ window.open(e.target.dataset.href,'_blank'); return; }
  if(e.target.matches('[data-start]')){
    const b=e.target; b.dataset.busy='1'; b.disabled=true; b.textContent='Starting…';
    try{ await fetch('/api/start?target='+encodeURIComponent(id),{method:'POST'}); }catch(err){}
    let n=0; const iv=setInterval(()=>{ refresh(); if(++n>=10){ clearInterval(iv); b.dataset.busy='0'; refresh(); } }, 1200);
    return;
  }
  if(e.target.matches('[data-stop]')){
    e.target.disabled=true;
    try{ await fetch('/api/stop?target='+encodeURIComponent(id),{method:'POST'}); }catch(err){}
    setTimeout(refresh, 700);
  }
});
refresh(); setInterval(refresh, 4000);
</script>
</body>
</html>
"""

_PAGE = _PAGE_TMPL.replace("<!--CARDS-->", _render_cards())


def start(port: int = 8888):
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    print(f"[aice-home] http://127.0.0.1:{port}/")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    start(int(os.environ.get("AICE_HOME_PORT", "8888")))
