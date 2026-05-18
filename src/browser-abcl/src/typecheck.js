// typecheck.js — flow-sensitive ad-hoc type inference for browser-abcl AIPL.
//
// Mirrors the OCaml runtime's Infer module conceptually, but uses a simpler
// single-pass flow-sensitive walker. No unification — type information is
// propagated forward from concrete sources (literals, field initializers,
// call-site argument types) to consumers.
//
// Type tags used internally:
//   "int", "float", "string", "bool", "unit",
//   "actor:<ClassName>",
//   "any"        ← unknown / polymorphic — never an error
//
// Strategy:
//   Pass 1 (build): walk every class, infer field types from initializer
//                   expressions. Cache `classFieldTypes[cls][field]`.
//
//   Pass 2 (build): walk every send/now/future/new call site, accumulate
//                   per-method argument-type sets, then assign each method
//                   parameter the meet of the observed types (or "any" if
//                   never called or called with mixed types).
//                   Cache `methodSigs[cls][method] = { params, ret }`.
//
//   Pass 3 (check): walk every method body and global statement, building
//                   local environments. Check that Assign / Binop / Send /
//                   CallStmt / If / While / Reply respect the types.
//
// On any inconsistency, throw `TypeError` with a descriptive message.
// The interpreter caller wraps the call so the runtime sees a clean failure.

export class TypeError extends Error {
  constructor(msg) { super(msg); this.name = "TypeError"; }
}

const ANY = "any";

// ─── CE-10: primitive effect table ──────────────────────────────
// Effect labels match the OCaml/Py-I tables: ai, fs, net, mut.
// "mut" tracks visible state mutation; "net" covers cross-region
// or replication-style network reach.
export const BUILTIN_EFFECTS = {
  ai_call:              ["ai"],
  ai_call_with_system:  ["ai"],
  read_file:            ["fs"],
  write_file:           ["fs", "mut"],
  append_file:          ["fs", "mut"],
  file_exists:          ["fs"],
  image_load:           ["fs"],
  image_save:           ["fs", "mut"],
  image_create:         ["mut"],
  image_set_pixel:      ["mut"],
  grant_cap:            ["mut"],
  revoke_cap:           ["mut"],
  crdt_gcounter_inc:    ["mut"],
  crdt_orset_add:       ["mut"],
  crdt_orset_remove:    ["mut"],
  crdt_lww_write:       ["mut"],
  crdt_gcounter_merge:  ["mut"],
  crdt_orset_merge:     ["mut"],
  crdt_lww_merge:       ["mut"],
  crdt_replicate:       ["mut", "net"],
  failover_region:      ["net"],
  route_for_region:     ["net"],
  pool_create:          ["mut"],
  pool_destroy:         ["mut"],
};

function effSet(arr) { return new Set(arr || []); }
function effUnion(a, b) {
  const out = new Set(a);
  for (const e of b) out.add(e);
  return out;
}
function effFmt(s) { return [...s].sort().join(","); }

// ─── CE-12: refinement type wrapper ─────────────────────────────
// A refined type is `{ kind:"refined", base, pred }`.  Equal preds
// always unify; otherwise we attempt subset via the host's
// `refinement_check` hook (which is plain string-equality in the
// browser and may shell out to z3 in Node when AIPL_REFINE_Z3=1).
export function refined(base, pred) {
  return { kind: "refined", base, pred };
}
function refineBase(t) {
  return (t && typeof t === "object" && t.kind === "refined") ? t.base : t;
}
function refinePred(t) {
  return (t && typeof t === "object" && t.kind === "refined") ? t.pred : null;
}
function refineSubset(predA, predB) {
  if (predA === predB) return true;
  if (!predA || !predB) return false;
  // Hook for Node-only z3.  Browser never enables this.
  if (typeof globalThis !== "undefined" &&
      typeof globalThis.__AIPL_REFINE_CHECK === "function") {
    try { return !!globalThis.__AIPL_REFINE_CHECK(predA, predB); }
    catch (_) { return false; }
  }
  return false;
}

