"""AICE home — a portal page (kodama-lab.com style) linking to every AIPL
runtime dashboard / server built in this project.

Run:
    python3 src/aice_home.py            # serves http://127.0.0.1:8888/
"""

from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            body = _PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


def start(port: int = 8888):
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    print(f"[aice-home] http://127.0.0.1:{port}/")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


_PAGE = r"""<!doctype html>
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
 .card .cover{position:absolute;inset:0;z-index:3}
 .thumb{aspect-ratio:16/7;display:flex;align-items:center;justify-content:center;position:relative;
  background:var(--grad-soft);border-bottom:1px solid var(--border)}
 .thumb .glyph{font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:30px;letter-spacing:.02em;
  background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}
 .thumb .port{position:absolute;left:12px;bottom:10px;font-family:'Space Grotesk',monospace;font-size:12px;
  color:var(--primary-strong);background:rgba(255,255,255,.7);border:1px solid var(--border);padding:2px 8px;border-radius:7px}
 .arrow{position:absolute;top:12px;right:12px;width:30px;height:30px;border-radius:50%;background:var(--accent);
  border:1px solid var(--accent-strong);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;
  opacity:0;transform:scale(.8);transition:all .3s;z-index:2}
 .card:hover .arrow{opacity:1;transform:scale(1)}
 .body{padding:15px 18px 18px;display:flex;flex-direction:column;gap:6px}
 .body h3{margin:0;font-size:16px;font-weight:600;color:var(--text)}
 .body p{margin:0;font-size:13px;color:var(--text-dim)}
 .body .addr{margin-top:4px;font-family:'Space Grotesk',monospace;font-size:12px;color:var(--accent-strong)}
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
  <div class="navlink"><a href="#dashboards">Dashboards</a></div>
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

<section class="container" id="dashboards">
 <div class="sec-head"><h2>Dashboards</h2><span class="ribbon"></span><span class="num">RUNNING SERVERS</span></div>
 <div class="grid">

  <div class="card">
   <a class="cover" target="_blank" href="http://127.0.0.1:8899/actors" aria-label="Py-I dashboard"></a>
   <div class="thumb"><span class="glyph">Py&middot;I</span><span class="port">:8899/actors</span></div>
   <span class="arrow">&#8599;</span>
   <div class="body"><h3>Py-I &mdash; Python runtime</h3>
    <p>Actor dashboard: dining philosophers, bounded buffer (capacity 20 + live speed sliders), token ring. Live actor table, console, ring/buffer visualization.</p>
    <span class="addr">127.0.0.1:8899/actors</span></div>
  </div>

  <div class="card">
   <a class="cover" target="_blank" href="http://localhost:8080/dashboard" aria-label="OCaml gateway dashboard"></a>
   <div class="thumb"><span class="glyph">OCaml</span><span class="port">:8080/dashboard</span></div>
   <span class="arrow">&#8599;</span>
   <div class="body"><h3>OCaml &mdash; web gateway</h3>
    <p>Reference runtime. Program selector (philosophers / bounded buffer + speed sliders / ping-pong / counter / hello), actor table, console, buffer viz, and source view.</p>
    <span class="addr">localhost:8080/dashboard</span></div>
  </div>

  <div class="card">
   <a class="cover" target="_blank" href="http://127.0.0.1:8700/" aria-label="Evolution pipeline"></a>
   <div class="thumb"><span class="glyph">Evolve</span><span class="port">:8700</span></div>
   <span class="arrow">&#8599;</span>
   <div class="body"><h3>Evolution pipeline</h3>
    <p>Type a goal, then convert step by step: <b>goal &rarr; .aice &rarr; .ga.json &rarr; .aipl</b>. LLM-assisted, with a dropdown of past experiments.</p>
    <span class="addr">127.0.0.1:8700</span></div>
  </div>

  <div class="card">
   <a class="cover" target="_blank" href="http://localhost:8090/" aria-label="JS Node server"></a>
   <div class="thumb"><span class="glyph">JS&middot;Node</span><span class="port">:8090</span></div>
   <span class="arrow">&#8599;</span>
   <div class="body"><h3>JavaScript &mdash; Node server</h3>
    <p>AIPL parsed &amp; run inside a Node process (<code>/api/run</code>). Editor + examples (incl. dining philosophers), type-check, console.</p>
    <span class="addr">localhost:8090</span></div>
  </div>

  <div class="card">
   <a class="cover" target="_blank" href="http://127.0.0.1:8765/" aria-label="JS browser runtime"></a>
   <div class="thumb"><span class="glyph">JS&middot;Web</span><span class="port">:8765</span></div>
   <span class="arrow">&#8599;</span>
   <div class="body"><h3>JavaScript &mdash; in-browser</h3>
    <p>No backend interpreter: AIPL runs entirely in the browser. Demos &mdash; philosophers, bounded buffer (visual), rotating threads, cooperative AI chat, drone simulator.</p>
    <span class="addr">127.0.0.1:8765</span></div>
  </div>

  <div class="card">
   <a class="cover" target="_blank" href="http://127.0.0.1:8095/" aria-label="C runtime dashboard"></a>
   <div class="thumb"><span class="glyph">C</span><span class="port">:8095</span></div>
   <span class="arrow">&#8599;</span>
   <div class="body"><h3>C &mdash; native + multi-target</h3>
    <p>AIPL &rarr; C &rarr; compiled native binary, showing generated source and stdout. Target selector: C / Erlang / Prolog / Go / Pony / Python / LLVM / OpenMP / Xinu.</p>
    <span class="addr">127.0.0.1:8095</span></div>
  </div>

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
  これらはローカル開発サーバです。リンクが開かない場合は、対象のダッシュボードを起動してください
  &mdash; 起動コマンド・ポート一覧は <code>docs/DASHBOARDS_NEXT_SESSION.md</code> を参照。
 </div>
</section>

<footer>
 <div class="footwrap">
  <span>AICE &mdash; AIPL multi-runtime portal &middot; Kodama Lab, Hosei University</span>
  <span>Copyright &copy; 2000&ndash;2026 &middot; styled after kodama-lab.com</span>
 </div>
</footer>
</body>
</html>
"""

if __name__ == "__main__":
    start(int(os.environ.get("AICE_HOME_PORT", "8888")))
