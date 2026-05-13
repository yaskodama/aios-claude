"""aipl_infer.py — Hindley-Milner type inference for AIPL (Python port).

This module is the type-checker for `python-aipl-inferred`, a sibling
runtime to `python-aipl` that replaces annotation-based gradual typing
with full HM inference.  The algorithm is a direct port of the OCaml
runtime's `src/infer.ml` + `src/types.ml` + `src/typing_env.ml` to
Python.

Annotations on `var`/`method`/`function` AST nodes are *ignored*
(retained for backward compatibility with existing samples but never
consulted).  Types are inferred from literals, initializers, call
sites, and operator overloads via unification.

Public entry:
    check_program(program) -> InferResult
        InferResult.ok          : bool
        InferResult.errors      : list[str]
        InferResult.warnings    : list[str]
        InferResult.class_fields: dict[str, dict[str, str]]
        InferResult.class_methods: dict[str, dict[str, str]]

On a type error, `ok` is False and `errors` lists the messages; the
caller is expected to hard-fail (consistent with the C / browser-abcl
implementations of full type checking).
"""

from __future__ import annotations

import sys
import os
from dataclasses import dataclass, field
from typing import Optional

# Reuse the existing python-aipl AST + parser from the sibling dir.
_SIB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "python-aipl")
if _SIB not in sys.path:
    sys.path.insert(0, _SIB)

import aipl_ast as A  # noqa: E402


# =====================================================================
# Types — direct port of OCaml types.ml
# =====================================================================

class Ty:
    """Base class for AIPL types.

    Subclasses:
      TVar   — mutable union-find type variable
      TInt / TFloat / TString / TBool / TUnit / TAny — concrete leaves
      TFun(params, ret)
      TActor(cls_name)
      TArray(elem)
      TRecord(fields: list[(name, Ty)])
      TTuple(elems: list[Ty])
    """
    __slots__ = ()


_tvar_counter = 0


class TVar(Ty):
    __slots__ = ("id", "link")

    def __init__(self):
        global _tvar_counter
        _tvar_counter += 1
        self.id: int = _tvar_counter
        self.link: Optional[Ty] = None

    def __repr__(self):
        if self.link is None:
            return f"'a{self.id}"
        return repr(self.link)


class TInt(Ty):
    __slots__ = ()
    def __repr__(self): return "int"


class TFloat(Ty):
    __slots__ = ()
    def __repr__(self): return "float"


class TString(Ty):
    __slots__ = ()
    def __repr__(self): return "string"


class TBool(Ty):
    __slots__ = ()
    def __repr__(self): return "bool"


class TUnit(Ty):
    __slots__ = ()
    def __repr__(self): return "unit"


class TAny(Ty):
    __slots__ = ()
    def __repr__(self): return "any"


class TFun(Ty):
    __slots__ = ("params", "ret")
    def __init__(self, params: list[Ty], ret: Ty):
        self.params = params
        self.ret = ret
    def __repr__(self):
        ps = ", ".join(repr(p) for p in self.params)
        return f"({ps}) -> {self.ret!r}"


class TActor(Ty):
    __slots__ = ("cls",)
    def __init__(self, cls: str):
        self.cls = cls
    def __repr__(self):
        return f"actor({self.cls})" if self.cls else "actor()"


class TArray(Ty):
    __slots__ = ("elem",)
    def __init__(self, elem: Ty):
        self.elem = elem
    def __repr__(self):
        return f"array({self.elem!r})"


class TRecord(Ty):
    __slots__ = ("fields",)
    def __init__(self, fields: list[tuple[str, Ty]]):
        self.fields = fields
    def __repr__(self):
        fs = "; ".join(f"{n}: {t!r}" for n, t in self.fields)
        return "{" + fs + "}"


class TTuple(Ty):
    __slots__ = ("elems",)
    def __init__(self, elems: list[Ty]):
        self.elems = elems
    def __repr__(self):
        return "(" + ", ".join(repr(e) for e in self.elems) + ")"