// ─── CE-13: record type with width subtyping ────────────────────
// A record type is `{ kind:"record", fields: { name: t, ... } }`.
// Currently the only way to produce one is by reading actor field
// maps via `classFieldTypes`; we surface this in the type tag
// `"record:<ClassName>"` so checkProgram can do width subtyping
// when the same actor is bound under a smaller interface.
function recordOf(fields) {
  return { kind: "record", fields: fields || {} };
}
function recordFields(t) {
  return (t && typeof t === "object" && t.kind === "record") ? t.fields : null;
}

function isConcrete(t) {
  return t !== ANY && t !== "unit";
}

function compatible(a, b) {
  // any matches anything
  if (a === ANY || b === ANY) return true;
  if (a === b) return true;
  // CE-12: refinement-aware compatibility — bases must agree, preds
  // must coincide or pass the host subset check.
  const aIsRefined = a && typeof a === "object" && a.kind === "refined";
  const bIsRefined = b && typeof b === "object" && b.kind === "refined";
  if (aIsRefined || bIsRefined) {
    const ba = refineBase(a), bb = refineBase(b);
    if (!compatible(ba, bb)) return false;
    const pa = refinePred(a), pb = refinePred(b);
    if (!pa && !pb) return true;
    if (!pa || !pb) return true;             // gradual: one side unrefined
    return pa === pb || refineSubset(pa, pb);
  }
  // CE-13: record width subtyping — every field on the *narrower*
  // side must be type-compatible with the same field on the wider
  // side.  Order: compatible(narrower, wider) holds when narrower
  // can be supplied in place of wider.
  const aRec = recordFields(a), bRec = recordFields(b);
  if (aRec && bRec) {
    for (const k of Object.keys(bRec)) {
      if (!(k in aRec)) return false;
      if (!compatible(aRec[k], bRec[k])) return false;
    }
    return true;
  }
  // int and float are compatible (numeric promotion)
  if ((a === "int" || a === "float") && (b === "int" || b === "float")) return true;
  // actor type compatibility: any actor matches the wildcard "actor:"
  if (typeof a === "string" && a.startsWith("actor:") &&
      typeof b === "string" && b.startsWith("actor:")) {
    // either side may be wildcard "actor:"
    if (a === "actor:" || b === "actor:") return true;
    return a === b;
  }
  return false;
}

// join: least upper bound. Monotonic — once widened to ANY, stays ANY.
// Used for field/var assignment merging (sentinel patterns etc.).
function join(a, b) {
  if (a === b) return a;
  if (a === ANY || b === ANY) return ANY;
  // numeric promotion: int + float = float
  if ((a === "int" && b === "float") || (a === "float" && b === "int")) return "float";
  // mismatched concrete types — fall back to ANY
  return ANY;
}

// (legacy alias for places that historically called meet — same behavior now)
const meet = join;

function literalType(node) {
  switch (node.type) {
    case "IntLit":    return "int";
    case "FloatLit":  return "float";
    case "StringLit": return "string";
    default: return null;
  }
}

// ----------------------------------------------------------------------
// Pass 1: collect field types

function buildFieldTypes(ast) {
  const classFieldTypes = {};
  // Pass 1a: from initializers
  for (const cls of ast.classes) {
    const fields = {};
    for (const field of (cls.fields || [])) {
      if (field.type === "VarField") {
        const t = inferExprType(field.expr, { fields: {}, params: {}, locals: {}, classFieldTypes, methodSigs: {} });
        fields[field.name] = t;
      }
    }
    classFieldTypes[cls.name] = fields;
  }
  // Pass 1b: also walk all method bodies and meet the type of any
  // field assignment, so sentinel patterns like `var pwaiter = "";` then
  // `pwaiter = sender;` widen to ANY (gradual).
  function walkForFieldAssigns(node, cls, env) {
    if (!node) return;
    switch (node.type) {
      case "Seq":
        node.statements.forEach(s => walkForFieldAssigns(s, cls, env));
        break;
      case "Assign": {
        if (classFieldTypes[cls] && classFieldTypes[cls][node.name] !== undefined) {
          const rhs = inferExprType(node.expr, env);
          const prev = classFieldTypes[cls][node.name];
          classFieldTypes[cls][node.name] = join(prev, rhs);
        }
        break;
      }
      case "If":
        walkForFieldAssigns(node.thenBody, cls, env);
        if (node.elseBody) walkForFieldAssigns(node.elseBody, cls, env);
        break;
      case "Select":
        node.cases.forEach(c => walkForFieldAssigns(c.body, cls, env));
        if (node.timeoutBody) walkForFieldAssigns(node.timeoutBody, cls, env);
        break;
    }
  }
  for (const cls of ast.classes) {
    for (const md of cls.methods) {
      const env = {
        fields: classFieldTypes[cls.name] || {},
        params: Object.fromEntries(md.params.map(p => [p, ANY])),
        locals: {},
        classFieldTypes,
        methodSigs: {},
      };
      walkForFieldAssigns(md.body, cls.name, env);
    }
  }
  return classFieldTypes;
}

