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

function isConcrete(t) {
  return t !== ANY && t !== "unit";
}

function compatible(a, b) {
  // any matches anything
  if (a === ANY || b === ANY) return true;
  if (a === b) return true;
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
// Public entry

export function runTypeCheck(ast, opts = {}) {
  const classFieldTypes = buildFieldTypes(ast);
  const methodSigs = buildMethodSigs(ast, classFieldTypes);
  checkProgram(ast, classFieldTypes, methodSigs);
  return { classFieldTypes, methodSigs };
}