# Singleton instances for atomic types
T_INT = TInt()
T_FLOAT = TFloat()
T_STRING = TString()
T_BOOL = TBool()
T_UNIT = TUnit()
T_ANY = TAny()


@dataclass
class Scheme:
    """Universally quantified type:  Forall qs. t

    qs is a list of TVar ids that are generalized.  Used for
    let-polymorphism on global functions and class methods.
    """
    qs: list[int]
    t: Ty


# =====================================================================
# Repr / occurs / unify
# =====================================================================

def repr_ty(t: Ty) -> Ty:
    """Follow TVar.link chain to the representative."""
    if isinstance(t, TVar):
        if t.link is None:
            return t
        end = repr_ty(t.link)
        t.link = end  # path compression
        return end
    return t


def occurs(v: TVar, t: Ty) -> bool:
    t = repr_ty(t)
    if isinstance(t, TVar):
        return t is v
    if isinstance(t, TFun):
        return any(occurs(v, p) for p in t.params) or occurs(v, t.ret)
    if isinstance(t, TArray):
        return occurs(v, t.elem)
    if isinstance(t, TRecord):
        return any(occurs(v, ft) for _, ft in t.fields)
    if isinstance(t, TTuple):
        return any(occurs(v, e) for e in t.elems)
    return False


class TypeError_(Exception):
    """Raised on unrecoverable type mismatch."""
    pass


def unify(a: Ty, b: Ty) -> None:
    a = repr_ty(a)
    b = repr_ty(b)
    if a is b:
        return
    if isinstance(a, TAny) or isinstance(b, TAny):
        return  # any is compatible with anything
    if isinstance(a, TVar):
        if occurs(a, b):
            raise TypeError_(f"occurs check: 'a{a.id} in {b!r}")
        a.link = b
        return
    if isinstance(b, TVar):
        if occurs(b, a):
            raise TypeError_(f"occurs check: 'a{b.id} in {a!r}")
        b.link = a
        return
    # Atomic leaves
    if type(a) is type(b) and isinstance(a, (TInt, TFloat, TString, TBool, TUnit)):
        return
    if isinstance(a, TActor) and isinstance(b, TActor):
        # Empty class name acts as wildcard (e.g. sender returns "")
        if a.cls == b.cls or a.cls == "" or b.cls == "":
            return
        raise TypeError_(f"actor class mismatch: {a.cls} vs {b.cls}")
    if isinstance(a, TFun) and isinstance(b, TFun):
        if len(a.params) != len(b.params):
            raise TypeError_(f"arity mismatch: {a!r} vs {b!r}")
        for p, q in zip(a.params, b.params):
            unify(p, q)
        unify(a.ret, b.ret)
        return
    if isinstance(a, TArray) and isinstance(b, TArray):
        unify(a.elem, b.elem); return
    if isinstance(a, TTuple) and isinstance(b, TTuple):
        if len(a.elems) != len(b.elems):
            raise TypeError_(f"tuple arity mismatch: {a!r} vs {b!r}")
        for x, y in zip(a.elems, b.elems):
            unify(x, y)
        return
    if isinstance(a, TRecord) and isinstance(b, TRecord):
        ka = {n: t for n, t in a.fields}
        kb = {n: t for n, t in b.fields}
        if set(ka) != set(kb):
            raise TypeError_(f"record fields differ: {a!r} vs {b!r}")
        for n in ka:
            unify(ka[n], kb[n])
        return
    raise TypeError_(f"cannot unify {a!r} with {b!r}")


def unify_try(a: Ty, b: Ty) -> bool:
    try:
        unify(a, b)
        return True
    except TypeError_:
        return False


# =====================================================================
# Free type variables / generalize / instantiate
# =====================================================================

def ftv(t: Ty) -> set[int]:
    t = repr_ty(t)
    if isinstance(t, TVar):
        return {t.id}
    if isinstance(t, TFun):
        out: set[int] = set()
        for p in t.params: out |= ftv(p)
        out |= ftv(t.ret)
        return out
    if isinstance(t, TArray):
        return ftv(t.elem)
    if isinstance(t, TRecord):
        out = set()
        for _, ft in t.fields: out |= ftv(ft)
        return out
    if isinstance(t, TTuple):
        out = set()
        for e in t.elems: out |= ftv(e)
        return out
    return set()


