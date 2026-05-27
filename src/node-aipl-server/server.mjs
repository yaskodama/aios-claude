#!/usr/bin/env node
// AIPL Node.js HTTP server — a sibling of the OCaml `web_gateway` and
// the static `browser-abcl/` demo, but with the AIPL parser /
// type-checker / interpreter all running inside Node.
//
// Endpoints (mirror the OCaml gateway's JSON shape where they overlap):
//   POST /api/typecheck  { source: "<.abcl>" }
//       => { ok, errors[], warnings[],
//            classes: { <C>: { fields:{}, methods:{} } } }
//   POST /api/run        { source: "<.abcl>",
//                          timeoutMs?: number,
//                          typecheck?: boolean }   // default true; false skips
//       => { ok, stdout, errors[] }
//   GET  /                 — small status page
//   WS   /ws?sid=<id>      — WebSocket endpoint.  Clients can subscribe
//                            to broadcast messages emitted by /run
//                            (each printed line becomes a frame), or
//                            send their own frames which the server
//                            re-broadcasts to all other clients of
//                            the same sid.
//   POST /api/broadcast   { sid: "<id>", message: "..." }
//                            — server-side broadcast trigger.
//
// The server reuses:
//   - `../browser-abcl/src/parser/parser.js`   (jison-generated parser)
//   - `../browser-abcl/src/ast.js`             (AST constructors)
//   - `../browser-abcl/src/typecheck.js`       (flow-sensitive HM-lite)
//   - `../browser-abcl/src/runtime.js`         (interpreter)
//
// Run:
//   node src/node-aipl-server/server.mjs
//   PORT=8090 node src/node-aipl-server/server.mjs

import { createServer } from "node:http";
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { WebSocketServer } from "ws";
import * as fs from "node:fs";
import { spawnSync } from "node:child_process";

// CE-12: optional z3 hook for refinement subset checks.
// Enabled when AIPL_REFINE_Z3=1 *and* the `z3` binary is on PATH.
// The shared typecheck.js calls globalThis.__AIPL_REFINE_CHECK(p_a, p_b)
// expecting boolean "p_a => p_b" decided over the integer vars
// mentioned in either predicate.
if (process.env.AIPL_REFINE_Z3 === "1") {
  globalThis.__AIPL_REFINE_CHECK = (predA, predB) => {
    try {
      const vars = new Set();
      const grep = (p) => { for (const m of String(p).match(/[a-zA-Z_][a-zA-Z0-9_]*/g) || []) vars.add(m); };
      grep(predA); grep(predB);
      const decls = [...vars].map(v => `(declare-const ${v} Int)`).join("\n");
      const q = `${decls}\n(assert ${predA})\n(assert (not ${predB}))\n(check-sat)\n`;
      const r = spawnSync("z3", ["-in"], { input: q, timeout: 800, encoding: "utf8" });
      return r.status === 0 && /^unsat/m.test(r.stdout || "");
    } catch { return false; }
  };
}

const __dirname = dirname(fileURLToPath(import.meta.url));
const BROWSER = resolve(__dirname, "..", "browser-abcl");

// Browser-abcl loads its parser as CommonJS (jison output), AST and
// typecheck as ESM.  We mix and match here.
const require = createRequire(import.meta.url);
const ast       = await import(resolve(BROWSER, "src/ast.js"));
const tc        = await import(resolve(BROWSER, "src/typecheck.js"));
const rt_module = await import(resolve(BROWSER, "src/runtime.js"));
const parser    = require(resolve(BROWSER, "src/parser/parser.js")).parser;
parser.yy = ast;

const PORT = Number(process.env.PORT || 8090);

// ---------------------------------------------------------------------
// JSON request body reader

function readBody(req) {
  return new Promise((res, rej) => {
    let chunks = "";
    req.on("data", (c) => { chunks += c; });
    req.on("end",  () => res(chunks));
    req.on("error", rej);
  });
}

// ---------------------------------------------------------------------
// /api/typecheck handler — mirror the OCaml endpoint's JSON shape

