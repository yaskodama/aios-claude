"""Evolution-pipeline dashboard (stdlib HTTP server).

A browser front-end for the three-stage aice-evolution pipeline:

    goal (自然言語)  --[変換]-->  *.aice   --[変換]-->  *.ga.json   --[変換]-->  *.aipl

Stage 1 (goal -> .aice) uses an LLM (aipl_ai.chat_ai) when an AI provider is
configured, and falls back to a known-good template with the goal inserted so
the dashboard always produces a valid .aice.  Stage 2 lowers the .aice to the
.ga.json IR (aice_parser.lower) and stage 3 emits the AIPL program
(aipl_codegen.generate_program).  Each stage also writes the artifact file
under out/dashboard/.

Run:
    cd aice-evolution-v2
    python3 evolution_dashboard.py            # serves http://127.0.0.1:8700/
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent          # aice-evolution-v2/
REPO = BASE.parent                              # abclcp-project/
OUT  = BASE / "out" / "dashboard"

# Make `src` (the pipeline package) and the Py-I AI helper importable.
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(REPO / "src" / "python-aipl"))

from src.aice_parser import parse as aice_parse, lower as aice_lower   # noqa: E402
from src.aipl_codegen import generate_program                          # noqa: E402

TEMPLATE_AICE = BASE / "examples" / "CompilerEvolution.aice"
EXAMPLES_DIR  = BASE / "examples"


def list_examples() -> list:
    """Past-experiment .aice files, for the dashboard's dropdown."""
    return [{"name": f.stem, "file": f.name}
            for f in sorted(EXAMPLES_DIR.glob("*.aice"))]


def example_source(name: str) -> dict:
    """Return the .aice text of a named example (validated against the list
    so it can only read files inside examples/)."""
    valid = {e["name"] for e in list_examples()}
    if name not in valid:
        return {"ok": False, "error": f"unknown example: {name}"}
    text = (EXAMPLES_DIR / f"{name}.aice").read_text(encoding="utf-8")
    return {"ok": True, "name": name, "aice": text}


# ---------------------------------------------------------------------------
# Pipeline steps

def _safe_name(goal: str) -> str:
    """Turn a free-text goal into a valid aice identifier."""
    words = re.findall(r"[A-Za-z0-9]+", goal)
    name = "".join(w.capitalize() for w in words[:4])
    if not name or not name[0].isalpha():
        name = "Goal" + name
    return (name or "GoalEvolution")[:40] + "Evolution"


def _template_aice(goal: str, name: str) -> str:
    """Known-good .aice with the goal substituted — always lowers cleanly."""
    base = TEMPLATE_AICE.read_text(encoding="utf-8")
    base = re.sub(r"aice\s+\w+\s*\{", f"aice {name} {{", base, count=1)
    g = goal.replace('"', "'").replace("\n", " ").strip()
    base = re.sub(r'task\s*=\s*"[^"]*"\s*;',
                  f'task = "{g}";', base, count=1)
    return base


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_]*\n", "", t)
        t = re.sub(r"\n```\s*$", "", t)
    return t.strip()


def goal_to_aice(goal: str) -> dict:
    """Stage 1.  Try the LLM; fall back to the template.  Always returns a
    .aice string that parses + lowers."""
    name = _safe_name(goal)
    template = _template_aice(goal, name)
    used = "template"
    aice = template
    try:
        from aipl_ai import chat_ai
        system = (
            "You write aice-evolution-v2 DSL files (a small C-like config "
            "language). Output ONLY the .aice source — no markdown, no prose. "
            "Keep the exact block structure of the template (dialect, "
            "gene_schema, evaluation_tasks, search, meta_fitness, ranking, "
            "reviewers). Adapt ONLY the aice name, the `task` string, and the "
            "reviewer personas to fit the user's goal. Keep gene_schema, "
            "evaluation_tasks specs, and numeric search/meta_fitness values "
            "unchanged so it stays runnable."
        )
        user = f"Goal:\n{goal}\n\nTemplate to adapt:\n{template}"
        reply = chat_ai([{"role": "user", "content": user}], system=system)
        cand = _strip_fences(reply)
        if cand.lstrip().startswith("aice") and not cand.startswith("[mock]"):
            aice_lower(aice_parse(cand))         # validate it lowers
            aice = cand
            used = "llm"
    except Exception:
        aice = template
        used = "template"
    spec = aice_lower(aice_parse(aice))
    out_name = spec.get("name", name)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{out_name}.aice"
    path.write_text(aice, encoding="utf-8")
    return {"ok": True, "source": "ai" if used == "llm" else "template",
            "name": out_name, "aice": aice, "path": str(path)}