def ftv_scheme(s: Scheme) -> set[int]:
    return ftv(s.t) - set(s.qs)


def ftv_env(env: dict[str, list[Scheme]]) -> set[int]:
    out: set[int] = set()
    for schemes in env.values():
        for sch in schemes:
            out |= ftv_scheme(sch)
    return out


def generalize(env_ftv: set[int], t: Ty) -> Scheme:
    qs = sorted(ftv(t) - env_ftv)
    return Scheme(qs, t)


def instantiate(sch: Scheme) -> Ty:
    """Replace each quantified id with a fresh TVar."""
    if not sch.qs:
        return sch.t
    subst: dict[int, TVar] = {q: TVar() for q in sch.qs}

    def go(t: Ty) -> Ty:
        t = repr_ty(t)
        if isinstance(t, TVar):
            return subst.get(t.id, t)
        if isinstance(t, TFun):
            return TFun([go(p) for p in t.params], go(t.ret))
        if isinstance(t, TArray):
            return TArray(go(t.elem))
        if isinstance(t, TRecord):
            return TRecord([(n, go(ft)) for n, ft in t.fields])
        if isinstance(t, TTuple):
            return TTuple([go(e) for e in t.elems])
        return t

    return go(sch.t)


# =====================================================================
# Class method / field registry — populated during preinfer
# =====================================================================

_class_method_schemes: dict[str, list[tuple[str, Scheme]]] = {}
_class_field_types: dict[str, list[tuple[str, Ty]]] = {}


def lookup_method_scheme(cls: str, mname: str) -> Optional[Scheme]:
    for n, s in _class_method_schemes.get(cls, []):
        if n == mname:
            return s
    return None


def reset_registries():
    _class_method_schemes.clear()
    _class_field_types.clear()


# =====================================================================
# Builtin signatures (prelude) — mirrors OCaml typing_env.ml
# =====================================================================

