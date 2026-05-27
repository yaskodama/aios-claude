// gateway_dashboard.js — drives the OCaml AIPL web gateway like the Py-I
// dashboard: a selector of example programs, each loaded/compiled through
// /api/repl, with a live actor table (/api/actors) and console (/api/log).

// Curated, self-contained examples (paths are relative to the runtime's cwd
// = the project root).  `start`/`stop` are REPL commands; if `start` is set
// the program waits for it (e.g. philosophers), otherwise it auto-runs on
// compile.  `viz` links to a dedicated visualization page when one exists.
const PROGRAMS = [
  { key:"philosophers", label:"Dining Philosophers (5)",
    file:"src/viz_philosophers.abcl",
    start:"send table.start();", stop:"send table.stop();",
    viz:"/viz_philosophers.html",
    note:"5 philosophers + 5 forks. Load & Run begins dinner; Stop halts. " +
         "The animated ring is the “Open visualization” page." },
  { key:"buffer", label:"Bounded buffer (1 producer / 1 consumer, cap 20)",
    file:"abclc/bounded_buffer20.abcl", canvas:"buffer", cap:20,
    speed:{ producer:"p0", consumer:"c0", pdef:250, cdef:500 },
    note:"Producer/Consumer over a capacity-20 buffer; runs on compile. Drag the " +
         "speed sliders to retune each side live; the buffer fills until " +
         "[BUF] FULL back-pressure (producer faster) or drains to EMPTY (consumer faster)." },
  { key:"pingpong", label:"Ping-Pong (2 actors, 10 rounds)",
    file:"abclc/PingPongDemo.abcl",
    note:"Two actors bounce a token back and forth 10 times (350 ms apart), " +
         "then stop; runs on compile." },
  { key:"counter", label:"Counter (2 actors)",
    file:"abclc/counter.abcl",
    note:"Two Counter actors run inc → dec via self-send; runs on compile." },
  { key:"hello", label:"Hello (init + greet)",
    file:"abclc/Hello.abcl",
    note:"One Hello actor: init(5) then greet/inc/greet; runs on compile." },
];

const $ = (id) => document.getElementById(id);
let logCursor = -1;
let current = null;

// Visualization state for the bounded-buffer demo, rebuilt by parsing the
// console (the OCaml /api/actors does not expose field values).
function freshViz(){
  return { fifo:[], cap:4, lastPut:null, lastGot:null, total:0,
           pStatus:"", cStatus:"", pDone:false, cDone:false };
}
let viz = freshViz();

function setState(text, cls){ const e=$("runstate"); e.textContent=text; e.className=cls; }

// Send one REPL command; returns the text reply.
async function repl(command){
  const r = await fetch("/api/repl", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ command })
  });
  return await r.text();
}

function selected(){
  const k = $("progsel").value;
  return PROGRAMS.find(p => p.key === k) || PROGRAMS[0];
}

function clearConsole(){
  $("console").textContent = "";
  logCursor = -1;            // re-read from the start after a reset
  viz = freshViz();
  if (current && current.cap) viz.cap = current.cap;
}