// ----------------------------------------------------------------------
// Pass 2: collect method signatures from call sites
//
// For each `send t.m(a,b)` (or now/future/new), record the inferred types
// of (a,b) under (className,methodName). Then merge across call sites.

function buildMethodSigs(ast, classFieldTypes) {
  const callSites = {};  // "ClassName.method" -> array of arg-type-lists

  function record(className, methodName, argTypes) {
    const key = className + "." + methodName;
    if (!callSites[key]) callSites[key] = [];
    callSites[key].push(argTypes);
  }

  // Initial env with empty methodSigs (we use only field types here)
  const seedEnv = () => ({ fields: {}, params: {}, locals: {}, classFieldTypes, methodSigs: {} });

  function walkExpr(e, env) {
    if (!e) return;
    if (e.type === "NewExpr") {
      const args = e.args.map(a => inferExprType(a, env));
      record(e.className, "init", args);
      e.args.forEach(a => walkExpr(a, env));
    } else if (e.type === "Now" || e.type === "Future") {
      const tgtType = inferExprType(e.target, env);
      if (typeof tgtType === "string" && tgtType.startsWith("actor:")) {
        const cls = tgtType.slice(6);
        if (cls) {
          const args = e.args.map(a => inferExprType(a, env));
          record(cls, e.method, args);
        }
      }
      e.args.forEach(a => walkExpr(a, env));
    } else if (e.type === "Binop") {
      walkExpr(e.left, env); walkExpr(e.right, env);
    } else if (e.type === "CallExpr") {
      e.args.forEach(a => walkExpr(a, env));
    } else if (e.type === "Await") {
      walkExpr(e.expr, env);
    }
  }

  function walkStmt(s, env) {
    if (!s) return;
    switch (s.type) {
      case "Seq":      s.statements.forEach(x => walkStmt(x, env)); break;
      case "VarDecl":
      case "Assign":   walkExpr(s.expr, env); break;
      case "Send": {
        const tgtType = inferExprType(s.target, env);
        if (typeof tgtType === "string" && tgtType.startsWith("actor:")) {
          const cls = tgtType.slice(6);
          if (cls) {
            const args = s.args.map(a => inferExprType(a, env));
            record(cls, s.method, args);
          }
        }
        s.args.forEach(a => walkExpr(a, env));
        break;
      }
      case "Print":    walkExpr(s.expr, env); break;
      case "Reply":    walkExpr(s.expr, env); break;
      case "CallStmt": s.args.forEach(a => walkExpr(a, env)); break;
      case "If":       walkExpr(s.cond, env); walkStmt(s.thenBody, env);
                       if (s.elseBody) walkStmt(s.elseBody, env); break;
      case "Select":   s.cases.forEach(c => walkStmt(c.body, env));
                       if (s.timeoutBody) walkStmt(s.timeoutBody, env); break;
    }
  }

  // walk class methods (use the class's field types as known env)
  for (const cls of ast.classes) {
    for (const md of cls.methods) {
      const env = seedEnv();
      env.fields = classFieldTypes[cls.name] || {};
      // Without method sigs yet, params start as "any"
      for (const p of md.params) env.params[p] = ANY;
      walkStmt(md.body, env);
    }
  }
  // walk globals
  for (const s of ast.statements) walkStmt(s, seedEnv());

  // build signatures by meeting all observed arg types per param
  const methodSigs = {};
  for (const key of Object.keys(callSites)) {
    const [cls, m] = key.split(".");
    const calls = callSites[key];
    const arity = Math.max(...calls.map(a => a.length));
    const params = [];
    for (let i = 0; i < arity; i++) {
      let t = ANY;
      for (const call of calls) {
        if (i < call.length) t = meet(t, call[i]);
      }
      params.push(t);
    }
    if (!methodSigs[cls]) methodSigs[cls] = {};
    methodSigs[cls][m] = { params, ret: ANY };
  }

  // attach declared params from AST (those never called → all any)
  for (const cls of ast.classes) {
    if (!methodSigs[cls.name]) methodSigs[cls.name] = {};
    for (const md of cls.methods) {
      if (!methodSigs[cls.name][md.name]) {
        methodSigs[cls.name][md.name] = {
          params: md.params.map(() => ANY),
          ret: ANY,
        };
      }
    }
  }

  return methodSigs;
}

