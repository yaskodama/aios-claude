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
        methods[k] = `(${ps}) -> ${ret}`;
      }
      result.classes[c] = { fields, methods };
    }
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
<html><head><meta charset="utf-8"><title>AIPL Node Server</title></head>
<body style="font-family:sans-serif;max-width:60em;margin:2em auto;">
<h1>AIPL Node.js server</h1>
<p>The Node sibling of the OCaml <code>web_gateway</code>.
Hosts the AIPL parser, flow-sensitive type checker, and interpreter
inside a single Node process.</p>
<h2>Endpoints</h2>
<ul>
<li><code>POST /api/typecheck</code> — body <code>{source}</code> returns
 inferred classes + errors</li>
<li><code>POST /api/run</code> — body <code>{source, timeoutMs?, typecheck?}</code>
 executes and returns stdout</li>
</ul>
<p>Try:
<pre>
curl -X POST -H 'Content-Type: application/json' \\
  -d '{"source":"class C{var x=0;method tick(){x=x+1;}}"}' \\
  http://localhost:${PORT}/api/typecheck
</pre></p>
</body></html>`;

function send(res, code, ctype, body) {
  res.writeHead(code, { "Content-Type": ctype });
  res.end(body);
}

const server = createServer(async (req, res) => {
  try {
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

    send(res, 404, "text/plain", "not found");
  } catch (e) {
    send(res, 500, "application/json",
         JSON.stringify({ ok:false, errors:[String(e.message||e)] }));
  }
});

server.listen(PORT, () => {
  process.stdout.write(`AIPL Node server listening on http://localhost:${PORT}/\n`);
});