def make_prelude() -> dict[str, list[Scheme]]:
    env: dict[str, list[Scheme]] = {}

    def add_mono(name: str, t: Ty):
        env.setdefault(name, []).append(Scheme([], t))

    def add_poly(name: str, qs: list[int], t: Ty):
        env.setdefault(name, []).append(Scheme(qs, t))

    # f : float -> float
    for f in ["sin", "cos", "tan", "asin", "acos", "atan",
              "sqrt", "exp", "log10", "abs", "floor", "ceil", "round"]:
        add_mono(f, TFun([T_FLOAT], T_FLOAT))

    # print : forall a. a -> unit
    a = TVar()
    add_poly("print", [a.id], TFun([a], T_UNIT))

    # Binary arithmetic — int/int, float/float, mixed
    for op in ["+", "-", "*", "/"]:
        add_mono(op, TFun([T_FLOAT, T_FLOAT], T_FLOAT))
        add_mono(op, TFun([T_INT, T_INT], T_INT))
        add_mono(op, TFun([T_INT, T_FLOAT], T_FLOAT))
        add_mono(op, TFun([T_FLOAT, T_INT], T_FLOAT))

    # Comparison: returns bool
    for op in [">", "<", "<=", ">=", "==", "!="]:
        add_mono(op, TFun([T_FLOAT, T_FLOAT], T_BOOL))
        add_mono(op, TFun([T_INT, T_INT], T_BOOL))
    add_mono("==", TFun([T_STRING, T_STRING], T_BOOL))
    add_mono("!=", TFun([T_STRING, T_STRING], T_BOOL))

    # String concatenation: + with one side string => string
    a = TVar()
    add_poly("+", [a.id], TFun([T_STRING, a], T_STRING))
    a = TVar()
    add_poly("+", [a.id], TFun([a, T_STRING], T_STRING))

    # reply : forall a. a -> unit
    a = TVar()
    add_poly("reply", [a.id], TFun([a], T_UNIT))

    # wait : int|float -> unit
    add_mono("wait", TFun([T_INT], T_UNIT))
    add_mono("wait", TFun([T_FLOAT], T_UNIT))

    # Future / await — async send returning a future handle that
    # await(f) blocks on.  Both are runtime-defined; treat as
    # polymorphic identity-ish for the type checker.
    a = TVar()
    add_poly("await", [a.id], TFun([a], a))

    # AI builtins (mirror OCaml prelude).  Each ai_call_* accepts an
    # optional leading provider id (int 1..3 = gemini/anthropic/openai)
    # or omits it for env-driven auto-select.
    add_mono("ai_call",                       TFun([T_STRING], T_STRING))
    add_mono("ai_call",                       TFun([T_INT, T_STRING], T_STRING))
    add_mono("ai_call_with_system",           TFun([T_STRING, T_STRING], T_STRING))
    add_mono("ai_call_with_system",           TFun([T_INT, T_STRING, T_STRING], T_STRING))
    add_mono("ai_usage",                      TFun([], T_STRING))
    add_mono("ai_remaining",                  TFun([], T_INT))
    add_mono("ai_cost",                       TFun([], T_FLOAT))
    add_mono("ai_call_retry",                 TFun([T_INT, T_STRING], T_STRING))
    add_mono("ai_call_retry",                 TFun([T_INT, T_INT, T_STRING], T_STRING))
    add_mono("ai_call_retry_with_system",     TFun([T_INT, T_STRING, T_STRING], T_STRING))
    add_mono("ai_call_retry_with_system",     TFun([T_INT, T_INT, T_STRING, T_STRING], T_STRING))

    # Web gateway
    add_mono("web_listen", TFun([T_INT], T_UNIT))
    add_mono("web_listen", TFun([T_FLOAT], T_UNIT))
    add_mono("web_expose", TFun([T_STRING, T_STRING], T_UNIT))

    # WebSocket (Phase 3 of WS rollout)
    add_mono("ws_listen", TFun([T_INT], T_INT))
    add_mono("ws_send",   TFun([T_STRING, T_STRING], T_INT))
    add_mono("ws_send",   TFun([T_STRING, T_STRING, T_INT], T_INT))
    add_mono("ws_close",  TFun([T_INT], T_UNIT))
    add_mono("ws_status", TFun([], T_ANY))

    add_mono("spawn", TFun([T_STRING, T_STRING], T_UNIT))

    # typeof : forall a. a -> string
    a = TVar()
    add_poly("typeof", [a.id], TFun([a], T_STRING))

    # Arrays
    a = TVar(); add_poly("array_empty", [a.id], TFun([], TArray(a)))
    a = TVar(); add_poly("array_len",   [a.id], TFun([TArray(a)], T_INT))
    a = TVar(); add_poly("array_get",   [a.id], TFun([TArray(a), T_INT], a))
    a = TVar(); add_poly("array_set",   [a.id], TFun([TArray(a), T_INT, a], TArray(a)))
    a = TVar(); add_poly("array_push",  [a.id], TFun([TArray(a), a], TArray(a)))

    return env


# =====================================================================
# Overload resolution — port of pick_overload
# =====================================================================

_warned_unknown: set[str] = set()


def pick_overload(name: str, env: dict[str, list[Scheme]], arg_tys: list[Ty]) -> Ty:
    schemes = env.get(name, [])
    if not schemes:
        # Gradual: unknown name treated as any-typed
        if name not in _warned_unknown:
            _warned_unknown.add(name)
            print(f"[type warning] unknown function '{name}' treated as gradual (any -> any)",
                  file=sys.stderr)
        return TVar()

    # Try each scheme; return first matching one
    for sch in schemes:
        inst = repr_ty(instantiate(sch))
        if isinstance(inst, TFun) and len(inst.params) == len(arg_tys):
            saved = [_snapshot(t) for t in inst.params + [inst.ret] + arg_tys]
            ok = all(unify_try(p, a) for p, a in zip(inst.params, arg_tys))
            if ok:
                return repr_ty(inst.ret)
            _restore(saved)

    # Gradual fallback: no overload matched, but the name is known.
    # Match the OCaml/JS-server policy of warn-and-continue so existing
    # samples that pass loose-typed args to overloaded builtins keep
    # working.  Hard type errors still come from explicit mismatches in
    # unify within user-defined sends and method bodies.
    if name not in _warned_unknown:
        _warned_unknown.add(name)
        sig = "(" + ", ".join(repr(a) for a in arg_tys) + ")"
        print(f"[type warning] no overload of {name!r} matches {sig} — gradual fallback",
              file=sys.stderr)
    return TVar()