// ----------------------------------------------------------------------
// Expression type inference (used in all passes)

function inferExprType(e, env) {
  if (!e) return ANY;
  const lit = literalType(e);
  if (lit) return lit;
  switch (e.type) {
    case "Var": {
      const n = e.name;
      if (n === "self") return "actor:";
      if (n === "sender") return "actor:";
      if (env.locals[n] !== undefined) return env.locals[n];
      if (env.params[n] !== undefined) return env.params[n];
      if (env.fields[n] !== undefined) return env.fields[n];
      return ANY;  // global / unknown
    }
    case "Binop": {
      const l = inferExprType(e.left, env);
      const r = inferExprType(e.right, env);
      if (e.op === "+") {
        if (l === "string" || r === "string") return "string";
        if (l === "float" || r === "float") return "float";
        if (l === "int" && r === "int") return "int";
        return ANY;
      }
      if (["-", "*", "/"].includes(e.op)) {
        if (l === "float" || r === "float") return "float";
        if (l === "int" && r === "int") return "int";
        return ANY;
      }
      if (["==", "!=", "<", "<=", ">", ">="].includes(e.op)) return "bool";
      return ANY;
    }
    case "CallExpr": return ANY;  // unknown / builtin
    case "NewExpr":  return "actor:" + e.className;
    case "Now": {
      const tgt = inferExprType(e.target, env);
      if (typeof tgt === "string" && tgt.startsWith("actor:")) {
        const cls = tgt.slice(6);
        if (cls && env.methodSigs[cls] && env.methodSigs[cls][e.method]) {
          return env.methodSigs[cls][e.method].ret;
        }
      }
      return ANY;
    }
    case "Future": return "future";
    case "Await":  return ANY;
    default:       return ANY;
  }
}

// ----------------------------------------------------------------------
// Pass 3: check method bodies for consistency

