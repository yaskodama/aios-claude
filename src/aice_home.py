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
        "id": "manet",
        "glyph": "MANET",
        "portlabel": ":8090",
        "title": "避難支援 MANET &mdash; soft-Xinu (荒川区)",
        "desc": "多賀(2021) 第4章の 4エージェント (info / nodemgr / diffusion / collecting) &times; soft-Xinu 避難支援シミュレータ。第6章 大規模火災シナリオの<b>実地図(東京都荒川区・約800&times;625m)</b>を OpenStreetMap から再現。避難者=1 soft-Xinu ノード、native <code>now remote(...)</code> で端末間を移動。道路網・避難所・危険地域・避難者を可視化。",
        "addr": "localhost:8090",
        "href": "http://localhost:8090/",
        "port": 8090,
        "cwd": os.path.join(os.path.expanduser("~"), "projects", "drone-taga", "aipl_xinu_sim"),
        "cmd": "python3 manet_aipl_sim.py",
    },
    {
        "id": "manet2",
        "glyph": "MANET(2)",
        "portlabel": ":8097/fire",
        "title": "避難支援 MANET(2) &mdash; OCaml AIPL 火災シナリオ",
        "desc": "多賀(2021) <b>第6章 大規模火災シナリオ</b>を <b>OCaml版 AIPL(型推論クリーン)</b> で再現。荒川区の実道路網(OpenStreetMap)<b>266頂点・4避難所</b>。各避難者=1台の soft-Xinu(4エージェント)。最寄り避難所へ最短経路で避難し、通行不能点(火災)を回避。<b>MANET メッシュ</b>のリンクと、火災発見時の<b>情報拡散ブロードキャスト(50m)</b>を可視化。図6.2/6.4 の傾向を再現。",
        "addr": "localhost:8097/fire",
        "href": "http://localhost:8097/fire",
        "port": 8097,
        "cwd": REPO,
        "cmd": "( printf 'load %s\\ncompile\\n'; tail -f /dev/null ) | ./_build/default/src/repl_thread.exe"
               % os.path.join(os.path.expanduser("~"), "projects", "drone-taga",
                              "aipl_xinu_sim", "ocaml", "manet_fire.abcl"),
    },
    {
        "id": "ns3",
        "glyph": "ns-3",
        "portlabel": ":8098",
        "title": "MANET + ドローン中継 可視化 (ns-3 検証)",
        "desc": "<b>ns-3</b> で検証した多賀論文の避難支援シナリオのブラウザ可視化（単体HTML・依存なし）。避難者の MANET・情報到達率・<b>ドローン中継</b>による改善を，道路網・通信リンク・ドローン軌道とともにアニメーション表示。ns-3 C++ 実装は <code>drone-manet-evacuation.cc</code> / <code>coupled-evacuation.cc</code> 等。",
        "addr": "localhost:8098/simulation.html",
        "href": "http://localhost:8098/simulation.html",
        "port": 8098,
        "cwd": os.path.join(os.path.expanduser("~"), "projects", "drone-taga"),
        "cmd": "python3 -m http.server 8098 --bind 127.0.0.1",
    },
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
        "id": "phil5",
        "glyph": "5&phi;",
        "portlabel": ":8901/actors",
        "title": "Py-I &mdash; 5 Dining Philosophers",
        "desc": "Five philosophers as Python actor threads, laid out in a pentagon and coloured by state (think / hungry / eat); forks are drawn as arrows pointing at whoever holds them. Ordered fork acquisition &rarr; deadlock-free.",
        "addr": "127.0.0.1:8901/actors",
        "href": "http://127.0.0.1:8901/actors",
        "port": 8901,
        "cwd": REPO,
        "cmd": "python3 philosophers5_web.py 8901",
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
        "portlabel": ":8091",
        "title": "JavaScript &mdash; Node server",
        "desc": "AIPL parsed &amp; run inside a Node process (<code>/api/run</code>). Editor + examples (incl. dining philosophers), type-check, console.",
        "addr": "localhost:8091",
        "href": "http://localhost:8091/",
        "port": 8091,
        "cwd": os.path.join(REPO, "src", "node-aipl-server"),
        "cmd": "PORT=8091 node server.mjs",
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
    {
        "id": "pi5des",
        "glyph": "Pi5",
        "portlabel": ":8901",
        "title": "Pi5 Xinu screen designer",
        "desc": "Drag/resize the 6 wm-windows over a scaled 1920x1080 Pi 5 desktop, then 送信 — geometry is shipped to the bare-metal Pi 5 over its 3-pin debug UART (no network). Select Shell + type to send keystrokes.",
        "addr": "127.0.0.1:8901",
        "href": "http://127.0.0.1:8901/",
        "port": 8901,
        "cwd": REPO,
        "cmd": "python3 src/pi5_screen_designer.py",
    },
    {
        "id": "milky",
        "glyph": "Milky",
        "portlabel": ":8030",
        "title": "Milky Character Studio",
        "desc": "Procedurally-generated cyborg-gal characters (MAKINA-7 / CHIHARU-3 / NAVI-bot / PROF-K) in a Blender-style in-browser 3D editor: Orbit/Transform gizmo, Outliner, Properties, shading, idle/walk/run/dance animation, glTF export.",
        "addr": "127.0.0.1:8030/index.html",
        "href": "http://127.0.0.1:8030/index.html",
        "port": 8030,
        "cwd": os.path.join(os.path.expanduser("~"), "projects", "milky-character"),
        "cmd": "python3 -m http.server 8030 --bind 127.0.0.1",
    },
    {
        "id": "rover",
        "glyph": "Rover",
        "portlabel": ":8020/rover.html",
        "title": "Robot arm &amp; rover &mdash; Xinu/AIPL motor control",
        "desc": "6-axis robot arm (7 environments + end-effector PiP camera) and a 4-wheel visual-navigation litter-collecting rover, each joint/wheel a separate Xinu node driven by AIPL messages over a soft-Xinu (Py-I) server. Opens the rover page.",
        "addr": "127.0.0.1:8020/rover.html",
        "href": "http://127.0.0.1:8020/rover.html",
        "port": 8020,
        "cwd": os.path.join(os.path.expanduser("~"), "projects", "robot-arm"),
        "cmd": "python3 soft_xinu.py",
    },
    {
        "id": "mecharm",
        "glyph": "mecharm",
        "portlabel": ":8021/mecharm_sim.html",
        "title": "mecharm 6軸アーム &mdash; 分散Xinu制御 + TinyML 強化学習",
        "desc": "実機 elephant robotics <b>mecharm</b> 相当の6軸アームを疑似3Dで可視化。<b>各関節に2台の soft-Xinu(計12)</b>を接続し、<b>Capability推論</b>で役割を分離(<code>Motor!{mut,net}</code> / <code>Sensor!{net}</code> / <code>Learner!{ai,net}</code>)。アプリ層の <b>TinyML方策(強化学習済)</b> がコンベア上の部品を把持→組付けする滑らかな動作を生成。Sensor→Learner→Motor の情報経路と、駆動中の Xinu を実時間ハイライト。",
        "addr": "127.0.0.1:8021/mecharm_sim.html",
        "href": "http://127.0.0.1:8021/mecharm_sim.html",
        "port": 8021,
        "cwd": os.path.join(REPO, "mecharm_rl"),
        "cmd": "python3 -m http.server 8021 --bind 127.0.0.1",
    },
    {
        "id": "dofbot",
        "glyph": "DOFBOT",
        "portlabel": ":8022/index.html",
        "title": "Yahboom DOFBOT 6軸アーム &mdash; 12 Xinu + Capability推論 + Pick&amp;Place",
        "desc": "実機 <b>Yahboom DOFBOT</b>(6DOF/Raspberry Pi 5)を Three.js で忠実に3D再現(黒シャーシ+青バスサーボ+手首カメラ+2指グリッパ)。<b>各サーボ ID1..ID6 に soft-Xinu 2台=計12</b>を接続し、<b>効果注釈は書かず</b>メソッド本体から <b>Capability推論</b>で役割を導出(<code>ServoMotor!{mut,net}</code> / <code>ServoSensor!{net}</code> / <code>Planner!{net}</code> / <code>Camera!{ai,net}</code>)。実機API <code>Arm_serial_servo_write/read</code> で駆動し、<b>掴む→回転→離す</b>の Pick&amp;Place を再現。カードクリックで各アクターの AIPL ソースを閲覧。",
        "addr": "127.0.0.1:8022/index.html",
        "href": "http://127.0.0.1:8022/index.html",
        "port": 8022,
        "cwd": os.path.join(os.path.expanduser("~"), "aipl_line_simulator"),
        "cmd": "python3 -m http.server 8022 --bind 127.0.0.1",
    },
]
TARGET_BY_ID = {t["id"]: t for t in TARGETS}