def aice_to_ga(aice_text: str) -> dict:
    """Stage 2.  Lower the .aice to the .ga.json IR."""
    spec = aice_lower(aice_parse(aice_text))
    name = spec.get("name", "program")
    ga = json.dumps(spec, ensure_ascii=False, indent=2)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.ga.json"
    path.write_text(ga, encoding="utf-8")
    return {"ok": True, "name": name, "ga": ga, "path": str(path)}


def ga_to_aipl(ga_text: str) -> dict:
    """Stage 3.  Emit the AIPL program from the .ga.json IR."""
    spec = json.loads(ga_text)
    name = spec.get("name", "program")
    schema_ref = Path(spec["schema_ref"])
    if not schema_ref.is_absolute():
        for c in (BASE / schema_ref, REPO / schema_ref, Path.cwd() / schema_ref):
            if c.exists():
                schema_ref = c
                break
    schema = json.loads(Path(schema_ref).read_text(encoding="utf-8"))
    aipl = generate_program(spec, schema)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.aipl"
    path.write_text(aipl, encoding="utf-8")
    return {"ok": True, "name": name, "aipl": aipl, "path": str(path)}


# ---------------------------------------------------------------------------
# HTTP

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):                  # quiet
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
        from urllib.parse import urlsplit, parse_qs
        parts = urlsplit(self.path)
        if parts.path == "/":
            self._send(200, "text/html; charset=utf-8", _PAGE.encode("utf-8"))
        elif parts.path == "/api/examples":
            self._json({"ok": True, "examples": list_examples()})
        elif parts.path == "/api/example":
            name = (parse_qs(parts.query).get("name", [""])[0])
            self._json(example_source(name))
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")

    def do_POST(self):
        try:
            d = self._read_json()
            if self.path == "/api/goal2aice":
                self._json(goal_to_aice(str(d.get("goal", "")).strip()))
            elif self.path == "/api/aice2ga":
                self._json(aice_to_ga(str(d.get("aice", ""))))
            elif self.path == "/api/ga2aipl":
                self._json(ga_to_aipl(str(d.get("ga", ""))))
            else:
                self._json({"ok": False, "error": "unknown endpoint"}, 404)
        except Exception as e:
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 200)