function handleTypecheck(source) {
  const errors = [];
  const warnings = [];
  let result = { ok: false, errors, warnings, classes: {} };

  let tree;
  try {
    tree = parser.parse(source);
  } catch (e) {
    errors.push(`parse error: ${String(e.message || e).split("\n")[0]}`);
    return result;
  }

  try {
    const info = tc.runTypeCheck(tree);
    result.ok = true;
    // Build the per-class field + method type maps from the inferer's
    // returned info.  classFieldTypes and methodSigs match what
    // typecheck.js exposes.
    const cf = info.classFieldTypes || {};
    const ms = info.methodSigs || {};
    const allClasses = new Set([...Object.keys(cf), ...Object.keys(ms)]);
    for (const c of allClasses) {
      const fields = {};
      for (const [k, v] of Object.entries(cf[c] || {})) fields[k] = String(v);
      const methods = {};
      for (const [k, v] of Object.entries(ms[c] || {})) {
        const ps = (v.params || []).map(String).join(", ");
        const ret = String(v.ret || "any");
        const eff = (info.effectsStr && info.effectsStr[c] && info.effectsStr[c][k]) || "pure";
        methods[k] = `(${ps}) -> ${ret} ![${eff}]`;
      }
      result.classes[c] = { fields, methods };
    }
    if (info.effectsStr) result.effects = info.effectsStr;
  } catch (e) {
    result.ok = false;
    errors.push(String(e.message || e).split("\n")[0]);
  }

  return result;
}

// ---------------------------------------------------------------------
// /api/run handler — full execution under Node's event loop

function handleRun(source, opts = {}) {
  const timeoutMs = Number(opts.timeoutMs || 1500);
  const typecheck = opts.typecheck !== false;
  const errors = [];
  const stdoutLines = [];

  let tree;
  try {
    tree = parser.parse(source);
  } catch (e) {
    return {
      ok: false,
      stdout: "",
      errors: [`parse error: ${String(e.message || e).split("\n")[0]}`],
    };
  }

  if (typecheck) {
    try {
      tc.runTypeCheck(tree);
    } catch (e) {
      return {
        ok: false,
        stdout: "",
        errors: [`type error: ${String(e.message || e).split("\n")[0]}`],
      };
    }
  }

  // Capture stdout
  const printer = (s) => stdoutLines.push(String(s));
  const runtime = new rt_module.Runtime(printer);
  // Inject Node's fs so the runtime's read_file / write_file / etc.
  // work — the same runtime.js file is also used in the browser, where
  // fs is unavailable.
  runtime.injectFs(fs);
  runtime.reset();
  for (const cls of tree.classes) runtime.registerClass(cls);
  const topEnv = {};
  for (const st of tree.statements) {
    try {
      runtime.evalStmt(st, topEnv);
    } catch (e) {
      errors.push(`runtime error: ${String(e.message || e).split("\n")[0]}`);
    }
  }

  // Wait for actor mailboxes to drain.  AIPL actors use setTimeout to
  // schedule message delivery, so we yield to the event loop.
  return new Promise((res) => {
    runtime.scheduleAllActors();
    setTimeout(() => {
      res({
        ok: errors.length === 0,
        stdout: stdoutLines.join("\n") + (stdoutLines.length ? "\n" : ""),
        errors,
      });
    }, timeoutMs);
  });
}

// ---------------------------------------------------------------------
// HTTP server