def _snapshot(t: Ty) -> tuple:
    """Capture the current link state of all TVars reachable from t."""
    captured = []
    def walk(x):
        x = repr_ty(x)
        if isinstance(x, TVar):
            captured.append((x, x.link))
        elif isinstance(x, TFun):
            for p in x.params: walk(p)
            walk(x.ret)
        elif isinstance(x, TArray):
            walk(x.elem)
        elif isinstance(x, TRecord):
            for _, ft in x.fields: walk(ft)
        elif isinstance(x, TTuple):
            for e in x.elems: walk(e)
    walk(t)
    return captured


def _restore(snapshots):
    for snap in snapshots:
        for tv, link in snap:
            tv.link = link


# =====================================================================
# Expression / statement inference
# =====================================================================

# Module-scope state per check_program run (cleared at entry)
_in_preinfer = False


def infer_expr(env: dict[str, list[Scheme]], e) -> Ty:
    if isinstance(e, A.IntLit):
        return T_INT
    if isinstance(e, A.FloatLit):
        return T_FLOAT
    if isinstance(e, A.StringLit):
        return T_STRING
    if isinstance(e, A.Var):
        if e.name == "sender":
            return T_ANY
        if e.name == "self":
            return T_ANY
        schemes = env.get(e.name, [])
        if schemes:
            return instantiate(schemes[0])
        # Gradual: unbound name is a fresh tvar with a warning.  Mostly
        # surfaces in samples that read function names or builtins that
        # we haven't pre-registered.  A real undefined identifier shows
        # up later as a unify failure at the use site.
        if e.name not in _warned_unknown:
            _warned_unknown.add(e.name)
            print(f"[type warning] unbound variable '{e.name}' treated as gradual",
                  file=sys.stderr)
        return TVar()
    if isinstance(e, A.Binop):
        t1 = infer_expr(env, e.lhs)
        t2 = infer_expr(env, e.rhs)
        r1 = repr_ty(t1); r2 = repr_ty(t2)
        if e.op == "+" and (isinstance(r1, TString) or isinstance(r2, TString)):
            return T_STRING
        return pick_overload(e.op, env, [t1, t2])
    if isinstance(e, A.Neg):
        t = infer_expr(env, e.inner)
        return t
    if isinstance(e, A.CallExpr):
        targs = [infer_expr(env, a) for a in e.args]
        return pick_overload(e.name, env, targs)
    if isinstance(e, A.New):
        targs = [infer_expr(env, a) for a in e.args]
        sch = lookup_method_scheme(e.cls_name, "init")
        if sch is not None:
            inst = repr_ty(instantiate(sch))
            if isinstance(inst, TFun):
                if len(inst.params) == len(targs):
                    for p, a in zip(inst.params, targs):
                        try: unify(p, a)
                        except TypeError_ as ex:
                            raise TypeError_(f"new {e.cls_name}: {ex}") from ex
        return TActor(e.cls_name)
    if isinstance(e, A.NowCall):
        # Synchronous send — typed as the receiver method's return
        targs = [infer_expr(env, a) for a in e.args]
        # Resolve target type from env if available
        tgt_ty: Optional[Ty] = None
        if e.target in env and env[e.target]:
            tgt_ty = repr_ty(instantiate(env[e.target][0]))
        if isinstance(tgt_ty, TActor):
            sch = lookup_method_scheme(tgt_ty.cls, e.method)
            if sch is not None:
                inst = repr_ty(instantiate(sch))
                if isinstance(inst, TFun) and len(inst.params) == len(targs):
                    for p, a in zip(inst.params, targs):
                        try: unify(p, a)
                        except TypeError_: pass
                    return inst.ret
        return TVar()
    if isinstance(e, A.FutureCall):
        # Return type is a future handle — treat as TAny
        for a in e.args:
            infer_expr(env, a)
        return T_ANY
    if isinstance(e, A.ArrayLit):
        if not e.items:
            return TArray(TVar())
        ts = [infer_expr(env, x) for x in e.items]
        t0 = ts[0]
        for t in ts[1:]:
            try: unify(t0, t)
            except TypeError_: pass
        return TArray(t0)
    if isinstance(e, A.ArraySized):
        # ArraySized(size, init) — len is int, value is any
        return TArray(TVar())
    if isinstance(e, A.IndexExpr):
        # Array indexing — result is element type
        sch_list = env.get(e.name, [])
        if sch_list:
            t = repr_ty(instantiate(sch_list[0]))
            if isinstance(t, TArray):
                return t.elem
        return T_ANY
    if isinstance(e, A.RecordLit):
        fts = [(n, infer_expr(env, ex)) for n, ex in e.fields]
        return TRecord(fts)
    if isinstance(e, A.TupleLit):
        return TTuple([infer_expr(env, ex) for ex in e.items])
    if isinstance(e, A.FieldAccess):
        sch_list = env.get(e.name, [])
        t = repr_ty(instantiate(sch_list[0])) if sch_list else T_ANY
        for attr in e.attrs:
            if isinstance(t, TRecord):
                found = next((ft for n, ft in t.fields if n == attr), None)
                t = found if found is not None else T_ANY
            else:
                t = T_ANY
        return t
    # Fallthrough: any unknown node type is gradual
    return T_ANY


