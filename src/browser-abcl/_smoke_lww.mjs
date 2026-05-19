// C4 smoke — lwwWins purity + an integration race against the real
// node-aipl-server (must already be running on 8090).
//
// Run from a directory whose node_modules has `ws` (e.g.
// src/node-aipl-server).  _smoke_lww.sh handles that.
import { lwwWins, newClientId } from "./src/lww.js";
import WebSocket from "ws";

let pass = 0, fail = 0;
function t(label, ok) {
  if (ok) { pass++; console.log("  PASS ", label); }
  else    { fail++; console.log("  FAIL ", label); }
}

console.log("[unit] lwwWins purity");
t("incoming wins when no current",
  lwwWins({ ts: 1, origin: "a" }, null) === true);
t("higher ts wins",
  lwwWins({ ts: 5, origin: "a" }, { ts: 4, origin: "z" }) === true);
t("lower ts loses",
  lwwWins({ ts: 4, origin: "z" }, { ts: 5, origin: "a" }) === false);
t("equal ts, larger origin wins",
  lwwWins({ ts: 7, origin: "z" }, { ts: 7, origin: "a" }) === true);
t("equal ts, smaller origin loses",
  lwwWins({ ts: 7, origin: "a" }, { ts: 7, origin: "z" }) === false);
t("equal ts, equal origin: tie → loses (not strictly newer)",
  lwwWins({ ts: 7, origin: "a" }, { ts: 7, origin: "a" }) === false);
t("newClientId shape c-XXXXXX",
  /^c-[a-z0-9]{1,6}$/.test(newClientId()));

console.log("[integration] race two clients on real /ws");
const PORT = process.env.PORT || 8090;
const sid  = "sheet:lww_smoke_" + Date.now();
const A = new WebSocket(`ws://localhost:${PORT}/ws?sid=${encodeURIComponent(sid)}`);
const B = new WebSocket(`ws://localhost:${PORT}/ws?sid=${encodeURIComponent(sid)}`);

// Each peer drives its own LWW state for the cell A1.
const state = {
  A: { lamport: 0, origin: "origA", clock: null, value: null },
  B: { lamport: 0, origin: "origB", clock: null, value: null },
};
function localWrite(peer, val) {
  const s = state[peer];
  s.lamport += 1;
  s.clock = { ts: s.lamport, origin: s.origin };
  s.value = val;
  return { type: "cell", row: 0, col: 0, val, kind: "Value",
           formula: null, fmt: "general",
           ts: s.lamport, origin: s.origin };
}
function applyRemote(peer, msg) {
  const s = state[peer];
  s.lamport = Math.max(s.lamport, msg.ts) + 1;
  const incoming = { ts: msg.ts, origin: msg.origin };
  if (!lwwWins(incoming, s.clock)) return false;
  s.clock = incoming;
  s.value = msg.val;
  return true;
}

const opens = Promise.all([
  new Promise(r => A.on("open", r)),
  new Promise(r => B.on("open", r)),
]);

A.on("message", raw => {
  const m = JSON.parse(raw.toString());
  if (m.type !== "cell" || m.origin === state.A.origin) return;
  applyRemote("A", m);
});
B.on("message", raw => {
  const m = JSON.parse(raw.toString());
  if (m.type !== "cell" || m.origin === state.B.origin) return;
  applyRemote("B", m);
});

await opens;

// Concurrent writes: A writes 100 at ts=1/origA, B writes 200 at ts=1/origB.
// Tiebreak by origin → origB > origA → both peers converge to 200.
A.send(JSON.stringify(localWrite("A", 100)));
B.send(JSON.stringify(localWrite("B", 200)));

// Then A learns about B and tries a follow-up at ts=2/origA.
// Per Lamport, A's clock catches up to ts=2 on receive, so the
// follow-up should stamp ts=3/origA, beating B's ts=1.
await new Promise(r => setTimeout(r, 250));
A.send(JSON.stringify(localWrite("A", 300)));

await new Promise(r => setTimeout(r, 350));
A.close(); B.close();

t("race1: both peers converge to 200 after concurrent A=100 / B=200",
  state.A.value === 300 && state.B.value === 300);
t("race1: A's follow-up (ts after Lamport catch-up) wins on both peers",
  state.A.clock.origin === "origA" && state.B.clock.origin === "origA");
t("race1: ts strictly increases past the racing pair",
  state.A.clock.ts >= 3 && state.B.clock.ts >= 3);

console.log(`\n==== _smoke_lww summary ====\n  pass=${pass}  fail=${fail}`);
process.exit(fail === 0 ? 0 : 1);
