#!/usr/bin/env node
/* MANET delivery-rate Monte Carlo — hard numbers to cross-check the GA scores.
 *
 * The GA (Rounds 1-3) ranked routing designs with LLM reviewers. This is the
 * objective counterpart: a time-stepped MANET with mobile UAVs, fixed relays +
 * ground station, frequent partitions, and per-protocol message delivery.
 * Measures delivery rate, latency, hops and control overhead for:
 *   - AODV          : reactive, single-shot — delivered only if a path exists
 *                     at send time (no buffering); RREQ floods to all nodes.
 *   - ZRP+custody   : intra-zone proactive + inter-zone bordercast (peripheral
 *                     nodes only) + ETX path + custody buffer at the source
 *                     (holds until a route returns within TTL).
 *   - DTN epidemic  : store-carry-forward, replicate to encountered nodes;
 *                     delivered when ANY copy-holder gains a path to GS.
 *
 * Topology/range mirror drone-hil (GS=shelter A, relays R1/R2/R3, R=0.30).
 * Deterministic: seeded mulberry32, so results are reproducible.
 *
 * Run:  node sim_delivery.mjs            (full sweep, writes out/delivery_results.json)
 */
import fs from 'fs';

// ---- fixed infrastructure (drone-hil coordinates) ----
const GS = { id:'GS', x:0.05, y:0.30, mobile:false };
const RELAYS = [ {id:'R1',x:0.30,y:0.40}, {id:'R2',x:0.52,y:0.58}, {id:'R3',x:0.74,y:0.42} ].map(r=>({...r,mobile:false}));
const N_UAV = 3;                       // mobile sources (UAV1..UAV3)
const R_DEFAULT = 0.30;                // comm range
const STEPS = 1500;                    // timesteps per trial
const SEND_EVERY = 25;                 // each UAV sends to GS every N steps
const TTL = 120;                       // custody / DTN buffer lifetime (steps)
const UAV_SPEED = 0.006;               // per step (normalised)
const HOP_DELAY = 1;                   // latency units per hop

function mulberry32(a){ return function(){ a|=0; a=a+0x6D2B79F5|0; let t=Math.imul(a^a>>>15,1|a);
  t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296; }; }
const dist=(p,q)=>Math.hypot(p.x-q.x,p.y-q.y);

// build node list with mobile UAVs doing random-waypoint motion
function makeNodes(rnd){
  const uavs=[];
  for (let i=0;i<N_UAV;i++) uavs.push({ id:'UAV'+(i+1), x:GS.x, y:GS.y, mobile:true,
    tx:rnd(), ty:rnd() });                                   // waypoint
  return [GS, ...RELAYS, ...uavs];
}
function moveUAVs(nodes, rnd){
  for (const n of nodes){ if(!n.mobile) continue;
    const dx=n.tx-n.x, dy=n.ty-n.y, d=Math.hypot(dx,dy);
    if (d < UAV_SPEED){ n.x=n.tx; n.y=n.ty; n.tx=rnd(); n.ty=rnd(); }   // pick new waypoint
    else { n.x+=dx/d*UAV_SPEED; n.y+=dy/d*UAV_SPEED; }
  }
}

// adjacency within range R
function links(nodes, R){ const adj=nodes.map(()=>[]);
  for (let i=0;i<nodes.length;i++) for (let j=i+1;j<nodes.length;j++)
    if (dist(nodes[i],nodes[j])<=R){ adj[i].push(j); adj[j].push(i); }
  return adj;
}
// BFS shortest-hop path (returns idx path or null)
function bfsPath(adj, s, t){
  if (s===t) return [s];
  const prev=new Array(adj.length).fill(-1), seen=new Array(adj.length).fill(false);
  const q=[s]; seen[s]=true;
  while(q.length){ const u=q.shift(); if(u===t) break;
    for(const v of adj[u]) if(!seen[v]){seen[v]=true;prev[v]=u;q.push(v);} }
  if(!seen[t]) return null;
  const p=[]; for(let u=t;u!==-1;u=prev[u]) p.unshift(u); return p;
}
// ETX-weighted shortest path (Dijkstra); cost = sum 1/(1-dist/R)
function etxPath(nodes, adj, s, t, R){
  const D=nodes.map(()=>Infinity), P=nodes.map(()=>-1), done=nodes.map(()=>false);
  D[s]=0;
  for(;;){ let u=-1,bd=Infinity; for(let k=0;k<nodes.length;k++) if(!done[k]&&D[k]<bd){bd=D[k];u=k;}
    if(u<0) break; done[u]=true; if(u===t) break;
    for(const v of adj[u]){ const w=1/Math.max(0.08,1-dist(nodes[u],nodes[v])/R);
      if(D[u]+w<D[v]){D[v]=D[u]+w;P[v]=u;} } }
  if(D[t]===Infinity) return null;
  const p=[]; for(let u=t;u!==-1;u=P[u]) p.unshift(u); return p;
}
// ZRP zone (<=RHO hops) and peripheral count from src
function zonePeripheral(adj, s, RHO){
  const hop=new Array(adj.length).fill(Infinity); hop[s]=0; const q=[s];
  while(q.length){ const u=q.shift(); if(hop[u]>=RHO) continue;
    for(const v of adj[u]) if(hop[v]===Infinity){hop[v]=hop[u]+1;q.push(v);} }
  let inZone=0, peri=0; hop.forEach(h=>{ if(h<Infinity&&h<=RHO) inZone++; if(h===RHO) peri++; });
  return { inZone, peri };
}