def check_stmt(env: dict[str, list[Scheme]], s) -> None:
    if isinstance(s, A.Block):
        for x in s.stmts:
            check_stmt(env, x)
        return
    if isinstance(s, A.VarDecl):
        t = infer_expr(env, s.expr)
        env[s.name] = [Scheme([], t)]
        return
    if isinstance(s, A.VarNew):
        # var x = new Cls(args)
        targs = [infer_expr(env, a) for a in s.args]
        sch = lookup_method_scheme(s.cls_name, "init")
        if sch is not None:
            inst = repr_ty(instantiate(sch))
            if isinstance(inst, TFun) and len(inst.params) == len(targs):
                for p, a in zip(inst.params, targs):
                    try: unify(p, a)
                    except TypeError_ as ex:
                        raise TypeError_(f"new {s.cls_name}: {ex}") from ex
        env[s.name] = [Scheme([], TActor(s.cls_name))]
        return
    if isinstance(s, A.Assign):
        t = infer_expr(env, s.expr)
        if s.name in env and env[s.name]:
            try: unify(repr_ty(instantiate(env[s.name][0])), t)
            except TypeError_:
                # Gradual widening: replace with TAny
                env[s.name] = [Scheme([], T_ANY)]
        else:
            env[s.name] = [Scheme([], t)]
        return
    if isinstance(s, A.IndexAssign) or isinstance(s, A.FieldAssign):
        if hasattr(s, 'expr'):
            infer_expr(env, s.expr)
        return
    if isinstance(s, A.Send):
        # send target.method(args) — check arg types against method scheme
        targs = [infer_expr(env, a) for a in s.args]
        if s.target in env and env[s.target]:
            tgt = repr_ty(instantiate(env[s.target][0]))
            if isinstance(tgt, TActor):
                sch = lookup_method_scheme(tgt.cls, s.method)
                if sch is None:
                    raise TypeError_(
                        f"no method {s.method} in actor({tgt.cls})")
                inst = repr_ty(instantiate(sch))
                if isinstance(inst, TFun):
                    if len(inst.params) != len(targs):
                        raise TypeError_(
                            f"{tgt.cls}.{s.method}: arity {len(inst.params)} vs {len(targs)}")
                    for p, a in zip(inst.params, targs):
                        try: unify(p, a)
                        except TypeError_ as ex:
                            raise TypeError_(
                                f"{tgt.cls}.{s.method}: {ex}") from ex
        return
    if isinstance(s, A.CallStmt):
        targs = [infer_expr(env, a) for a in s.args]
        try:
            pick_overload(s.name, env, targs)
        except TypeError_:
            pass
        return
    if isinstance(s, A.If):
        infer_expr(env, s.cond)
        check_stmt(env, s.then_body)
        if getattr(s, 'else_body', None) is not None:
            check_stmt(env, s.else_body)
        return
    if isinstance(s, A.While):
        infer_expr(env, s.cond)
        check_stmt(env, s.body)
        return
    if isinstance(s, A.Become):
        for a in s.args:
            infer_expr(env, a)
        return
    if isinstance(s, A.Return):
        if s.expr is not None:
            infer_expr(env, s.expr)
        return
    if isinstance(s, A.Scope):
        check_stmt(env, s.body)
        return
    if isinstance(s, A.Spawn):
        for a in s.args:
            infer_expr(env, a)
        return
    # Unknown statement — silently accept (gradual)