function checkProgram(ast, classFieldTypes, methodSigs) {
  function newEnv(cls, params) {
    return {
      fields: classFieldTypes[cls] || {},
      params: { ...(params || {}) },
      locals: {},
      classFieldTypes,
      methodSigs,
    };
  }

  function check(node, env, currentClass) {
    if (!node) return;
    switch (node.type) {
      case "Seq":
        node.statements.forEach(s => check(s, env, currentClass));
        break;

      case "VarDecl": {
        const t = inferExprType(node.expr, env);
        env.locals[node.name] = t;
        break;
      }

      case "Assign": {
        const rhs = inferExprType(node.expr, env);
        let target = null;
        if (env.locals[node.name] !== undefined) target = env.locals[node.name];
        else if (env.params[node.name] !== undefined) target = env.params[node.name];
        else if (env.fields[node.name] !== undefined) target = env.fields[node.name];
        if (target !== null && !compatible(target, rhs)) {
          throw new TypeError(
            `assign type mismatch on '${node.name}': expected ${target}, got ${rhs}`);
        }
        break;
      }

      case "Binop": {
        // recheck via inferExprType — throw on incompatibilities for arithmetic
        const l = inferExprType(node.left, env);
        const r = inferExprType(node.right, env);
        if (["-", "*", "/"].includes(node.op)) {
          if (isConcrete(l) && isConcrete(r) &&
              !["int", "float"].includes(l) || !["int", "float"].includes(r)) {
            if (!compatible(l, "float") || !compatible(r, "float")) {
              throw new TypeError(
                `binop '${node.op}' requires numeric operands; got ${l} ${node.op} ${r}`);
            }
          }
        }
        break;
      }

      case "Send": {
        const tgt = inferExprType(node.target, env);
        if (typeof tgt === "string" && tgt.startsWith("actor:") && tgt !== "actor:") {
          const cls = tgt.slice(6);
          const sig = methodSigs[cls] && methodSigs[cls][node.method];
          if (sig) {
            if (node.args.length !== sig.params.length) {
              throw new TypeError(
                `${cls}.${node.method}: arity mismatch (expected ${sig.params.length}, got ${node.args.length})`);
            }
            for (let i = 0; i < node.args.length; i++) {
              const at = inferExprType(node.args[i], env);
              if (!compatible(sig.params[i], at)) {
                throw new TypeError(
                  `${cls}.${node.method} arg ${i}: expected ${sig.params[i]}, got ${at}`);
              }
            }
          }
        }
        break;
      }

      case "If":
        check(node.thenBody, env, currentClass);
        if (node.elseBody) check(node.elseBody, env, currentClass);
        break;

      case "Select":
        node.cases.forEach(c => check(c.body, env, currentClass));
        if (node.timeoutBody) check(node.timeoutBody, env, currentClass);
        break;

      // DR-11: saga body / compensate share the enclosing env
      case "Saga":
        for (const step of node.steps) {
          check(step.body, env, currentClass);
          check(step.compensate, env, currentClass);
        }
        break;

      // Print, Reply, CallStmt — only walk subexprs, no constraint
      case "Print":    inferExprType(node.expr, env); break;
      case "Reply":    inferExprType(node.expr, env); break;
      case "CallStmt": node.args.forEach(a => inferExprType(a, env)); break;
    }
  }

  for (const cls of ast.classes) {
    for (const md of cls.methods) {
      const sig = methodSigs[cls.name] && methodSigs[cls.name][md.name];
      const params = {};
      if (sig && sig.params) {
        md.params.forEach((p, i) => { params[p] = sig.params[i] || ANY; });
      } else {
        md.params.forEach(p => { params[p] = ANY; });
      }
      const env = newEnv(cls.name, params);
      check(md.body, env, cls.name);
    }
  }

  // also walk top-level globals (they share env with VarDecl tracking)
  const globalEnv = {
    fields: {}, params: {}, locals: {}, classFieldTypes, methodSigs,
  };
  for (const s of ast.statements) check(s, globalEnv, null);
}

// ----------------------------------------------------------------------
// CE-10: collect declared + transitive effects for every method.
// Result shape:  effects[className][methodName] = Set<"ai"|"fs"|"net"|"mut">

