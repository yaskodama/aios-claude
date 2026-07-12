// manet_dashboard.js — 避難支援MANET (OCaml AIPL/World アクター) のビューア。
// 同一オリジン(gateway 8096)。tick を POST で駆動し、print("@STATE ...") を
// GET /api/log で読み取って canvas に描画する。
(() => {
  const $ = (id) => document.getElementById(id);
  const cv = $("cv"), ctx = cv.getContext("2d");
  const W = 800, H = 625;

  let cursor = 0;         // /api/log の読み取り位置
  let timer = null;
  let map = null;         // {verts:[[x,y]], edges:[[a,b]], safe:[i,j]}
  let state = null;       // {t,N,inf,hop,dng, nodes:[[x,y,k]]}
  let range = 60;

  async function send(method, args) {
    try {
      await fetch("/api/json/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ to: "world", method, args: args || [], unsafe: true }),
      });
    } catch (e) { /* ignore transient */ }
  }

  async function logSince(after) {
    const r = await fetch("/api/log?after=" + after);
    return await r.json();  // {next, lines:[...]}
  }

  function parseMap(line) {
    const parts = line.split("#");
    const head = parts[0].split(";");   // ["@MAP","800","625",numV,"x,y",...]
    const verts = [];
    for (let i = 4; i < head.length; i++) {
      const s = head[i]; if (!s || s.indexOf(",") < 0) continue;
      const xy = s.split(","); verts.push([parseFloat(xy[0]), parseFloat(xy[1])]);
    }
    const edges = [];
    if (parts[1]) parts[1].split(",").forEach((e) => {
      if (e.indexOf("-") < 0) return;
      const ab = e.split("-"); edges.push([parseInt(ab[0]), parseInt(ab[1])]);
    });
    let safe = [];
    if (parts[2]) safe = parts[2].split(",").map((x) => parseInt(x));
    return { verts, edges, safe };
  }

  function parseState(line) {
    const f = line.split(";");
    // ["@STATE",t,N,inf,hop,dng,"x,y,k",...]
    const st = {
      t: parseFloat(f[1]), N: parseInt(f[2]), inf: parseInt(f[3]),
      hop: parseFloat(f[4]), dng: parseInt(f[5]), nodes: [],
    };
    for (let i = 6; i < f.length; i++) {
      const s = f[i]; if (!s || s.indexOf(",") < 0) continue;
      const p = s.split(",");
      st.nodes.push([parseFloat(p[0]), parseFloat(p[1]), parseInt(p[2])]);
    }
    return st;
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    if (!map) {
      ctx.fillStyle = "#8b949e"; ctx.font = "13px sans-serif";
      ctx.fillText("▶ スタートで開始", 20, 30); return;
    }
    // 道路(辺)
    ctx.strokeStyle = "#26303c"; ctx.lineWidth = 2;
    map.edges.forEach(([a, b]) => {
      const va = map.verts[a], vb = map.verts[b];
      if (!va || !vb) return;
      ctx.beginPath(); ctx.moveTo(va[0], va[1]); ctx.lineTo(vb[0], vb[1]); ctx.stroke();
    });
    // 頂点
    ctx.fillStyle = "#39424e";
    map.verts.forEach((v) => { ctx.beginPath(); ctx.arc(v[0], v[1], 3, 0, 7); ctx.fill(); });
    // 避難所
    ctx.fillStyle = "#58a6ff";
    map.safe.forEach((si) => {
      const v = map.verts[si]; if (!v) return;
      ctx.beginPath(); ctx.arc(v[0], v[1], 9, 0, 7); ctx.fill();
      ctx.fillStyle = "#0a0e14"; ctx.font = "10px sans-serif"; ctx.fillText("避", v[0] - 6, v[1] + 4);
      ctx.fillStyle = "#58a6ff";
    });
    if (!state) return;
    // MANET リンク(電波範囲内のノード対)
    const r2 = range * range, nd = state.nodes;
    ctx.strokeStyle = "rgba(63,185,80,.35)"; ctx.lineWidth = 1;
    for (let i = 0; i < nd.length; i++) {
      for (let j = i + 1; j < nd.length; j++) {
        const dx = nd[i][0] - nd[j][0], dy = nd[i][1] - nd[j][1];
        if (dx * dx + dy * dy <= r2) {
          ctx.beginPath(); ctx.moveTo(nd[i][0], nd[i][1]); ctx.lineTo(nd[j][0], nd[j][1]); ctx.stroke();
        }
      }
    }
    // 避難者
    nd.forEach((p) => {
      ctx.fillStyle = p[2] > 0 ? "#22c55e" : "#f97316";
      ctx.beginPath(); ctx.arc(p[0], p[1], 4, 0, 7); ctx.fill();
    });
  }

  function updateMetrics() {
    if (!state) return;
    $("mInf").textContent = state.inf + " / " + state.N;
    $("mBar").style.width = (state.N ? (100 * state.inf / state.N) : 0) + "%";
    $("mT").textContent = Math.round(state.t);
    $("mHop").textContent = Math.round(state.hop);
    $("mDng").textContent = state.dng;
  }

  async function poll() {
    await send("tick", []);
    const j = await logSince(cursor);
    cursor = j.next;
    (j.lines || []).forEach((ln) => {
      if (ln.startsWith("@MAP")) map = parseMap(ln);
      else if (ln.startsWith("@STATE")) state = parseState(ln);
    });
    draw(); updateMetrics();
  }

  async function start() {
    range = parseInt($("rRange").value);
    const n = parseInt($("nRange").value);
    // 過去ログを読み飛ばす
    const j0 = await logSince(0); cursor = j0.next;
    map = null; state = null;
    await send("setup", [n, range]);
    await send("start", []);
    $("status").textContent = "稼働中: " + n + " ノード soft-World メッシュ";
    $("bStart").disabled = true; $("bStop").disabled = false;
    if (timer) clearInterval(timer);
    timer = setInterval(poll, 180);
  }

  async function stop() {
    if (timer) { clearInterval(timer); timer = null; }
    await send("stop", []);
    $("status").textContent = "一時停止中";
    $("bStart").disabled = false; $("bStop").disabled = true;
  }

  $("bStart").onclick = start;
  $("bStop").onclick = stop;
  $("bDanger").onclick = () => send("discover", []);
  $("nRange").oninput = (e) => $("nVal").textContent = e.target.value;
  $("rRange").oninput = (e) => { $("rVal").textContent = e.target.value; range = parseInt(e.target.value); };
  draw();
})();
