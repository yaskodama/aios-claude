// manet_fire_dash.js — 第6章 火災シナリオ (OCaml AIPL Fire アクター) のビューア。
// 地図は「東京都荒川区の実道路網(OpenStreetMap由来 arakawa_map266.json)」を、
// 実際の OSM 地図タイル画像の上に貼り付けて描画する(図6.1(A)(B) の形)。
// 動的状態(@FSTATE: 避難者・火災・計測)は /api/log ポーリング、tick は send 駆動。
(() => {
  const $ = (id) => document.getElementById(id);
  const cv = $("cv"), ctx = cv.getContext("2d");
  const W = 800, H = 625, Z = 17;

  let MAP = null;    // {verts:[[x,y]], edges:[[a,b]], safe:[...], bbox:[S,Wd,N,E]}
  let bg = null;     // 背景タイルを合成したオフスクリーン
  let useSys = 1, cursor = 0, timer = null;
  let st = null;

  const lon2gx = (lon) => (lon + 180) / 360 * Math.pow(2, Z) * 256;
  const lat2gy = (lat) => {
    const r = lat * Math.PI / 180;
    return (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * Math.pow(2, Z) * 256;
  };

  // OSM タイルを bbox に合わせて合成し、背景キャンバスを作る
  function buildBackground() {
    const [S, Wd, N, E] = MAP.bbox;
    const gx0 = lon2gx(Wd), gx1 = lon2gx(E), gy0 = lat2gy(N), gy1 = lat2gy(S);
    const tx0 = Math.floor(gx0 / 256), tx1 = Math.floor(gx1 / 256);
    const ty0 = Math.floor(gy0 / 256), ty1 = Math.floor(gy1 / 256);
    bg = document.createElement("canvas"); bg.width = W; bg.height = H;
    const bx = bg.getContext("2d");
    bx.fillStyle = "#0a0e14"; bx.fillRect(0, 0, W, H);
    const sx = W / (gx1 - gx0), sy = H / (gy1 - gy0);
    for (let tx = tx0; tx <= tx1; tx++) for (let ty = ty0; ty <= ty1; ty++) {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        const dx = (tx * 256 - gx0) * sx, dy = (ty * 256 - gy0) * sy;
        bx.drawImage(img, dx, dy, 256 * sx, 256 * sy);
        draw();
      };
      img.src = `https://tile.openstreetmap.org/${Z}/${tx}/${ty}.png`;
    }
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    if (bg) { ctx.globalAlpha = 0.85; ctx.drawImage(bg, 0, 0); ctx.globalAlpha = 1; }
    if (!MAP) return;
    const V = MAP.verts;
    // 道路(辺) — 図6.1(A) の赤い線
    ctx.strokeStyle = "rgba(220,60,60,.75)"; ctx.lineWidth = 2;
    MAP.edges.forEach(([a, b]) => {
      ctx.beginPath(); ctx.moveTo(V[a][0], V[a][1]); ctx.lineTo(V[b][0], V[b][1]); ctx.stroke();
    });
    // 頂点 — 図6.1(A) の青い円
    ctx.fillStyle = "rgba(80,150,255,.9)";
    V.forEach((v) => { ctx.beginPath(); ctx.arc(v[0], v[1], 2.5, 0, 7); ctx.fill(); });
    // 火災(通行不能点) — 図6.1(B) の赤い炎
    if (st) st.fire.forEach(([v, known]) => {
      const p = V[v]; if (!p) return;
      ctx.fillStyle = known ? "#ff4d3d" : "#c23a26";
      ctx.beginPath(); ctx.arc(p[0], p[1], 6, 0, 7); ctx.fill();
      ctx.fillStyle = "#fff2cc"; ctx.font = "9px sans-serif"; ctx.fillText("火", p[0] - 4.5, p[1] + 3.2);
    });
    // 避難所 — 図6.1(A) の赤い円(4つ)
    MAP.safe.forEach((si) => {
      const p = V[si]; if (!p) return;
      ctx.fillStyle = "#ff5a5a"; ctx.strokeStyle = "#fff"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(p[0], p[1], 10, 0, 7); ctx.fill(); ctx.stroke();
      ctx.fillStyle = "#fff"; ctx.font = "11px sans-serif"; ctx.fillText("避", p[0] - 5.5, p[1] + 4);
    });
    // 避難者 — 図6.1(B) の人型(移動中=橙 / 到達=緑 / 死亡=灰)
    if (st) st.evac.forEach((e) => {
      ctx.fillStyle = e[2] === 1 ? "#22c55e" : (e[2] === 2 ? "#8b949e" : "#ff9500");
      ctx.beginPath(); ctx.arc(e[0], e[1], 4, 0, 7); ctx.fill();
    });
  }

  function metrics() {
    if (!st) return;
    $("mCon").textContent = st.contacts; $("mDie").textContent = st.deaths;
    $("mArr").textContent = st.arrived + " / " + st.N;
    $("mBar").style.width = (st.N ? 100 * st.arrived / st.N : 0) + "%";
    $("mFire").textContent = st.fires; $("mT").textContent = Math.round(st.t);
  }

  function parseState(line) {
    const parts = line.split("#");
    const f = parts[0].split(";");
    const s = { t: +f[1], N: +f[2], arrived: +f[3], deaths: +f[4],
                contacts: +f[5], fires: +f[6], use: +f[7], evac: [], fire: [] };
    for (let i = 8; i < f.length; i++) {
      const e = f[i]; if (!e || e.indexOf(",") < 0) continue;
      const p = e.split(","); s.evac.push([parseFloat(p[0]), parseFloat(p[1]), parseInt(p[2])]);
    }
    if (parts[1]) parts[1].split(",").forEach((x) => {
      if (x.indexOf(":") < 0) return;
      const ab = x.split(":"); s.fire.push([parseInt(ab[0]), parseInt(ab[1])]);
    });
    return s;
  }

  async function send(m, a) {
    try {
      await fetch("/api/json/send", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ to: "fire", method: m, args: a || [], unsafe: true }) });
    } catch (e) {}
  }
  async function logSince(a) { return (await fetch("/api/log?after=" + a)).json(); }

  async function poll() {
    await send("tick", []);
    const j = await logSince(cursor); cursor = j.next;
    (j.lines || []).forEach((ln) => { if (ln.startsWith("@FSTATE")) st = parseState(ln); });
    draw(); metrics();
  }

  async function start() {
    const n = parseInt($("nRange").value);
    const j0 = await logSince(0); cursor = j0.next; st = null;
    await send("setup", [n, useSys]);
    $("status").textContent = "地図読込・経路計算中 ...";
    await new Promise((r) => setTimeout(r, 3200));   // 実地図 setup + 距離場計算を待つ
    await send("start", []);
    $("status").textContent = (useSys ? "システム利用" : "不使用") + ": " + n + " 避難者 稼働中";
    $("bStart").disabled = true; $("bStop").disabled = false;
    if (timer) clearInterval(timer);
    timer = setInterval(poll, 160);
  }
  async function stop() {
    if (timer) { clearInterval(timer); timer = null; }
    await send("stop", []);
    $("status").textContent = "一時停止"; $("bStart").disabled = false; $("bStop").disabled = true;
  }

  // ---- 4エージェントのソース表示 ----
  const AGENTS = [
    { cls: "InfoAgent", name: "① 情報エージェント (info)", tag: "static", role:
      "端末の頭脳。通行不能点(火災)の発見/学習、移動エージェントの派遣、既知の通行不能点を避ける避難経路の再構成を司る。" },
    { cls: "NodeManager", name: "② ノード管理エージェント (nodemgr)", tag: "static", role:
      "端末が『共有可能』として公開する通行不能点テーブルを保持。隣端末から来た収集エージェントはここを読みに来る。" },
    { cls: "DiffusionAgent", name: "③ 情報拡散エージェント (diffusion)", tag: "mobile", role:
      "push型。通行不能点IDを載せて電波内(50m)の隣端末へ1ホップ移動し、着いた先の情報エージェントへ預ける(図6.2はhop1)。" },
    { cls: "CollectingAgent", name: "④ 情報収集エージェント (collecting)", tag: "mobile", role:
      "pull型。隣端末のノード管理エージェントを巡回訪問し、未知の通行不能点IDを持ち帰って自端末へ取り込む。" },
  ];
  function extractClass(src, name) {
    const i = src.indexOf("class " + name);
    if (i < 0) return "(見つかりません)";
    const b = src.indexOf("{", i); let depth = 0, j = b;
    for (; j < src.length; j++) {
      if (src[j] === "{") depth++;
      else if (src[j] === "}") { depth--; if (depth === 0) { j++; break; } }
    }
    return src.slice(i, j);
  }
  let agentSrc = null;
  async function showAgents() {
    const grid = $("agGrid");
    if (!agentSrc) {
      try { agentSrc = await (await fetch("/phone_node_fire.abcl")).text(); }
      catch (e) { agentSrc = ""; }
    }
    grid.innerHTML = "";
    AGENTS.forEach((a) => {
      const code = agentSrc ? extractClass(agentSrc, a.cls) : "(取得失敗)";
      const div = document.createElement("div"); div.className = "ag";
      const tagname = a.tag === "static" ? "静的(常駐)" : "移動";
      div.innerHTML = `<h3>${a.name}<span class="tag ${a.tag}">${tagname}</span></h3>`
        + `<p>${a.role}</p><pre></pre>`;
      div.querySelector("pre").textContent = code;
      grid.appendChild(div);
    });
    $("agModal").classList.add("on");
  }
  $("bAgents").onclick = showAgents;
  $("agClose").onclick = () => $("agModal").classList.remove("on");
  $("agModal").onclick = (e) => { if (e.target.id === "agModal") $("agModal").classList.remove("on"); };

  $("bStart").onclick = start;
  $("bStop").onclick = stop;
  $("nRange").oninput = (e) => $("nVal").textContent = e.target.value;
  $("mUse").onclick = () => { useSys = 1; $("mUse").classList.add("on"); $("mNo").classList.remove("on"); };
  $("mNo").onclick  = () => { useSys = 0; $("mNo").classList.add("on"); $("mUse").classList.remove("on"); };

  fetch("/arakawa_map266.json").then((r) => r.json()).then((m) => {
    MAP = m; buildBackground(); draw();
    $("status").textContent = "地図読込完了(荒川区 " + m.verts.length + "頂点/" + m.safe.length + "避難所)。▶スタート";
  }).catch((e) => { $("status").textContent = "地図読込失敗: " + e; });
  draw();
})();