function collectMethodEffects(ast) {
  const effects = {};
  for (const cls of ast.classes) {
    effects[cls.name] = {};
    for (const md of cls.methods) effects[cls.name][md.name] = new Set();
  }

  // Per-method: collect direct primitive effects, "mut" from any
  // field assignment / index assign, "mut" from send/now/future
  // (sending a message mutates the target actor's mailbox), plus
  // a list of called (cls, method) edges so we can iterate to a
  // fixed point afterwards.
  const callEdges = {};   // "C.m" -> [["C2","m2"], ...]
  function addEdge(from, to) {
    if (!callEdges[from]) callEdges[from] = [];
    callEdges[from].push(to);
  }
  function direct(node, ownerCls, ownerMethod, env) {
    if (!node) return;
    switch (node.type) {
      case "Seq":
        node.statements.forEach(s => direct(s, ownerCls, ownerMethod, env));
        return;
      case "VarDecl":
        direct(node.expr, ownerCls, ownerMethod, env); return;
      case "Assign":
        // assignment to a class field counts as "mut"; locals/params do not
        if (env.fields[node.name] !== undefined)
          effects[ownerCls][ownerMethod].add("mut");
        direct(node.expr, ownerCls, ownerMethod, env);
        return;
      case "IndexAssign":
        effects[ownerCls][ownerMethod].add("mut");
        direct(node.expr, ownerCls, ownerMethod, env);
        node.dims.forEach(d => direct(d, ownerCls, ownerMethod, env));
        return;
      case "Send":
      case "Now":
      case "Future": {
        effects[ownerCls][ownerMethod].add("mut");  // mailbox mutation
        // Resolve target class via fields/params/locals
        const tgtType = inferExprType(node.target, env);
        if (typeof tgtType === "string" && tgtType.startsWith("actor:")) {
          const cls = tgtType.slice(6);
          if (cls) addEdge(`${ownerCls}.${ownerMethod}`, [cls, node.method]);
        }
        node.args.forEach(a => direct(a, ownerCls, ownerMethod, env));
        return;
      }
      case "Print":  direct(node.expr, ownerCls, ownerMethod, env); return;
      case "Reply":
        // a reply propagates a value back — counts as mut on caller's reply slot
        effects[ownerCls][ownerMethod].add("mut");
        direct(node.expr, ownerCls, ownerMethod, env);
        return;
      case "CallStmt": {
        const e = BUILTIN_EFFECTS[node.name];
        if (e) for (const x of e) effects[ownerCls][ownerMethod].add(x);
        node.args.forEach(a => direct(a, ownerCls, ownerMethod, env));
        return;
      }
      case "If":
        direct(node.cond, ownerCls, ownerMethod, env);
        direct(node.thenBody, ownerCls, ownerMethod, env);
        if (node.elseBody) direct(node.elseBody, ownerCls, ownerMethod, env);
        return;
      case "Select":
        node.cases.forEach(c => direct(c.body, ownerCls, ownerMethod, env));
        if (node.timeoutBody) direct(node.timeoutBody, ownerCls, ownerMethod, env);
        return;
      case "Saga":
        // DR-11 + CE-10: saga is mut (writes events, runs side-effecting
        // bodies). Walk each step and compensate too.
        effects[ownerCls][ownerMethod].add("mut");
        for (const step of node.steps) {
          direct(step.body,       ownerCls, ownerMethod, env);
          direct(step.compensate, ownerCls, ownerMethod, env);
        }
        return;
      // Expressions
      case "Binop":
        direct(node.left, ownerCls, ownerMethod, env);
        direct(node.right, ownerCls, ownerMethod, env);
        return;
      case "CallExpr": {
        const e = BUILTIN_EFFECTS[node.name];
        if (e) for (const x of e) effects[ownerCls][ownerMethod].add(x);
        node.args.forEach(a => direct(a, ownerCls, ownerMethod, env));
        return;
      }
      case "Await":
        direct(node.expr, ownerCls, ownerMethod, env); return;
      case "NewExpr":
        // Construction sends `init` — propagates from constructor
        addEdge(`${ownerCls}.${ownerMethod}`, [node.className, "init"]);
        effects[ownerCls][ownerMethod].add("mut");
        node.args.forEach(a => direct(a, ownerCls, ownerMethod, env));
        return;
    }
  }

  // Direct pass
  for (const cls of ast.classes) {
    for (const md of cls.methods) {
      const env = {
        fields: {}, params: {}, locals: {},
        classFieldTypes: {}, methodSigs: {},
      };
      // Seed field map (just names, types don't matter for effects)
      for (const f of (cls.fields || [])) env.fields[f.name] = ANY;
      for (const p of md.params) env.params[p] = ANY;
      direct(md.body, cls.name, md.name, env);
    }
  }

  // Fixed-point over call edges
  let changed = true;
  while (changed) {
    changed = false;
    for (const fromKey of Object.keys(callEdges)) {
      const [fcls, fm] = fromKey.split(".");
      if (!effects[fcls] || !effects[fcls][fm]) continue;
      for (const [tcls, tm] of callEdges[fromKey]) {
        if (!effects[tcls] || !effects[tcls][tm]) continue;
        for (const e of effects[tcls][tm]) {
          if (!effects[fcls][fm].has(e)) {
            effects[fcls][fm].add(e);
            changed = true;
          }
        }
      }
    }
  }

  return effects;
}

// ----------------------------------------------------------------------
// Public entry

export function runTypeCheck(ast, opts = {}) {
  const classFieldTypes = buildFieldTypes(ast);
  const methodSigs = buildMethodSigs(ast, classFieldTypes);
  checkProgram(ast, classFieldTypes, methodSigs);
  const effects = collectMethodEffects(ast);
  // Serialize as plain strings for callers (e.g. server.mjs JSON).
  const effectsStr = {};
  for (const c of Object.keys(effects)) {
    effectsStr[c] = {};
    for (const m of Object.keys(effects[c])) {
      effectsStr[c][m] = effFmt(effects[c][m]) || "pure";
    }
  }
  return { classFieldTypes, methodSigs, effects, effectsStr };
}