# Targets shown in their own section above, not in the generic Dashboards grid.
_ROBOT_IDS = {"milky", "rover", "mecharm", "dofbot"}

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
        elif path == "/aipl":
            try:
                with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "aipl_intro.html"), "rb") as f:
                    self._send(f.read(), "text/html; charset=utf-8")
            except OSError:
                self.send_response(404); self.end_headers()
        elif path in ("/tinyml_aipl_xinu_guide.pdf", "/AICE_Meta_Research.pdf"):
            try:
                with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       path.lstrip("/")), "rb") as f:
                    self._send(f.read(), "application/pdf")
            except OSError:
                self.send_response(404); self.end_headers()
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
        if t["id"] in _ROBOT_IDS:
            continue
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
  <div class="navlink"><a href="#robot">Robot</a> <a href="#xinu">Xinu&middot;Pi4</a> <a href="#xinu3">Xinu&middot;Pi3</a> <a href="#dashboards">Dashboards</a></div>
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
 <p style="margin-top:20px">
  <a href="/aipl" style="display:inline-flex;align-items:center;gap:9px;text-decoration:none;
     font-family:'Space Grotesk',ui-monospace,monospace;font-weight:700;font-size:15px;color:#0C0E14;
     background:linear-gradient(92deg,#5EEAD4,#818CF8);border-radius:10px;padding:11px 20px;
     box-shadow:0 10px 30px rgba(94,234,212,.25)">&#128218; AIPL とは — 言語の詳細解説 &rarr;</a>
 </p>
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
  <div class="card" data-id="milky">
   <div class="thumb"><span class="glyph">&#128118;&#10024;</span><span class="port">:8030</span>
    <span class="status" data-status><span class="led"></span><span class="txt">…</span></span></div>
   <span class="arrow">&#8599;</span>
   <div class="body"><h3>Milky Character Studio &mdash; 3D character editor</h3>
    <p>Procedurally-generated cyborg-gal characters (MAKINA-7 / CHIHARU-3 / NAVI-bot / PROF-K) in a Blender-style in-browser 3D editor: Orbit/Transform gizmo, Outliner, Properties, shading, idle/walk/run/dance animation, and glTF export.</p>
    <span class="addr">127.0.0.1:8030/index.html</span>
    <div class="controls">
     <button class="btn btn-start" data-start>Start</button>
     <button class="btn btn-stop" data-stop>Stop</button>
     <button class="btn btn-open" data-href="http://127.0.0.1:8030/index.html">Open &#8599;</button>
    </div></div>
  </div>
  <div class="card" data-id="rover">
   <div class="thumb"><span class="glyph">&#129302;&#128663;</span><span class="port">:8020/rover.html</span>
    <span class="status" data-status><span class="led"></span><span class="txt">…</span></span></div>
   <span class="arrow">&#8599;</span>
   <div class="body"><h3>Robot arm &amp; rover &mdash; Xinu/AIPL motor control</h3>
    <p>6-axis robot arm (7 environments + end-effector PiP camera) and a 4-wheel visual-navigation litter-collecting rover, each joint/wheel a separate Xinu node driven by AIPL messages over a soft-Xinu (Py&middot;I) server. Opens the rover page.</p>
    <span class="addr">127.0.0.1:8020/rover.html</span>
    <div class="controls">
     <button class="btn btn-start" data-start>Start</button>
     <button class="btn btn-stop" data-stop>Stop</button>
     <button class="btn btn-open" data-href="http://127.0.0.1:8020/rover.html">Open &#8599;</button>
    </div></div>
  </div>
  <div class="card" data-id="mecharm">
   <div class="thumb"><span class="glyph">&#129693;</span><span class="port">:8021/mecharm_sim.html</span>
    <span class="status" data-status><span class="led"></span><span class="txt">…</span></span></div>
   <span class="arrow">&#8599;</span>
   <div class="body"><h3>mecharm 6軸アーム &mdash; 分散Xinu制御 + TinyML 強化学習</h3>
    <p>実機 elephant robotics <b>mecharm</b> 相当の6軸アームを疑似3Dで可視化。<b>各関節に2台の soft-Xinu(計12)</b>を接続し、<b>Capability推論</b>で役割を分離(<code>Motor!{mut,net}</code> / <code>Sensor!{net}</code> / <code>Learner!{ai,net}</code>)。アプリ層の <b>TinyML方策(強化学習済)</b> がコンベア上の部品を把持→組付けする滑らかな動作を生成する製造ライン組立シミュレーション。</p>
    <span class="addr">127.0.0.1:8021/mecharm_sim.html</span>
    <div class="controls">
     <button class="btn btn-start" data-start>Start</button>
     <button class="btn btn-stop" data-stop>Stop</button>
     <button class="btn btn-open" data-href="http://127.0.0.1:8021/mecharm_sim.html">Open &#8599;</button>
    </div></div>
  </div>
  <div class="card" data-id="dofbot">
   <div class="thumb"><span class="glyph">&#129302;</span><span class="port">:8022/index.html</span>
    <span class="status" data-status><span class="led"></span><span class="txt">…</span></span></div>
   <span class="arrow">&#8599;</span>
   <div class="body"><h3>Yahboom DOFBOT 6軸アーム &mdash; 12 Xinu + Capability推論 + Pick&amp;Place</h3>
    <p>実機 <b>Yahboom DOFBOT</b>(6DOF/Raspberry Pi 5)を Three.js で忠実に3D再現。<b>各サーボ ID1..ID6 に soft-Xinu 2台=計12</b>を接続し、メソッド本体から <b>Capability推論</b>で役割を導出(<code>ServoMotor!{mut,net}</code> / <code>ServoSensor!{net}</code> / <code>Planner!{net}</code>)。実機API <code>Arm_serial_servo_write/read</code> で駆動し、掴む→回転→離す の Pick&amp;Place を再現。</p>
    <span class="addr">127.0.0.1:8022/index.html</span>
    <div class="controls">
     <button class="btn btn-start" data-start>Start</button>
     <button class="btn btn-stop" data-stop>Stop</button>
     <button class="btn btn-open" data-href="http://127.0.0.1:8022/index.html">Open &#8599;</button>
    </div></div>
  </div>
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

<section class="container" id="xinu5">
 <div class="sec-head"><h2>Xinu (bare-metal Pi 5)</h2><span class="ribbon"></span><span class="num">SERIAL &middot; LAYOUT &middot; SHELL</span></div>
 <!-- The Pi 5 has no working network (BCM2712 GENET/RP1 unbrought-up, GIC
      unreachable with the MMU off), so this designer drives the kernel over
      the 3-pin DEBUG UART via the Mac's USB-serial adapter — its own
      server on :8901 (data-id "pi5des"), not a Py-I sub-route. -->
 <div class="grid">
  <div class="card" data-id="pi5des">
   <div class="thumb"><span class="glyph">&#128421;</span><span class="port">:8901</span>
    <span class="status" data-status><span class="led"></span><span class="txt">…</span></span></div>
   <span class="arrow">&#8599;</span>
   <div class="body"><h3>Pi5 Xinu 画面設計 &mdash; Window layout designer (serial)</h3>
    <p>Drag/resize the 6 wm-windows (banner / System status / VFS tree / Memory / Shell / Soft keyboard) over a scaled 1920&times;1080 view of the Pi 5 HDMI desktop, then 送信 &mdash; the geometry is shipped to the bare-metal Pi 5 over its 3-pin <code>debug UART</code> (0x107D001000) via the Mac&rsquo;s USB-serial adapter, and <code>serial_io_tick</code> in the kernel repositions the live windows. <b>Select a window (yellow), pick Shell, then type to send keystrokes into that window.</b> Needs the debug-UART adapter plugged into the Mac.</p>
    <span class="addr">127.0.0.1:8901</span>
    <div class="controls">
     <button class="btn btn-start" data-start>Start</button>
     <button class="btn btn-stop" data-stop>Stop</button>
     <button class="btn btn-open" data-href="http://127.0.0.1:8901/">Open &#8599;</button>
    </div></div>
  </div>
 </div>
</section>

<section class="container" id="xinu3">
 <div class="sec-head"><h2>Xinu (bare-metal Pi 3)</h2><span class="ribbon"></span><span class="num">WIFI &middot; FRAMEBUFFER</span></div>
 <!-- Pi 3 page is a sub-route of the Py-I dashboard (port 8900), so Start/Stop
      targets the same `pyi` process.  The Pi 3 (192.168.3.50) must be WiFi-
      connected + DHCP'd for 送信 to draw on its HDMI screen. -->
 <div class="grid">
  <div class="card" data-id="pyi">
   <div class="thumb"><span class="glyph">&#128421;</span><span class="port">:8899/pi3</span>
    <span class="status" data-status><span class="led"></span><span class="txt">…</span></span></div>
   <span class="arrow">&#8599;</span>
   <div class="body"><h3>Pi3 Xinu 画面設計 &mdash; Framebuffer browser layout</h3>
    <p>Drag/resize the browser window over a scaled 1024&times;768 view of the Pi 3 HDMI screen, set a URL, then 送信 &mdash; the page forwards the geometry to the Pi 3&rsquo;s <code>/api/wifi/browse</code> so the bare-metal kernel fetches the page (plain HTTP, e.g. http://kodamay.org) over its self-built WiFi/TCP stack and draws it as a window. Needs Py&middot;I running + the Pi 3 connected.</p>
    <span class="addr">127.0.0.1:8899/pi3</span>
    <div class="controls">
     <button class="btn btn-start" data-start>Start</button>
     <button class="btn btn-stop" data-stop>Stop</button>
     <button class="btn btn-open" data-href="http://127.0.0.1:8899/pi3">Open &#8599;</button>
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