// Update the bounded-buffer viz state from one console line.
function parseVizLine(line){
  let m;
  if ((m = line.match(/\[BUF\] put=(\d+)/)))               { viz.fifo.push(+m[1]); viz.lastPut=+m[1]; viz.pStatus="producing"; }
  else if ((m = line.match(/\[BUF\] accepted queued put=(\d+)/))) { viz.fifo.push(+m[1]); viz.lastPut=+m[1]; viz.pStatus="producing"; }
  else if (line.indexOf("[BUF] get") === 0)                { if (viz.fifo.length) viz.fifo.shift(); }
  else if ((m = line.match(/\[BUF\] passthrough put=(\d+)/))) { viz.lastPut=+m[1]; }
  else if ((m = line.match(/\[BUF\] FULL  -- queued put=(\d+)/))) { viz.lastPut=+m[1]; viz.pStatus="blocked (full)"; }
  else if (line.indexOf("[BUF] EMPTY") === 0)              { viz.cStatus="waiting (empty)"; }
  else if ((m = line.match(/\[P\d+\] -> put (\d+)/)))       { viz.pStatus="producing"; }
  else if (line.match(/\[P\d+\] DONE/))                     { viz.pDone=true; viz.pStatus="done"; }
  else if ((m = line.match(/\[C\d+\] got (\d+)\.?\s+\(total=(\d+)/))) { viz.lastGot=+m[1]; viz.total=+m[2]; viz.cStatus="consuming"; }
  else if (line.match(/\[C\d+\] DONE/))                     { viz.cDone=true; viz.cStatus="done"; }
}

function pcColor(status, done){
  const s = String(status||"").toLowerCase();
  if (done || s.indexOf("done")>=0) return "#7a8a99";
  if (s.indexOf("block")>=0 || s.indexOf("wait")>=0 || s.indexOf("full")>=0 || s.indexOf("empty")>=0) return "#ebcb8b";
  return "#81a1c1";
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

function drawViz(){
  const wrap = $("vizwrap"), sc = $("speedctl");
  if (!current || current.canvas !== "buffer"){
    wrap.style.display="none"; if (sc) sc.style.display="none"; return;
  }
  wrap.style.display = "block";
  if (sc) sc.style.display = current.speed ? "block" : "none";
  const cv = $("viz"), ctx = cv.getContext("2d"), W=cv.width, H=cv.height, cy=H/2;
  ctx.clearRect(0,0,W,H);
  const cap = viz.cap || 4, count = viz.fifo.length;
  // buffer slots — a single centred row, sized to fit `cap` between the
  // producer/consumer nodes on the sides.
  const gap=4, sideMargin=100, rowMaxW=W-2*sideMargin;
  const bw=Math.max(14, Math.min(58, Math.floor((rowMaxW-(cap-1)*gap)/cap)));
  const bh=Math.min(58, Math.max(34, bw));
  const rowW=cap*bw+(cap-1)*gap, gx=(W-rowW)/2, gy=cy-bh/2;
  ctx.textAlign="center"; ctx.fillStyle="#cdd6e0"; ctx.font="13px monospace";
  ctx.fillText("bounded buffer   "+count+"/"+cap, W/2, gy-14);
  for (let i=0;i<cap;i++){
    const bx=gx+i*(bw+gap), occ=i<count;
    ctx.fillStyle = occ ? "#2e4b2e" : "#11161d"; ctx.fillRect(bx,gy,bw,bh);
    ctx.lineWidth=2; ctx.strokeStyle = occ ? "#a3be8c" : "#2a3340"; ctx.strokeRect(bx,gy,bw,bh);
    if (occ && bw>=18){ ctx.fillStyle="#e5e9f0"; ctx.font=(bw>=28?"15px":"9px")+" monospace"; ctx.textBaseline="middle";
      ctx.fillText(String(viz.fifo[i]), bx+bw/2, gy+bh/2); ctx.textBaseline="alphabetic"; }
  }
  // producer (left) and consumer (right) nodes with flow arrows
  const node=(x,label,sub,status,done)=>{
    flowArrow(ctx, ...(label[0]==="P" ? [gx-8,cy, x+22,cy] : [x-22,cy, gx+rowW+8,cy]), pcColor(status,done));
    ctx.beginPath(); ctx.arc(x,cy,22,0,2*Math.PI); ctx.fillStyle=pcColor(status,done); ctx.fill();
    ctx.lineWidth=2; ctx.strokeStyle="#0b0f14"; ctx.stroke();
    ctx.fillStyle="#0b0f14"; ctx.font="bold 13px monospace"; ctx.textAlign="center";
    ctx.fillText(label, x, cy+1);
    ctx.fillStyle="#cdd6e0"; ctx.font="11px monospace"; if (sub) ctx.fillText(sub, x, cy+38);
    if (status){ ctx.fillStyle="#8fbcbb"; ctx.font="10px monospace"; ctx.fillText(String(status).slice(0,18), x, cy+52); }
  };
  node(54,        "P", viz.lastPut!=null ? ("put "+viz.lastPut) : "", viz.pStatus, viz.pDone);
  node(W-54,      "C", "got "+viz.total,                              viz.cStatus, viz.cDone);
  ctx.fillStyle="#7a8a99"; ctx.font="11px monospace"; ctx.textAlign="center";
  ctx.fillText("producer", 54, 18); ctx.fillText("consumer", W-54, 18);
}

async function doReset(){
  await repl("reset");
  clearConsole();
  $("abody").innerHTML = '<tr><td colspan="4">(reset)</td></tr>';
  $("acount").textContent = "";
  setState("reset", "reset");
}

async function loadRun(){
  const p = selected();
  current = p;
  setState("loading…", "loaded");
  await repl("reset");
  clearConsole();
  await repl("load " + p.file);
  await repl("compile");
  if (p.speed){ applySpeedDefaults(p); await pushSpeed(); }   // sync actors to the sliders
  if (p.start){ await repl(p.start); setState("running: " + p.label, "running"); }
  else        { setState("running: " + p.label, "running"); }
  setTimeout(tick, 200);
}

async function ctl(which){
  const p = current || selected();
  const cmd = which === "start" ? p.start : p.stop;
  if (!cmd){
    setState((current?current.label:"") + " — no " + which + " (auto-runs on compile)", "running");
    return;
  }
  await repl(cmd);
  setState((which === "start" ? "running: " : "stopped: ") + p.label,
           which === "start" ? "running" : "loaded");
}

// Speed sliders → live set_speed messages (only for programs with `speed`).
async function pushSpeed(){
  const pe = $("pspeed"), ce = $("cspeed"); if (!pe || !ce) return;
  const pv = +pe.value, cv = +ce.value;
  $("pspeedv").textContent = pv + " ms";
  $("cspeedv").textContent = cv + " ms";
  const p = current;
  if (!p || !p.speed) return;
  await repl("send " + p.speed.producer + ".set_speed(" + pv + ");");
  await repl("send " + p.speed.consumer + ".set_speed(" + cv + ");");
}

function applySpeedDefaults(p){
  if (!p || !p.speed) return;
  const pe = $("pspeed"), ce = $("cspeed");
  if (pe){ pe.value = p.speed.pdef; $("pspeedv").textContent = p.speed.pdef + " ms"; }
  if (ce){ ce.value = p.speed.cdef; $("cspeedv").textContent = p.speed.cdef + " ms"; }
}

function showNote(){
  const p = selected();
  $("note").textContent = p.note || "";
  applySpeedDefaults(p);
  const vl = $("vizlink");
  if (p.viz){ vl.href = p.viz; vl.style.display = "inline"; }
  else      { vl.style.display = "none"; }
  loadSource(p);
}

async function loadSource(p){
  $("srcpath").textContent = p.file;
  try {
    const r = await fetch("/api/source?file=" + encodeURIComponent(p.file), {cache:"no-store"});
    $("source").textContent = r.ok ? await r.text() : "(could not load " + p.file + ": " + r.status + ")";
  } catch(e){ $("source").textContent = "(load error: " + e + ")"; }
}

async function pollActors(){
  try {
    const a = await (await fetch("/api/actors", {cache:"no-store"})).json();
    // hide the runtime's internal <top> actor
    const rows = a.filter(x => x.name !== "<top>");
    $("acount").textContent = "(" + rows.length + ")";
    $("abody").innerHTML = rows.length
      ? rows.map(x =>
          "<tr><td>"+esc(x.name)+"</td><td class=cls>"+esc(x["class"])+"</td>"+
          "<td>"+(x.mbox|0)+"</td><td class=meth>"+
          esc((x.methods||[]).join(", "))+"</td></tr>").join("")
      : '<tr><td colspan="4">(no actors)</td></tr>';
  } catch(e){}
}

async function pollLog(){
  try {
    const d = await (await fetch("/api/log?after=" + logCursor, {cache:"no-store"})).json();
    if (typeof d.next === "number") logCursor = d.next;
    if (d.lines && d.lines.length){
      if (current && current.canvas === "buffer") d.lines.forEach(parseVizLine);
      const el = $("console");
      if (el.textContent === "(waiting for output...)") el.textContent = "";
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      el.textContent += d.lines.join("\n") + "\n";
      if (el.textContent.length > 60000) el.textContent = el.textContent.slice(-60000);
      if (atBottom) el.scrollTop = el.scrollHeight;
    }
  } catch(e){}
}

function esc(s){ return String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

async function tick(){ await pollActors(); await pollLog(); drawViz(); }

function init(){
  $("progsel").innerHTML = PROGRAMS.map(p =>
    '<option value="'+p.key+'">'+esc(p.label)+'</option>').join("");
  $("progsel").addEventListener("change", showNote);
  showNote();
  setInterval(tick, 700);
  tick();
}
init();