# =====================================================================
# Class preinference (gather field types + method schemes)
# =====================================================================

def _join_types(a: Ty, b: Ty) -> Ty:
    """Least upper bound for field widening — monotonic; anything that
    includes TAny stays TAny. Tries unification first so fresh tvars
    (e.g. method parameters during a pre-pass) get bound to the field
    type. Numeric int ⊔ float promotes to float."""
    ra = repr_ty(a); rb = repr_ty(b)
    if ra is rb:
        return ra
    if isinstance(ra, TAny) or isinstance(rb, TAny):
        return T_ANY
    # Try to unify — succeeds for matching types and for any TVar pair
    if unify_try(ra, rb):
        return repr_ty(ra)
    # Numeric promotion
    if (isinstance(ra, TInt) and isinstance(rb, TFloat)) or \
       (isinstance(ra, TFloat) and isinstance(rb, TInt)):
        return T_FLOAT
    return T_ANY


def _walk_for_field_assigns(node, cls_name: str, env: dict):
    """Visit every Assign whose target is a class field. Widen the
    field's recorded type via _join_types on each occurrence.
    """
    if node is None:
        return
    if isinstance(node, A.Block):
        for s in node.stmts:
            _walk_for_field_assigns(s, cls_name, env)
        return
    if isinstance(node, A.Assign):
        # Is this a field of this class?
        fts = _class_field_types.get(cls_name, [])
        idx = next((i for i, (n, _) in enumerate(fts) if n == node.name), -1)
        if idx >= 0:
            rhs = infer_expr(env, node.expr)
            cur = fts[idx][1]
            fts[idx] = (node.name, _join_types(cur, rhs))
        # Recurse into expr too (handles nested assigns in expressions, unusual)
        return
    if isinstance(node, A.If):
        _walk_for_field_assigns(node.then_body, cls_name, env)
        if getattr(node, 'else_body', None) is not None:
            _walk_for_field_assigns(node.else_body, cls_name, env)
        return
    if isinstance(node, A.While):
        _walk_for_field_assigns(node.body, cls_name, env)
        return
    if isinstance(node, A.Scope):
        _walk_for_field_assigns(node.body, cls_name, env)
        return


def preinfer_class(env: dict[str, list[Scheme]], cls):
    env_cls = dict(env)
    field_types: list[tuple[str, Ty]] = []

    for f in cls.fields:
        t = infer_expr(env_cls, f.expr)
        field_types.append((f.name, repr_ty(t)))
        env_cls[f.name] = [Scheme([], t)]

    _class_field_types[cls.name] = field_types

    schemes: list[tuple[str, Scheme]] = []
    for md in cls.methods:
        env_m = dict(env_cls)
        env_m["self"] = [Scheme([], TActor(cls.name))]
        ps = []
        for p in md.params:
            tv = TVar()
            env_m[p] = [Scheme([], tv)]
            ps.append(tv)
        # Don't walk body yet (matches OCaml's design)
        tfun = TFun(ps, T_UNIT)
        sch = generalize(ftv_env(env_m), tfun)
        schemes.append((md.name, sch))

    _class_method_schemes[cls.name] = schemes

    # Pass 1b — widen field types based on assigns in method bodies.
    # This catches sentinel patterns like `var partner = 0;` later
    # bound to an actor reference, which pure HM would flag as
    # int / actor mismatch.  Widening to TAny matches the gradual
    # semantics used by browser-abcl and the OCaml runtime in practice.
    for md in cls.methods:
        env_m = dict(env_cls)
        env_m["self"] = [Scheme([], TActor(cls.name))]
        for p in md.params:
            env_m[p] = [Scheme([], TVar())]
        _walk_for_field_assigns(md.body, cls.name, env_m)