const STATUS_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AIPL Node.js Dashboard</title>
<style>
 body{font-family:ui-monospace,Menlo,Consolas,monospace;background:#0b0f14;color:#d8dee9;margin:0;padding:16px;max-width:920px}
 h2{margin:0 0 4px} h3{margin:14px 0 6px;color:#8fbcbb;font-size:14px}
 .note{color:#7a8a99;font-size:12px}
 .bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:10px 0}
 select{font-family:inherit;font-size:13px;padding:5px;background:#11161d;color:#d8dee9;border:1px solid #3b4757;border-radius:5px;min-width:300px}
 button{font-family:inherit;font-size:13px;padding:7px 14px;background:#1c2530;color:#d8dee9;border:1px solid #3b4757;border-radius:5px;cursor:pointer}
 button:hover{background:#26313e} button.primary{background:#2e4b6e;border-color:#3b6ea5}
 button:disabled{opacity:.5;cursor:default}
 textarea{width:100%;box-sizing:border-box;background:#0b0f14;color:#d8dee9;border:1px solid #2a3340;border-radius:6px;font-family:inherit;font-size:13px;padding:8px;resize:vertical}
 pre{background:#0b0f14;border:1px solid #2a3340;border-radius:6px;padding:8px;max-height:340px;overflow:auto;white-space:pre-wrap}
 #console{color:#40ff80} #status{font-size:12px}
 .ok{color:#a3be8c} .err{color:#bf616a}
</style>
</head>
<body>
<h2>AIPL Node.js &mdash; Dashboard</h2>
<div class="note">The Node sibling of the OCaml <code>web_gateway</code>: the AIPL parser, type checker, and
 interpreter run inside this Node process. Pick or edit a program, then Run (POST <code>/api/run</code>)
 or Type-check (POST <code>/api/typecheck</code>).</div>

<div class="bar">
 <select id="exsel" onchange="loadExample()"></select>
 <button id="b_run" class="primary" onclick="run()">&#9654; Run</button>
 <button id="b_tc" onclick="typecheck()">Type-check</button>
 <span id="status"></span>
</div>

<h3>AIPL source</h3>
<textarea id="src" rows="16" spellcheck="false"></textarea>

<h3>Console &mdash; stdout / errors</h3>
<pre id="console">(run a program)</pre>

<script>
var EXAMPLES = {
  "Dining Philosophers (5, deadlock-free, 3 meals each)":
    "class Fork {\\n  var holder = 0;\\n  method acquire(pid) {\\n    if (holder == 0) { holder = pid; send sender.granted(pid); }\\n    else { send sender.denied(pid); }\\n  }\\n  method release(pid) { if (holder == pid) { holder = 0; } }\\n}\\nclass Philosopher {\\n  var id = 0;\\n  var lo = 0;\\n  var hi = 0;\\n  var state = 0;\\n  var meals = 0;\\n  var target = 3;\\n  method init(i, l, h) { id = i; lo = l; hi = h; send self.think(); }\\n  method think() { send lo.acquire(id); }\\n  method granted(pid) {\\n    if (state == 0) {\\n      state = 1;\\n      send hi.acquire(id);\\n    } else {\\n      meals = meals + 1;\\n      print(\\"P\\" + id + \\" eats (meal \\" + meals + \\")\\");\\n      send hi.release(id);\\n      send lo.release(id);\\n      state = 0;\\n      if (meals < target) { send self.think(); }\\n      else { print(\\"P\\" + id + \\" done after \\" + meals + \\" meals\\"); }\\n    }\\n  }\\n  method denied(pid) {\\n    if (state == 1) { send lo.release(id); state = 0; }\\n    send self.think();\\n  }\\n}\\nvar f0 = new Fork();\\nvar f1 = new Fork();\\nvar f2 = new Fork();\\nvar f3 = new Fork();\\nvar f4 = new Fork();\\nvar p0 = new Philosopher(1, f0, f1);\\nvar p1 = new Philosopher(2, f1, f2);\\nvar p2 = new Philosopher(3, f2, f3);\\nvar p3 = new Philosopher(4, f3, f4);\\nvar p4 = new Philosopher(5, f0, f4);",
  "Counter (self-send, prints 1..5)":
    "class Counter {\\n  var n = 0;\\n  method go() {\\n    n = n + 1;\\n    print(\\"n=\\" + n);\\n    if (n < 5) { send self.go(); }\\n  }\\n}\\nvar c = new Counter();\\nsend c.go();",
  "Ping-Pong (2 actors, bounded)":
    "class Pinger {\\n  var left = 4;\\n  var p = 0;\\n  method bind(x) { p = x; send p.ping(left); }\\n  method pong(k) {\\n    print(\\"pong \\" + k);\\n    left = left - 1;\\n    if (left > 0) { send p.ping(left); }\\n  }\\n}\\nclass Ponger {\\n  method ping(k) { print(\\"ping \\" + k); send sender.pong(k); }\\n}\\nvar pi = new Pinger();\\nvar po = new Ponger();\\nsend pi.bind(po);",
  "Hello (init + greet)":
    "class Hello {\\n  var n = 0;\\n  method init(x) { n = x; print(\\"init \\" + n); }\\n  method greet() { print(\\"hello, count=\\" + n); }\\n}\\nvar h = new Hello(5);\\nsend h.greet();",
  "Empty class + tick":
    "class C {\\n  var x = 0;\\n  method tick() { x = x + 1; }\\n}\\nvar c = new C();\\nsend c.tick();"
};
var $ = function(id){ return document.getElementById(id); };
function setStatus(t, cls){ var e=$("status"); e.textContent=t; e.className=cls||""; }
function loadExample(){
  var k = $("exsel").value;
  if (EXAMPLES[k] !== undefined) $("src").value = EXAMPLES[k];
}
async function post(ep, payload){
  var r = await fetch(ep, { method:"POST", headers:{"Content-Type":"application/json"},
                            body: JSON.stringify(payload) });
  return await r.json();
}
async function run(){
  setStatus("running…"); $("b_run").disabled = true;
  try {
    var d = await post("/api/run", { source: $("src").value, timeoutMs: 8000 });
    var out = "";
    if (d.stdout) out += d.stdout;
    if (d.errors && d.errors.length) out += "\\n[errors]\\n" + d.errors.join("\\n");
    $("console").textContent = out || "(no output)";
    setStatus(d.ok ? "✔ ran" : "✘ error", d.ok ? "ok" : "err");
  } catch(e){ $("console").textContent = String(e); setStatus("✘ " + e, "err"); }
  finally { $("b_run").disabled = false; }
}
async function typecheck(){
  setStatus("type-checking…"); $("b_tc").disabled = true;
  try {
    var d = await post("/api/typecheck", { source: $("src").value });
    $("console").textContent = JSON.stringify(d, null, 2);
    var bad = (d.errors && d.errors.length);
    setStatus(bad ? "✘ type errors" : "✔ type-checked", bad ? "err" : "ok");
  } catch(e){ $("console").textContent = String(e); setStatus("✘ " + e, "err"); }
  finally { $("b_tc").disabled = false; }
}
(function init(){
  var sel = $("exsel"); var keys = Object.keys(EXAMPLES);
  for (var i=0;i<keys.length;i++){
    var o = document.createElement("option"); o.value=keys[i]; o.textContent=keys[i]; sel.appendChild(o);
  }
  loadExample();
})();
</script>
</body></html>`;

function send(res, code, ctype, body) {
  // CORS (Phase 5.4): allow the browser-abcl static server at
  // localhost:3000 to call /api/sheet/* on the AIPL Node server.
  // Wildcard origin is fine for a local dev setup.
  res.writeHead(code, {
    "Content-Type": ctype,
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  });
  res.end(body);
}

const server = createServer(async (req, res) => {
  try {
    if (req.method === "OPTIONS") {
      // CORS preflight — send() already attaches the headers.
      return send(res, 204, "text/plain", "");
    }
    if (req.method === "GET" && req.url === "/") {
      return send(res, 200, "text/html; charset=utf-8", STATUS_HTML);
    }

    if (req.method === "POST" && req.url === "/api/typecheck") {
      const body = await readBody(req);
      let j;
      try { j = JSON.parse(body); }
      catch { return send(res, 400, "application/json",
                          JSON.stringify({ ok:false, errors:["bad JSON"]})); }
      const src = j && typeof j.source === "string" ? j.source : "";
      if (!src) return send(res, 400, "application/json",
                            JSON.stringify({ ok:false,
                                             errors:["missing source"]}));
      const out = handleTypecheck(src);
      return send(res, 200, "application/json", JSON.stringify(out));
    }

    if (req.method === "POST" && req.url === "/api/run") {
      const body = await readBody(req);
      let j;
      try { j = JSON.parse(body); }
      catch { return send(res, 400, "application/json",
                          JSON.stringify({ ok:false, errors:["bad JSON"]})); }
      const src = j && typeof j.source === "string" ? j.source : "";
      if (!src) return send(res, 400, "application/json",
                            JSON.stringify({ ok:false,
                                             errors:["missing source"]}));
      const out = await handleRun(src, {
        timeoutMs: j.timeoutMs,
        typecheck: j.typecheck,
      });
      return send(res, 200, "application/json", JSON.stringify(out));
    }

    // ── Round 5 Phase 5.4: C2 ServerFile ─────────────────────
    //   POST /api/sheet/<id>/save  body {rows, cols, cells: [...]}
    //   GET  /api/sheet/<id>/load
    //   GET  /api/sheet/list
    //
    // CE-11 capability gating: when AIPL_CAP_STRICT=1 and the env
    // var AIPL_CAP_GRANT doesn't contain "fs", we 403 instead of
    // touching the filesystem.
    const sheetMatch = (req.url || "").match(/^\/api\/sheet\/([\w.\-]+)\/(save|load)(?:\?|$)/);
    const listMatch  = (req.url || "") === "/api/sheet/list";
    if (sheetMatch || listMatch) {
      const strict = (process.env.AIPL_CAP_STRICT === "1");
      const caps   = (process.env.AIPL_CAP_GRANT || "fs").split(",").map(s=>s.trim());
      if (strict && !caps.includes("fs")) {
        return send(res, 403, "application/json",
                    JSON.stringify({ ok:false, error:"capability denied: fs" }));
      }
      const dir = process.env.AIPL_SHEET_DIR || "/tmp/aipl_sheets";
      if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

      if (listMatch && req.method === "GET") {
        const ids = fs.readdirSync(dir)
                      .filter(n => n.endsWith(".json"))
                      .map(n => n.slice(0, -5))
                      .sort();
        return send(res, 200, "application/json",
                    JSON.stringify({ ok:true, dir, sheets: ids }));
      }
      if (sheetMatch) {
        const id  = sheetMatch[1];
        const op  = sheetMatch[2];
        const fp  = `${dir}/${id}.json`;

        if (op === "save" && req.method === "POST") {
          const body = await readBody(req);
          let j;
          try { j = JSON.parse(body); }
          catch { return send(res, 400, "application/json",
                              JSON.stringify({ ok:false, error:"bad JSON" })); }
          const payload = {
            id,
            rows: Number(j.rows || 3),
            cols: Number(j.cols || 3),
            cells: Array.isArray(j.cells) ? j.cells : [],
            // C5: persist per-cell LWW state so reload preserves
            // convergence after concurrent edits.
            clocks:  Array.isArray(j.clocks)  ? j.clocks  : [],
            lamport: Number(j.lamport || 0),
            saved_at: new Date().toISOString(),
          };
          fs.writeFileSync(fp, JSON.stringify(payload, null, 2), "utf8");
          return send(res, 200, "application/json",
                      JSON.stringify({ ok:true, id, cells: payload.cells.length, path: fp }));
        }
        if (op === "load" && req.method === "GET") {
          if (!fs.existsSync(fp)) {
            return send(res, 404, "application/json",
                        JSON.stringify({ ok:false, error:"not found", id }));
          }
          const text = fs.readFileSync(fp, "utf8");
          return send(res, 200, "application/json", text);
        }
      }
    }

    send(res, 404, "text/plain", "not found");
  } catch (e) {
    send(res, 500, "application/json",
         JSON.stringify({ ok:false, errors:[String(e.message||e)] }));
  }
});

// ---------------------------------------------------------------------
// WebSocket endpoint: GET /ws?sid=<id>
//
// Clients connect by URL.  Frames sent by any client of the same sid
// are re-broadcast to all peer clients (including loopback).  Server
// code can also broadcast via POST /api/broadcast or, programmatically,
// by calling broadcast(sid, message).
//
// Mirrors the shape of OCaml's web_gateway ws_clients table.

const wss = new WebSocketServer({ noServer: true });
const wsClientsBySid = new Map();   // sid -> Set<WebSocket>

function broadcast(sid, message) {
  const peers = wsClientsBySid.get(sid);
  if (!peers) return 0;
  let n = 0;
  for (const ws of peers) {
    if (ws.readyState === ws.OPEN) {
      ws.send(message);
      n++;
    }
  }
  return n;
}

wss.on("connection", (ws, request, sid) => {
  if (!wsClientsBySid.has(sid)) wsClientsBySid.set(sid, new Set());
  const set = wsClientsBySid.get(sid);
  set.add(ws);
  ws.send(JSON.stringify({ kind: "welcome", sid, peers: set.size }));

  ws.on("message", (data) => {
    const text = typeof data === "string" ? data : data.toString();
    // Re-broadcast to other peers of this sid.
    for (const peer of set) {
      if (peer !== ws && peer.readyState === peer.OPEN) {
        peer.send(text);
      }
    }
  });

  ws.on("close", () => {
    set.delete(ws);
    if (set.size === 0) wsClientsBySid.delete(sid);
  });
});

server.on("upgrade", (req, socket, head) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  if (url.pathname !== "/ws") {
    socket.write("HTTP/1.1 404 Not Found\r\n\r\n");
    socket.destroy();
    return;
  }
  const sid = url.searchParams.get("sid") || "default";
  wss.handleUpgrade(req, socket, head, (ws) => {
    wss.emit("connection", ws, req, sid);
  });
});

// Add /api/broadcast handler — declare BEFORE listen by patching the
// existing request dispatcher.  We monkey-patch the server's listener.
const _origListeners = server.listeners("request").slice();
server.removeAllListeners("request");
server.on("request", async (req, res) => {
  if (req.method === "POST" && req.url === "/api/broadcast") {
    try {
      const body = await readBody(req);
      const j = JSON.parse(body);
      const sid = j && typeof j.sid === "string" ? j.sid : "default";
      const msg = j && typeof j.message === "string" ? j.message : "";
      if (!msg) return send(res, 400, "application/json",
                           JSON.stringify({ ok:false, errors:["missing message"] }));
      const n = broadcast(sid, msg);
      return send(res, 200, "application/json",
                  JSON.stringify({ ok:true, delivered: n }));
    } catch (e) {
      return send(res, 500, "application/json",
                  JSON.stringify({ ok:false, errors:[String(e.message||e)] }));
    }
  }
  // Forward to original handler.
  for (const l of _origListeners) l(req, res);
});

server.listen(PORT, () => {
  process.stdout.write(`AIPL Node server listening on http://localhost:${PORT}/\n`);
  process.stdout.write(`  WebSocket: ws://localhost:${PORT}/ws?sid=<id>\n`);
});