// ---- one trial for one protocol ----
function trial(proto, R, seed){
  const rnd=mulberry32(seed);
  const nodes=makeNodes(rnd);
  const gsIdx=0;
  const uavIdx=[]; nodes.forEach((n,i)=>{ if(n.mobile) uavIdx.push(i); });
  let sent=0, delivered=0, latSum=0, hopSum=0, control=0, expired=0;
  const buffers=[];   // pending msgs: {src, born, holders:Set, kind}

  for (let step=0; step<STEPS; step++){
    moveUAVs(nodes, rnd);
    const adj=links(nodes, R);

    // generate traffic
    if (step % SEND_EVERY === 0 && step>0){
      for (const ui of uavIdx){ sent++;
        if (proto==='AODV'){
          control += nodes.length;                    // RREQ floods to all nodes
          const p=bfsPath(adj, ui, gsIdx);
          if (p){ delivered++; latSum += (p.length-1)*HOP_DELAY; hopSum += p.length-1; }
          // else: dropped (no buffering)
        } else if (proto==='ZRP'){
          const p=etxPath(nodes, adj, ui, gsIdx, R);
          if (p){ delivered++; latSum += (p.length-1)*HOP_DELAY; hopSum += p.length-1;
            const z=zonePeripheral(adj, ui, 1); control += Math.max(1, z.peri); } // bordercast = peripheral only
          else { buffers.push({src:ui, born:step, kind:'zrp'});                     // custody at source
                 const z=zonePeripheral(adj, ui, 1); control += Math.max(1, z.peri); }
        } else if (proto==='DTN'){
          buffers.push({src:ui, born:step, holders:new Set([ui]), kind:'dtn'});      // store-carry-forward
        }
      }
    }

    // service pending buffers (ZRP custody + DTN epidemic)
    for (let b=buffers.length-1; b>=0; b--){
      const m=buffers[b];
      if (step - m.born > TTL){ buffers.splice(b,1); expired++; continue; }
      if (m.kind==='zrp'){
        const p=etxPath(nodes, adj, m.src, gsIdx, R);
        if (p){ delivered++; latSum += (step-m.born) + (p.length-1)*HOP_DELAY; hopSum += p.length-1;
          buffers.splice(b,1); }
      } else { // dtn epidemic: replicate to neighbours; deliver if any holder has a path to GS
        let done=false;
        for (const h of m.holders){ const p=bfsPath(adj, h, gsIdx);
          if (p){ delivered++; latSum += (step-m.born) + (p.length-1)*HOP_DELAY; hopSum += p.length-1;
            buffers.splice(b,1); done=true; break; } }
        if (done) continue;
        const add=[]; for (const h of m.holders) for (const v of adj[h]) if(!m.holders.has(v)) add.push(v);
        for (const v of add){ m.holders.add(v); control++; }                          // each replication = 1 control msg
      }
    }
  }
  return { sent, delivered, expired,
    deliveryRate: sent? delivered/sent : 0,
    meanLatency: delivered? latSum/delivered : 0,
    meanHops: delivered? hopSum/delivered : 0,
    ctrlPerMsg: sent? control/sent : 0 };
}

function avg(trials, key){ return trials.reduce((a,t)=>a+t[key],0)/trials.length; }

// ---- sweep ----
const PROTOS=['AODV','ZRP','DTN'];
const RANGES=[0.22, 0.30, 0.40];     // smaller R = more partition
const SEEDS=24;
const results={ meta:{ N_UAV, STEPS, SEND_EVERY, TTL, UAV_SPEED, SEEDS, RANGES }, byRange:{} };

console.log(`MANET delivery Monte Carlo — ${N_UAV} mobile UAVs + 3 relays + GS, ${SEEDS} seeds × ${STEPS} steps\n`);
for (const R of RANGES){
  results.byRange[R]={};
  console.log(`=== comm range R=${R} (${R<0.3?'high partition':R>0.3?'well connected':'baseline'}) ===`);
  console.log(`  proto   delivery%   latency  hops   ctrl/msg`);
  for (const proto of PROTOS){
    const trials=[]; for (let s=0;s<SEEDS;s++) trials.push(trial(proto, R, 1000+s*7+Math.round(R*100)));
    const dr=avg(trials,'deliveryRate'), lat=avg(trials,'meanLatency'), hop=avg(trials,'meanHops'), ctrl=avg(trials,'ctrlPerMsg');
    results.byRange[R][proto]={ deliveryRate:dr, meanLatency:lat, meanHops:hop, ctrlPerMsg:ctrl };
    console.log(`  ${proto.padEnd(6)}  ${(dr*100).toFixed(1).padStart(7)}%   ${lat.toFixed(1).padStart(6)}  ${hop.toFixed(2)}   ${ctrl.toFixed(1).padStart(6)}`);
  }
  console.log('');
}

const outPath = new URL('./out/delivery_results.json', import.meta.url);
fs.writeFileSync(outPath, JSON.stringify(results,null,2));
console.log('wrote', outPath.pathname);