def prebind_global_actors(env: dict[str, list[Scheme]], program):
    for d in program.decls:
        if isinstance(d, A.GlobalStmt):
            s = d.stmt
            if isinstance(s, A.VarNew):
                env[s.name] = [Scheme([], TActor(s.cls_name))]


# =====================================================================
# Top-level check
# =====================================================================

@dataclass
class InferResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    class_fields: dict[str, dict[str, str]] = field(default_factory=dict)
    class_methods: dict[str, dict[str, str]] = field(default_factory=dict)


def check_program(program) -> InferResult:
    global _in_preinfer
    reset_registries()
    _warned_unknown.clear()
    env = make_prelude()

    try:
        prebind_global_actors(env, program)
        # Pre-register top-level FunctionDecl as polymorphic schemes so
        # `function f(a,b) { ... } ... f(1, 2)` doesn't see f as unbound.
        for d in program.decls:
            if isinstance(d, A.FunctionDecl):
                ps = [TVar() for _ in d.params]
                ret = TVar()
                tfun = TFun(ps, ret)
                sch = generalize(set(), tfun)
                env.setdefault(d.name, []).append(sch)
        _in_preinfer = True
        for d in program.decls:
            if isinstance(d, A.ClassDecl):
                preinfer_class(env, d)
        _in_preinfer = False

        # Walk method bodies and global statements (body check pass).
        # IMPORTANT: each method body gets fresh TVars for its params,
        # not the ones from the scheme.  Reusing scheme TVars would
        # leak unifications between sibling call sites — e.g. an
        # assignment to a field of known type would constrain the
        # original scheme and trigger spurious errors at later calls.
        for d in program.decls:
            if isinstance(d, A.ClassDecl):
                for md in d.methods:
                    env_m = dict(env)
                    for fname, ft in _class_field_types.get(d.name, []):
                        env_m[fname] = [Scheme([], ft)]
                    env_m["self"] = [Scheme([], TActor(d.name))]
                    for p in md.params:
                        env_m[p] = [Scheme([], TVar())]
                    check_stmt(env_m, md.body)
            elif isinstance(d, A.FunctionDecl):
                env_f = dict(env)
                for p in d.params:
                    env_f[p] = [Scheme([], TVar())]
                check_stmt(env_f, d.body)
            elif isinstance(d, A.GlobalStmt):
                check_stmt(env, d.stmt)
    except TypeError_ as ex:
        return InferResult(ok=False, errors=[str(ex)])

    # Serialize results for reporting
    result = InferResult(ok=True)
    for cls, fields in _class_field_types.items():
        result.class_fields[cls] = {n: repr(repr_ty(t)) for n, t in fields}
    for cls, methods in _class_method_schemes.items():
        result.class_methods[cls] = {n: repr(repr_ty(s.t)) for n, s in methods}
    return result


def render_result(r: InferResult) -> str:
    """Pretty-print the inference result (for --dump-types)."""
    lines: list[str] = []
    lines.append(f"=== inferred types (ok={r.ok}) ===")
    for cls in sorted(r.class_fields):
        lines.append(f"class {cls}:")
        for fname, fty in r.class_fields[cls].items():
            lines.append(f"  field  {fname} : {fty}")
        for mname, mty in r.class_methods.get(cls, {}).items():
            lines.append(f"  method {mname} : {mty}")
    if r.errors:
        lines.append("=== errors ===")
        for e in r.errors:
            lines.append(f"  {e}")
    return "\n".join(lines)