def start(port: int = 8700):
    OUT.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    print(f"[evo-dashboard] http://127.0.0.1:{port}/   (artifacts -> {OUT})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


_PAGE = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>AICE Evolution Pipeline</title>
<style>
 body{font-family:ui-monospace,Menlo,Consolas,monospace;background:#0b0f14;color:#d8dee9;margin:0;padding:18px;max-width:980px}
 h2{margin:0 0 4px} h3{margin:0 0 6px;color:#8fbcbb;font-size:14px}
 .note{color:#7a8a99;font-size:12px}
 .stage{background:#11161d;border:1px solid #2a3340;border-radius:8px;padding:12px 14px;margin:12px 0}
 .arrow{text-align:center;color:#4c566a;font-size:20px;margin:-4px 0}
 textarea{width:100%;box-sizing:border-box;background:#0b0f14;color:#d8dee9;border:1px solid #2a3340;border-radius:6px;font-family:inherit;font-size:12.5px;padding:8px;resize:vertical}
 button{font-family:inherit;font-size:13px;padding:7px 16px;background:#2e4b6e;color:#e5e9f0;border:1px solid #3b6ea5;border-radius:6px;cursor:pointer;margin-top:8px}
 button:hover{background:#37597f} button:disabled{opacity:.5;cursor:default}
 .meta{color:#7a8a99;font-size:11px;margin-top:6px;min-height:1em}
 .ok{color:#a3be8c} .err{color:#bf616a} .src-ai{color:#88c0d0} .src-template{color:#ebcb8b}
</style>
</head>
<body>
<h2>AICE Evolution Pipeline &mdash; Dashboard</h2>
<div class="note">目標を入力して順に「変換」を押すと <b>goal → *.aice → *.ga.json → *.aipl</b> を生成します。
 各段の枠は編集してから次の変換に渡せます。生成物は <code>out/dashboard/</code> に保存されます。</div>

<div class="stage">
 <h3>1. 目標 (goal)</h3>
 <textarea id="goal" rows="3" placeholder="例: 型安全な並行ストリーム処理言語の設計を進化させたい">型システムが効く並行プログラミング言語の設計を進化させる</textarea>
 <button id="b1" onclick="step('goal2aice','goal','aice',this)">変換 &#9660; .aice を生成</button>
 <div id="m1" class="meta"></div>
</div>
<div class="arrow">&#8595;</div>

<div class="stage">
 <h3>2. *.aice (設計 DSL)</h3>
 <div style="margin:0 0 8px;display:flex;align-items:center;gap:8px">
  <span class="note">以前の実験例から読み込む:</span>
  <select id="exsel" onchange="loadExample()" style="font-family:inherit;font-size:12.5px;padding:5px;background:#0b0f14;color:#d8dee9;border:1px solid #3b4757;border-radius:5px;min-width:300px">
   <option value="">— 例題を選択 —</option>
  </select>
  <span id="exmeta" class="note"></span>
 </div>
 <textarea id="aice" rows="14" placeholder="(目標から「変換」、上の例題プルダウンから読み込み、または直接貼り付け)"></textarea>
 <button id="b2" onclick="step('aice2ga','aice','ga',this)">変換 &#9660; .ga.json を生成</button>
 <div id="m2" class="meta"></div>
</div>
<div class="arrow">&#8595;</div>

<div class="stage">
 <h3>3. *.ga.json (中間 IR)</h3>
 <textarea id="ga" rows="12" placeholder="(上の「変換」で生成、または直接貼り付け)"></textarea>
 <button id="b3" onclick="step('ga2aipl','ga','aipl',this)">変換 &#9660; .aipl を生成</button>
 <div id="m3" class="meta"></div>
</div>
<div class="arrow">&#8595;</div>

<div class="stage">
 <h3>4. *.aipl (実行プログラム)</h3>
 <textarea id="aipl" rows="18" placeholder="(最終生成物)"></textarea>
 <div id="m4" class="meta"></div>
</div>

<script>
const $ = (id) => document.getElementById(id);

async function loadExamples(){
  try {
    const d = await (await fetch("/api/examples")).json();
    if (!d.ok) return;
    const sel = $("exsel");
    for (const e of d.examples){
      const o = document.createElement("option");
      o.value = e.name; o.textContent = e.name;
      sel.appendChild(o);
    }
  } catch(e){}
}

async function loadExample(){
  const name = $("exsel").value;
  if (!name) return;
  $("exmeta").textContent = "読み込み中…";
  try {
    const d = await (await fetch("/api/example?name=" + encodeURIComponent(name))).json();
    if (d.ok){
      $("aice").value = d.aice;
      $("exmeta").innerHTML = '<span class="ok">✔ ' + name + '.aice を読み込みました</span>';
      $("m2").textContent = ""; $("ga").value = ""; $("aipl").value = "";
      $("m3").textContent = ""; $("m4").textContent = "";
    } else {
      $("exmeta").innerHTML = '<span class="err">✘ ' + (d.error||"failed") + '</span>';
    }
  } catch(e){ $("exmeta").innerHTML = '<span class="err">✘ ' + e + '</span>'; }
}

async function step(endpoint, fromId, toId, btn){
  const inText = $(fromId).value;
  const key = endpoint.split("2")[0];        // goal / aice / ga
  const meta = { goal2aice:"m1", aice2ga:"m2", ga2aipl:"m3" }[endpoint];
  const label = btn.textContent;
  btn.disabled = true; btn.textContent = "変換中…";
  $(meta).textContent = "…";
  try {
    const body = {}; body[key] = inText;
    const r = await fetch("/api/" + endpoint, {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify(body)
    });
    const d = await r.json();
    if (d.ok){
      $(toId).value = d.aice || d.ga || d.aipl || "";
      let extra = "";
      if (endpoint === "goal2aice")
        extra = ' <span class="src-' + (d.source||"template") + '">[' + (d.source==="ai"?"LLM 生成":"テンプレート") + ']</span>';
      $(meta).innerHTML = '<span class="ok">✔ ' + (d.name||"") + '</span> → ' + (d.path||"") + extra;
    } else {
      $(meta).innerHTML = '<span class="err">✘ ' + (d.error||"failed") + '</span>';
    }
  } catch(e){
    $(meta).innerHTML = '<span class="err">✘ ' + e + '</span>';
  } finally {
    btn.disabled = false; btn.textContent = label;
  }
}
loadExamples();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.environ.get("EVO_DASH_PORT", "8700"))
    start(port)
