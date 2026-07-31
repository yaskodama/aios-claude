"""C-runtime dashboard for AIPL (stdlib HTTP server).

Pick or edit an AIPL program, then:
  * Translate -> C : run aipl2c to show the generated C source.
  * Build & Run    : translate -> cc (link abcl_nextgen_runtime.c) -> run the
                     native binary -> show the generated C *and* its stdout.

This is the C-language sibling of the Py-I / OCaml / JS dashboards: here the
"engine" is the AIPL->C translator plus a real C compiler.

Run:
    python3 src/c_dashboard.py            # serves http://127.0.0.1:8095/
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SRC  = Path(__file__).resolve().parent          # .../src
REPO = SRC.parent                               # repo root
AIPL2C   = REPO / "_build" / "default" / "src" / "aipl2c.exe"
RUNTIME_C = SRC / "abcl_nextgen_runtime.c"
WORK = REPO / "out" / "c_dashboard"
CC = os.environ.get("CC", "cc")

RUN_TIMEOUT = 10        # seconds for the compiled binary
CC_TIMEOUT  = 40        # seconds for the C compile


# ---------------------------------------------------------------------------
# Targets: key -> (aipl2c flag, output file extension, syntax label).  "c" is
# the default backend (no flag) and the only one we also compile + run.
TARGETS = {
    "c":      ("",          "c",    "C"),
    "erlang": ("--erlang",  "erl",  "Erlang"),
    "prolog": ("--prolog",  "pl",   "Prolog"),
    "go":     ("--go",      "go",   "Go"),
    "pony":   ("--pony",    "pony", "Pony"),
    "python": ("--python",  "py",   "Python"),
    "llvm":   ("--llvm",    "ll",   "LLVM (C + build notes)"),
    "openmp": ("--openmp",  "c",    "OpenMP (C)"),
    "xinu":   ("--xinu",    "c",    "Xinu (C)"),
}


# ---------------------------------------------------------------------------
# Pipeline

def translate(source: str, target: str, max_msgs: int, typecheck: bool) -> dict:
    if target not in TARGETS:
        return {"ok": False, "src": "", "log": f"unknown target: {target}"}
    flag, ext, label = TARGETS[target]
    WORK.mkdir(parents=True, exist_ok=True)
    abcl = WORK / "prog.aipl"
    out = WORK / f"prog.{ext}"
    abcl.write_text(source, encoding="utf-8")
    if out.exists():
        out.unlink()
    args = [str(AIPL2C), str(abcl), "--max-msgs", str(max_msgs), "-o", str(out)]
    if flag:
        args.append(flag)
    if not typecheck:
        args.append("--no-typecheck")
    p = subprocess.run(args, capture_output=True, text=True, timeout=60, cwd=str(REPO))
    log = (p.stdout or "") + (p.stderr or "")
    if not out.exists() or "type errors" in log or "Type error" in log or "Parse error" in log:
        return {"ok": False, "src": "", "lang": label, "target": target,
                "log": log.strip() or "translation failed"}
    return {"ok": True, "src": out.read_text(encoding="utf-8"), "lang": label,
            "target": target, "log": log.strip()}


def build_and_run(source: str, target: str, max_msgs: int, typecheck: bool) -> dict:
    t = translate(source, target, max_msgs, typecheck)
    if not t["ok"]:
        return {"ok": False, "src": "", "stdout": "", "lang": t.get("lang", target),
                "target": target, "log": t["log"], "stage": "translate"}
    # Only the C backend is compiled + executed here; other targets are
    # transpilation outputs we just display (they need their own toolchains).
    if target != "c":
        return {"ok": True, "src": t["src"], "lang": t["lang"], "target": target,
                "log": t["log"], "stage": "translate",
                "stdout": f"[{t['lang']}] source generated. Run is only wired up for the C "
                          f"target on this dashboard; this language's source is shown on the right "
                          f"(compile/run it with its own toolchain)."}
    cpath = WORK / "prog.c"
    binp = WORK / "prog.bin"
    cc = subprocess.run(
        [CC, str(cpath), str(RUNTIME_C), "-I", str(SRC), "-pthread", "-o", str(binp)],
        capture_output=True, text=True, timeout=CC_TIMEOUT, cwd=str(REPO))
    if cc.returncode != 0:
        return {"ok": False, "src": t["src"], "lang": "C", "target": "c", "stdout": "",
                "log": (cc.stderr or cc.stdout or "compile failed").strip(),
                "stage": "compile"}
    try:
        r = subprocess.run([str(binp)], capture_output=True, text=True,
                           timeout=RUN_TIMEOUT, cwd=str(REPO))
        out = (r.stdout or "") + (r.stderr or "")
        return {"ok": True, "src": t["src"], "lang": "C", "target": "c",
                "stdout": out, "log": t["log"], "stage": "run"}
    except subprocess.TimeoutExpired as e:
        partial = (e.stdout or b"")
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        return {"ok": False, "src": t["src"], "lang": "C", "target": "c", "stdout": partial,
                "log": f"binary timed out after {RUN_TIMEOUT}s", "stage": "run"}


# ---------------------------------------------------------------------------
# Examples (verified to translate + compile + run under the C runtime)

EXAMPLES = {
"Dining Philosophers (5, deadlock-free, 3 meals each)": '''\
// Actor refs are typed (var lo: Fork, init(.. l: Fork ..)) so the C
// translator's type checker resolves the sends — the C runtime needs this.
class Fork {
  var holder = 0;
  method acquire(pid) {
    if (holder == 0) { holder = pid; send sender.granted(pid); }
    else { send sender.denied(pid); }
  }
  method release(pid) { if (holder == pid) { holder = 0; } }
}

var f0 = new Fork();
var f1 = new Fork();
var f2 = new Fork();
var f3 = new Fork();
var f4 = new Fork();

class Philosopher {
  var id = 0;
  var lo: Fork = f0;
  var hi: Fork = f0;
  var state = 0;
  var meals = 0;
  var target = 3;
  method init(i, l: Fork, h: Fork) { id = i; lo = l; hi = h; send self.think(); }
  method think() { send lo.acquire(id); }
  method granted(pid) {
    if (state == 0) { state = 1; send hi.acquire(id); }
    else {
      meals = meals + 1;
      print("P" + id + " eats meal " + meals);
      send hi.release(id); send lo.release(id); state = 0;
      if (meals < target) { send self.think(); } else { print("P" + id + " done"); }
    }
  }
  method denied(pid) { if (state == 1) { send lo.release(id); state = 0; } send self.think(); }
}

var p0 = new Philosopher(1, f0, f1);
var p1 = new Philosopher(2, f1, f2);
var p2 = new Philosopher(3, f2, f3);
var p3 = new Philosopher(4, f3, f4);
var p4 = new Philosopher(5, f0, f4);
''',

"Ping-Pong (2 actors, bounded)": '''\
class Ponger {
  method ping(k) { print("ping " + k); send sender.pong(k); }
}
var ponger = new Ponger();
class Pinger {
  var left = 5;
  var p: Ponger = ponger;
  method go() { send p.ping(left); }
  method pong(k) {
    print("pong " + k);
    left = left - 1;
    if (left > 0) { send p.ping(left); }
  }
}
var pinger = new Pinger();
send pinger.go();
''',

"Counter (self-send, prints 1..5)": '''\
class Counter {
  var n = 0;
  method go() {
    n = n + 1;
    print("n=" + n);
    if (n < 5) { send self.go(); }
  }
}
var c = new Counter();
send c.go();
''',

"Hello (init + greet)": '''\
class Hello {
  var n = 0;
  method init(x) { n = x; print("init " + n); }
  method greet() { print("hello, count=" + n); }
}
var h = new Hello(5);
send h.greet();
''',
}


# ---------------------------------------------------------------------------
# HTTP

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _read_json(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        if self.path == "/":
            page = _PAGE.replace("__EXAMPLES_JSON__",
                                 json.dumps(EXAMPLES, ensure_ascii=False))
            self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")

    def do_POST(self):
        try:
            d = self._read_json()
            src = str(d.get("source", ""))
            mm = int(d.get("maxMsgs", 4000) or 4000)
            tc = bool(d.get("typecheck", True))
            target = str(d.get("target", "c"))
            if self.path == "/api/translate":
                self._json(translate(src, target, mm, tc))
            elif self.path == "/api/run":
                self._json(build_and_run(src, target, mm, tc))
            else:
                self._json({"ok": False, "log": "unknown endpoint"}, 404)
        except Exception as e:
            self._json({"ok": False, "log": f"{type(e).__name__}: {e}"}, 200)


def start(port: int = 8095):
    WORK.mkdir(parents=True, exist_ok=True)
    if not AIPL2C.exists():
        print(f"[c-dashboard] WARNING: {AIPL2C} not found — run `dune build` first.")
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    print(f"[c-dashboard] http://127.0.0.1:{port}/   (aipl2c -> cc -> run; work dir {WORK})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AIPL C-runtime Dashboard</title>
<style>
 body{font-family:ui-monospace,Menlo,Consolas,monospace;background:#0b0f14;color:#d8dee9;margin:0;padding:16px;max-width:1100px}
 h2{margin:0 0 4px} h3{margin:14px 0 6px;color:#8fbcbb;font-size:14px}
 .note{color:#7a8a99;font-size:12px}
 .bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:10px 0}
 select,input{font-family:inherit;font-size:13px;padding:5px;background:#11161d;color:#d8dee9;border:1px solid #3b4757;border-radius:5px}
 select{min-width:320px}
 button{font-family:inherit;font-size:13px;padding:7px 14px;background:#1c2530;color:#d8dee9;border:1px solid #3b4757;border-radius:5px;cursor:pointer}
 button:hover{background:#26313e} button.primary{background:#2e4b6e;border-color:#3b6ea5}
 button:disabled{opacity:.5;cursor:default}
 textarea{width:100%;box-sizing:border-box;background:#0b0f14;color:#d8dee9;border:1px solid #2a3340;border-radius:6px;font-family:inherit;font-size:13px;padding:8px;resize:vertical}
 .cols{display:flex;gap:12px;flex-wrap:wrap}
 .col{flex:1;min-width:340px}
 pre{background:#0b0f14;border:1px solid #2a3340;border-radius:6px;padding:8px;max-height:420px;overflow:auto;white-space:pre-wrap;font-size:12px}
 #stdout{color:#40ff80} #cout{color:#cdd6e0}
 #status{font-size:12px} .ok{color:#a3be8c} .err{color:#bf616a}
 label.cb{color:#7a8a99;font-size:12px}
</style>
</head>
<body>
<h2>AIPL &mdash; C-runtime Dashboard</h2>
<div class="note">AIPL is translated to C by <code>aipl2c</code>, compiled with <code>cc</code> against
 <code>abcl_nextgen_runtime.c</code>, and run as a native binary. Pick or edit a program, then
 Translate (see the generated C) or Build &amp; Run (compile + run).</div>

<div class="bar">
 <select id="exsel" onchange="loadExample()"></select>
 <select id="tgt" onchange="onTarget()" title="target language">
  <option value="c">C (compile &amp; run)</option>
  <option value="erlang">Erlang</option>
  <option value="prolog">Prolog</option>
  <option value="go">Go</option>
  <option value="pony">Pony</option>
  <option value="python">Python</option>
  <option value="llvm">LLVM</option>
  <option value="openmp">OpenMP</option>
  <option value="xinu">Xinu</option>
 </select>
 <button id="b_run" class="primary" onclick="run()">&#9654; Build &amp; Run</button>
 <button id="b_tr" onclick="translateOnly()">Translate &rarr; source</button>
 <label class="cb"><input type="checkbox" id="tc" checked> type-check</label>
 <label class="cb">max msgs <input id="mm" type="number" value="4000" min="10" style="width:80px"></label>
 <span id="status"></span>
</div>

<h3>AIPL source</h3>
<textarea id="src" rows="16" spellcheck="false"></textarea>

<div class="cols">
 <div class="col">
  <h3>Program output (stdout)</h3>
  <pre id="stdout">(Build &amp; Run)</pre>
 </div>
 <div class="col">
  <h3 id="srchdr">Generated source</h3>
  <pre id="cout">(Translate or Build &amp; Run)</pre>
 </div>
</div>

<script>
var EXAMPLES = __EXAMPLES_JSON__;
var $ = function(id){ return document.getElementById(id); };
function setStatus(t, cls){ var e=$("status"); e.textContent=t; e.className=cls||""; }
function loadExample(){ var k=$("exsel").value; if (EXAMPLES[k]!==undefined) $("src").value = EXAMPLES[k]; }
function payload(){
  return { source: $("src").value, typecheck: $("tc").checked, target: $("tgt").value,
           maxMsgs: parseInt($("mm").value || "4000", 10) };
}
function onTarget(){
  var isC = $("tgt").value === "c";
  $("b_run").textContent = isC ? "▶ Build & Run" : "▶ Translate (run = C only)";
}
function setSrcHdr(lang){ $("srchdr").textContent = "Generated source" + (lang ? " — " + lang : ""); }
async function post(ep){
  var r = await fetch(ep, { method:"POST", headers:{"Content-Type":"application/json"},
                            body: JSON.stringify(payload()) });
  return await r.json();
}
async function translateOnly(){
  setStatus("translating…"); $("b_tr").disabled = true;
  try {
    var d = await post("/api/translate");
    setSrcHdr(d.lang);
    $("cout").textContent = d.ok ? d.src : ("[translate failed]\n" + (d.log||""));
    setStatus(d.ok ? ("✔ translated to " + (d.lang||"")) : "✘ translate error", d.ok ? "ok" : "err");
  } catch(e){ $("cout").textContent = String(e); setStatus("✘ " + e, "err"); }
  finally { $("b_tr").disabled = false; }
}
async function run(){
  setStatus($("tgt").value === "c" ? "building & running…" : "translating…"); $("b_run").disabled = true;
  try {
    var d = await post("/api/run");
    setSrcHdr(d.lang);
    $("cout").textContent = d.src || "(no source generated)";
    if (d.ok){
      $("stdout").textContent = d.stdout || "(no output)";
      setStatus(d.target === "c" ? "✔ ran (native C binary)" : ("✔ generated " + (d.lang||"") + " source"), "ok");
    } else {
      $("stdout").textContent = "[" + (d.stage||"error") + " failed]\n" + (d.log||"") +
        (d.stdout ? ("\n--- partial stdout ---\n" + d.stdout) : "");
      setStatus("✘ " + (d.stage||"error"), "err");
    }
  } catch(e){ $("stdout").textContent = String(e); setStatus("✘ " + e, "err"); }
  finally { $("b_run").disabled = false; }
}
(function init(){
  var sel = $("exsel"); var keys = Object.keys(EXAMPLES);
  for (var i=0;i<keys.length;i++){
    var o = document.createElement("option"); o.value=keys[i]; o.textContent=keys[i]; sel.appendChild(o);
  }
  loadExample();
})();
</script>
</body></html>
"""

if __name__ == "__main__":
    start(int(os.environ.get("C_DASH_PORT", "8095")))
