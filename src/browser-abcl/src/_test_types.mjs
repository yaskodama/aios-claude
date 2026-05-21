// _test_types.mjs — Phase 1-3 unit tests for types.js.
// Run with:  node --test src/browser-abcl/src/_test_types.mjs

import test from "node:test";
import assert from "node:assert/strict";

import * as T from "./types.js";

function tvar() { return T.TVar(T.freshTvar()); }
function withRowPoly(fn) {
  const prev = globalThis.AIPL_ROWPOLY;
  globalThis.AIPL_ROWPOLY = "1";
  try { fn(); } finally { globalThis.AIPL_ROWPOLY = prev; }
}

test("singletons", () => {
  assert.equal(T.TInt.tag,    "TInt");
  assert.equal(T.TFloat.tag,  "TFloat");
  assert.equal(T.TBool.tag,   "TBool");
  assert.equal(T.TString.tag, "TString");
  assert.equal(T.TUnit.tag,   "TUnit");
  assert.equal(T.TAny.tag,    "TAny");
});

test("fresh tvars get unique ids", () => {
  T.resetForTypecheck();
  const a = T.freshTvar(), b = T.freshTvar();
  assert.notEqual(a.id, b.id);
});

test("repr returns self on unlinked tvar", () => {
  const v = tvar();
  assert.equal(T.repr(v), v);
});

test("repr follows link + compresses path", () => {
  const v1 = T.freshTvar();
  const v2 = T.freshTvar();
  v1.link = T.TVar(v2);
  v2.link = T.TInt;
  const r = T.repr(T.TVar(v1));
  assert.equal(r.tag, "TInt");
  // After compression, v1.link should bypass v2 directly to TInt.
  assert.equal(v1.link, T.TInt);
});

test("unify int + int", () => {
  T.unify(T.TInt, T.TInt);   // no throw
});

test("unify int + float throws", () => {
  assert.throws(() => T.unify(T.TInt, T.TFloat), T.TypeError);
});

test("unify tvar with int binds tvar to int", () => {
  const v = T.freshTvar();
  T.unify(T.TVar(v), T.TInt);
  assert.equal(T.repr(T.TVar(v)).tag, "TInt");
});

test("unify tvar with tvar (transitive)", () => {
  const a = T.freshTvar(), b = T.freshTvar();
  T.unify(T.TVar(a), T.TVar(b));
  T.unify(T.TVar(b), T.TFloat);
  assert.equal(T.repr(T.TVar(a)).tag, "TFloat");
});

test("occurs check fails for direct cycle", () => {
  const v = T.freshTvar();
  assert.throws(() => T.unify(T.TVar(v), T.TArray(T.TVar(v))), /occurs/);
});

test("TAny absorbs both directions", () => {
  T.unify(T.TAny, T.TInt);
  T.unify(T.TInt, T.TAny);
  // No throw.
});

test("TArray element unify", () => {
  const v = T.freshTvar();
  T.unify(T.TArray(T.TVar(v)), T.TArray(T.TString));
  assert.equal(T.repr(T.TVar(v)).tag, "TString");
});

test("TTuple arity mismatch throws", () => {
  assert.throws(() => T.unify(T.TTuple([T.TInt]), T.TTuple([T.TInt, T.TInt])), T.TypeError);
});

test("TFun arity + return unify", () => {
  const v = T.freshTvar();
  T.unify(
    T.TFun([T.TInt], T.TVar(v)),
    T.TFun([T.TInt], T.TString)
  );
  assert.equal(T.repr(T.TVar(v)).tag, "TString");
});

test("TRecord width subtyping (CE-13)", () => {
  // Both sides have field `n`, only one has `m`.  Closed records →
  // common field unifies; disjoint check passes because intersection
  // is non-empty.
  T.unify(
    T.TRecord([["n", T.TInt], ["m", T.TInt]], null),
    T.TRecord([["n", T.TInt]], null)
  );
});

test("TRecord disjoint labels throws", () => {
  assert.throws(() =>
    T.unify(
      T.TRecord([["a", T.TInt]], null),
      T.TRecord([["b", T.TInt]], null)
    ), T.TypeError);
});

test("TRecord row poly (CE-16, opt-in)", () => {
  withRowPoly(() => {
    const rest = T.TVar(T.freshTvar());
    T.unify(
      T.TRecord([["n", T.TInt]], rest),
      T.TRecord([["n", T.TInt], ["m", T.TString]], null)
    );
    // The rest tail should now bind to the missing `m` field.
    const rep = T.repr(rest);
    assert.equal(rep.tag, "TRecord");
    assert.deepEqual(rep.fields.map(([l]) => l), ["m"]);
  });
});

test("unifyTry returns false on mismatch", () => {
  const ok = T.unifyTry(T.TInt, T.TString);
  assert.equal(ok, false);
});

test("generalize + instantiate yields fresh tvars", () => {
  T.resetForTypecheck();
  const v = T.freshTvar();
  const tyV = T.TVar(v);
  const scheme = T.generalize(new Set(), tyV);  // empty env → quantify v
  const inst1 = T.instantiate(scheme);
  const inst2 = T.instantiate(scheme);
  // Both instantiations are TVars but with DIFFERENT tvar identities.
  assert.equal(inst1.tag, "TVar");
  assert.equal(inst2.tag, "TVar");
  assert.notEqual(inst1.tv, inst2.tv);
  assert.notEqual(inst1.tv, v);
});

test("instantiate of monotype scheme returns same shape", () => {
  const scheme = T.Forall([], T.TInt);
  const inst = T.instantiate(scheme);
  assert.equal(inst, T.TInt);
});

test("class method scheme registry round-trip", () => {
  T.resetForTypecheck();
  T.registerClassAuto("Foo", [["bar", 2]]);
  const sch = T.lookupClassMethodScheme("Foo", "bar");
  assert.ok(sch);
  const ty = T.instantiate(sch);
  assert.equal(ty.tag, "TFun");
  assert.equal(ty.params.length, 2);
  assert.equal(ty.ret.tag, "TUnit");
});

test("class field type registry round-trip", () => {
  T.resetForTypecheck();
  T.registerClassFieldTypes("Bar", [["n", T.TInt], ["s", T.TString]]);
  assert.equal(T.lookupFieldType("Bar", "n").tag, "TInt");
  assert.equal(T.lookupFieldType("Bar", "s").tag, "TString");
  assert.equal(T.lookupFieldType("Bar", "missing"), null);
});

test("stringOfTyPretty renames tvars to 'a, 'b", () => {
  T.resetForTypecheck();
  const a = T.freshTvar(), b = T.freshTvar();
  const ty = T.TFun([T.TVar(a), T.TVar(b)], T.TVar(a));
  const s = T.stringOfTyPretty(ty);
  // Same tvar should reuse name; order: 'a then 'b
  assert.match(s, /'a/);
  assert.match(s, /'b/);
});

test("prune resolves linked vars", () => {
  T.resetForTypecheck();
  const v = T.freshTvar();
  v.link = T.TInt;
  const pruned = T.prune(T.TArray(T.TVar(v)));
  assert.equal(pruned.tag, "TArray");
  assert.equal(pruned.elt.tag, "TInt");
});

test("ftvTy collects free tvar ids", () => {
  T.resetForTypecheck();
  const a = T.freshTvar(), b = T.freshTvar();
  const ty = T.TFun([T.TVar(a)], T.TArray(T.TVar(b)));
  const ftv = T.ftvTy(ty);
  assert.ok(ftv.has(a.id));
  assert.ok(ftv.has(b.id));
});
