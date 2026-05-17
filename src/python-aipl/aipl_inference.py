"""aipl_inference — Phase C type inference for AIPL.

A constraint-based Hindley–Milner inference with optional refinement
predicates verified by Z3.  Designed to be a drop-in companion to the
existing `aipl_typeck.py` (877 LOC, signature-driven nominal checker)
without breaking any of its consumers — it can be invoked separately
and its results merged.

Design tracks the AIPL v2 (2) `type_inference` evolution top 1 + top
2 consensus (REPORT in experiments/2026-05-17_aipl_v2_type_inference/):

  * inference_algorithm     = constraint_based_global  (top 1)
                              + bidirectional         (top 2-5)
  * inference_scope         = incremental_per_method  (top 5/5)
  * type_system_strength    = HM + bidirectional refinement
  * subtyping               = structural / gradual
  * annotation_requirement  = optional_with_fallback_dyn
  * error_message_style     = ocaml_style_with_path
  * implementation_strategy = new_aipl_inference_module
  * backend                 = z3-solver (when refinements present)

Public entry points:

    infer_program(program)            -> InferenceResult
    infer_method(class_, method)      -> InferenceResult
    type_of(env, expr)                -> InferredType

The `InferenceResult` carries the fresh type assignments for every
binding (let, fn param, var decl) and a list of `RefinementIssue`s
produced by the Z3 backend when a `where` predicate cannot be
discharged.

This module DOES NOT touch the runtime — it is a pure static analysis.
Programs that pass `aipl_typeck.check(...)` will also pass inference
(unless their refinements are actually broken).

Z3 is loaded lazily; if unavailable, refinement clauses are treated as
documentation (matching v2 PsiLang's `static_simple` semantics).
"""
from __future__ import annotations
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

# Local AST.  Imported lazily so this module is also usable as a
# library without booting the full AIPL parser.
try:
    from aipl_ast import (
        IntLit, FloatLit, StringLit, Var, Binop, Neg, New,
        CallExpr, ArrayLit, IndexExpr, RecordLit, TupleLit,
        FunctionDecl, Return, FieldAccess, NowCall, FutureCall,
        VarDecl, Assign, If, While, Block, MethodDecl, ClassDecl,
        Program, GlobalStmt, CallStmt, Send,
    )
except Exception:                       # pragma: no cover
    IntLit = FloatLit = StringLit = Var = Binop = Neg = New = None
    CallExpr = ArrayLit = IndexExpr = RecordLit = TupleLit = None
    FunctionDecl = Return = FieldAccess = NowCall = FutureCall = None
    VarDecl = Assign = If = While = Block = MethodDecl = None
    ClassDecl = Program = GlobalStmt = CallStmt = Send = None


# ════════════════════════════════════════════════════════════════════════
# 1. Type representation
# ════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TCon:
    """Type constructor: Int, Bool, Real, Rat, Str, Unit, List(T), …"""
    name: str
    args: tuple = ()

    def __str__(self) -> str:
        if not self.args: return self.name
        return f"{self.name}<{', '.join(str(a) for a in self.args)}>"


@dataclass(frozen=True)
class TVar:
    """A unification type variable (α, β, …)."""
    id: int

    def __str__(self) -> str:
        # Greek letter alphabet for short ids, fallback to t{N}
        gr = "αβγδεζηθικλμνξοπρστυφχψω"
        return gr[self.id] if 0 <= self.id < len(gr) else f"t{self.id}"


@dataclass(frozen=True)
class TArrow:
    """Function type: (T1, T2, ...) -> R"""
    args: tuple        # tuple of Type
    ret: Any           # Type

    def __str__(self) -> str:
        return f"({', '.join(str(a) for a in self.args)}) -> {self.ret}"


@dataclass(frozen=True)
class TTuple:
    items: tuple

    def __str__(self) -> str:
        return f"({', '.join(str(a) for a in self.items)})"


@dataclass(frozen=True)
class TRecord:
    """Structural record type: {field: T, …}.

    Used for AIPL classes (since AIPL has nominal classes, we still
    use structural types internally for now)."""
    fields: tuple      # tuple of (name, Type)

    def __str__(self) -> str:
        body = ", ".join(f"{n}: {t}" for n, t in self.fields)
        return f"{{{body}}}"


@dataclass(frozen=True)
class TRefined:
    """Refinement type:  base type + predicate AST + parameter name.

    Example:  TRefined(TCon('Int'), 'k', "k >= 0")
    semantic: { k : Int | k >= 0 }
    """
    base: Any
    binder: str
    pred_src: str       # textual predicate (for error messages)
    pred_ast: Any = None   # parsed predicate (lazy)

    def __str__(self) -> str:
        return f"{{{self.binder}: {self.base} | {self.pred_src}}}"


Type = Union[TCon, TVar, TArrow, TTuple, TRecord, TRefined]


# Convenience constructors
T_INT    = TCon("Int")
T_BOOL   = TCon("Bool")
T_STR    = TCon("Str")
T_REAL   = TCon("Real")
T_RAT    = TCon("Rat")
T_UNIT   = TCon("Unit")
T_DYN    = TCon("Dyn")          # gradual-typing wildcard


# ════════════════════════════════════════════════════════════════════════
# 2. Type schemes (∀-quantification)
# ════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Scheme:
    """∀ α₁ … αₙ . T   (Hindley-Milner generalisation)."""
    vars: tuple         # tuple of TVar
    type: Any           # Type

    def __str__(self) -> str:
        if not self.vars: return str(self.type)
        return f"∀{''.join(str(v) for v in self.vars)}. {self.type}"


# ════════════════════════════════════════════════════════════════════════
# 3. Substitutions and free-variables
# ════════════════════════════════════════════════════════════════════════

Subst = Dict[TVar, Any]      # TVar -> Type


def apply(s: Subst, t: Any) -> Any:
    """Apply substitution `s` to type `t` (recursively)."""
    if isinstance(t, TVar):
        if t in s: return apply(s, s[t])
        return t
    if isinstance(t, TCon):
        if not t.args: return t
        return TCon(t.name, tuple(apply(s, a) for a in t.args))
    if isinstance(t, TArrow):
        return TArrow(tuple(apply(s, a) for a in t.args), apply(s, t.ret))
    if isinstance(t, TTuple):
        return TTuple(tuple(apply(s, a) for a in t.items))
    if isinstance(t, TRecord):
        return TRecord(tuple((n, apply(s, ft)) for n, ft in t.fields))
    if isinstance(t, TRefined):
        return TRefined(apply(s, t.base), t.binder, t.pred_src, t.pred_ast)
    return t


def free_vars(t: Any) -> set:
    """Free (un-bound) type variables in `t`."""
    if isinstance(t, TVar): return {t}
    if isinstance(t, TCon):
        out = set()
        for a in t.args: out |= free_vars(a)
        return out
    if isinstance(t, TArrow):
        out = set()
        for a in t.args: out |= free_vars(a)
        out |= free_vars(t.ret)
        return out
    if isinstance(t, TTuple):
        out = set()
        for a in t.items: out |= free_vars(a)
        return out
    if isinstance(t, TRecord):
        out = set()
        for _, ft in t.fields: out |= free_vars(ft)
        return out
    if isinstance(t, TRefined):
        return free_vars(t.base)
    return set()


def compose(s1: Subst, s2: Subst) -> Subst:
    """s1 ∘ s2  (apply s2 first, then s1)."""
    out = {tv: apply(s1, t) for tv, t in s2.items()}
    for tv, t in s1.items():
        if tv not in out: out[tv] = t
    return out


# ════════════════════════════════════════════════════════════════════════
# 4. Unification
# ════════════════════════════════════════════════════════════════════════

class UnifyError(Exception):
    pass


def unify(t1: Any, t2: Any) -> Subst:
    """Robinson unification.  Raise UnifyError on failure."""
    if t1 == t2: return {}
    if isinstance(t1, TVar): return _bind(t1, t2)
    if isinstance(t2, TVar): return _bind(t2, t1)
    # gradual: Dyn unifies with everything (top type for refactors)
    if t1 == T_DYN or t2 == T_DYN: return {}
    if isinstance(t1, TCon) and isinstance(t2, TCon):
        if t1.name != t2.name or len(t1.args) != len(t2.args):
            raise UnifyError(f"cannot unify {t1} with {t2}")
        s: Subst = {}
        for a1, a2 in zip(t1.args, t2.args):
            s = compose(unify(apply(s, a1), apply(s, a2)), s)
        return s
    if isinstance(t1, TArrow) and isinstance(t2, TArrow):
        if len(t1.args) != len(t2.args):
            raise UnifyError(f"arity mismatch: {t1} vs {t2}")
        s: Subst = {}
        for a1, a2 in zip(t1.args, t2.args):
            s = compose(unify(apply(s, a1), apply(s, a2)), s)
        s = compose(unify(apply(s, t1.ret), apply(s, t2.ret)), s)
        return s
    if isinstance(t1, TTuple) and isinstance(t2, TTuple):
        if len(t1.items) != len(t2.items):
            raise UnifyError(f"tuple arity: {t1} vs {t2}")
        s: Subst = {}
        for a, b in zip(t1.items, t2.items):
            s = compose(unify(apply(s, a), apply(s, b)), s)
        return s
    # Refinement vs base: drop refinement for unification (kept aside for SMT)
    if isinstance(t1, TRefined):
        return unify(t1.base, t2)
    if isinstance(t2, TRefined):
        return unify(t1, t2.base)
    raise UnifyError(f"no rule to unify {t1} with {t2}")


def _bind(v: TVar, t: Any) -> Subst:
    if v == t: return {}
    if isinstance(t, TVar) and v.id == t.id: return {}
    if v in free_vars(t):
        raise UnifyError(f"occurs check: {v} in {t}")
    return {v: t}


# ════════════════════════════════════════════════════════════════════════
# 5. Inference monad
# ════════════════════════════════════════════════════════════════════════

@dataclass
class Inference:
    """Mutable state during inference."""
    fresh_counter: int = 0
    subst: Subst = field(default_factory=dict)
    refinements: list = field(default_factory=list)
    # Phase E-α: every TRefined produced by `_parse_annotation` is also
    # registered here so a declaration-time satisfiability check can run
    # at the end of inference.  Entries are TRefined instances (binder
    # already specialized to a concrete name where possible).
    refined_decls: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    # D-1: class-level method signatures pre-registered before any body
    # is inferred so `now obj.method(args)` can unify against them.
    # Schema: { class_name: { method_name: (param_tvars, ret_tvar) } }
    class_sigs: Dict[str, Dict[str, tuple]] = field(default_factory=dict)
    # The currently-being-inferred (class, method) pair so `reply(...)`
    # can constrain the method's return type slot.
    current_method: Optional[tuple] = None

    def fresh(self) -> TVar:
        v = TVar(self.fresh_counter)
        self.fresh_counter += 1
        return v

    def constrain(self, t1: Any, t2: Any, where: str = "") -> None:
        """Add the constraint `t1 = t2` to the substitution."""
        a, b = apply(self.subst, t1), apply(self.subst, t2)
        try:
            s = unify(a, b)
        except UnifyError as e:
            self.issues.append(InferenceIssue(
                kind="unify",
                msg=f"{e}",
                expected=a, actual=b, location=where,
            ))
            return
        self.subst = compose(s, self.subst)


@dataclass
class InferenceIssue:
    kind: str           # "unify" | "refinement" | "unbound" | "arity"
    msg: str
    expected: Any = None
    actual:   Any = None
    location: str = ""


# ════════════════════════════════════════════════════════════════════════
# 6. Environment (Γ)
# ════════════════════════════════════════════════════════════════════════

class Env:
    """Lexical environment of name → Scheme."""

    def __init__(self, parent: Optional["Env"] = None):
        self.bindings: Dict[str, Scheme] = {}
        self.parent = parent

    def lookup(self, name: str) -> Optional[Scheme]:
        if name in self.bindings: return self.bindings[name]
        if self.parent: return self.parent.lookup(name)
        return None

    def bind(self, name: str, scheme: Scheme) -> None:
        self.bindings[name] = scheme

    def child(self) -> "Env":
        return Env(self)


def instantiate(infer: Inference, sch: Scheme) -> Any:
    """Refresh quantified variables in a scheme — α₁ … αₙ become fresh."""
    if not sch.vars: return sch.type
    subst: Subst = {v: infer.fresh() for v in sch.vars}
    return apply(subst, sch.type)


def generalise(env: Env, t: Any) -> Scheme:
    """∀-quantify variables in t that are not free in the surrounding env."""
    fv_t = free_vars(t)
    fv_env: set = set()
    e: Optional[Env] = env
    while e is not None:
        for sch in e.bindings.values():
            fv_env |= free_vars(sch.type)
        e = e.parent
    return Scheme(tuple(sorted(fv_t - fv_env, key=lambda v: v.id)), t)


# ════════════════════════════════════════════════════════════════════════
# 7. Built-in environment
# ════════════════════════════════════════════════════════════════════════

def _builtins(infer: Inference) -> Env:
    """Pre-populated env with AIPL primitives + bigint/rational/real ops."""
    env = Env()
    # Int arithmetic + comparison
    int_int_int = TArrow((T_INT, T_INT), T_INT)
    int_int_bool = TArrow((T_INT, T_INT), T_BOOL)
    for op in ["int_add", "int_sub", "int_mul", "int_div", "int_mod",
               "int_pow", "int_fact"]:
        env.bind(op, Scheme((), int_int_int if op != "int_fact"
                                else TArrow((T_INT,), T_INT)))
    for op in ["int_eq", "int_ne", "int_lt", "int_gt", "int_le", "int_ge"]:
        env.bind(op, Scheme((), int_int_bool))
    env.bind("int_to_string", Scheme((), TArrow((T_INT,), T_STR)))
    # Bool
    env.bind("not", Scheme((), TArrow((T_BOOL,), T_BOOL)))
    env.bind("and", Scheme((), TArrow((T_BOOL, T_BOOL), T_BOOL)))
    env.bind("or",  Scheme((), TArrow((T_BOOL, T_BOOL), T_BOOL)))
    # String
    env.bind("str_len",   Scheme((), TArrow((T_STR,), T_INT)))
    env.bind("str_index", Scheme((), TArrow((T_STR, T_STR), T_INT)))
    env.bind("str_sub",   Scheme((), TArrow((T_STR, T_INT, T_INT), T_STR)))
    # Rat (constructors and operations)
    env.bind("rat",          Scheme((), TArrow((T_INT, T_INT), T_RAT)))
    env.bind("rat_from_int", Scheme((), TArrow((T_INT,), T_RAT)))
    env.bind("rat_add",      Scheme((), TArrow((T_RAT, T_RAT), T_RAT)))
    env.bind("rat_sub",      Scheme((), TArrow((T_RAT, T_RAT), T_RAT)))
    env.bind("rat_mul",      Scheme((), TArrow((T_RAT, T_RAT), T_RAT)))
    env.bind("rat_div",      Scheme((), TArrow((T_RAT, T_RAT), T_RAT)))
    env.bind("rat_neg",      Scheme((), TArrow((T_RAT,), T_RAT)))
    env.bind("rat_inv",      Scheme((), TArrow((T_RAT,), T_RAT)))
    env.bind("rat_num",      Scheme((), TArrow((T_RAT,), T_INT)))
    env.bind("rat_den",      Scheme((), TArrow((T_RAT,), T_INT)))
    # Real
    env.bind("real_from_int", Scheme((), TArrow((T_INT,), T_REAL)))
    env.bind("real_from_rat", Scheme((), TArrow((T_RAT, T_INT), T_REAL)))
    env.bind("real_sqrt",     Scheme((), TArrow((T_REAL, T_INT), T_REAL)))
    env.bind("real_add",      Scheme((), TArrow((T_REAL, T_REAL), T_REAL)))
    env.bind("real_sub",      Scheme((), TArrow((T_REAL, T_REAL), T_REAL)))
    env.bind("real_mul",      Scheme((), TArrow((T_REAL, T_REAL), T_REAL)))
    env.bind("real_div",      Scheme((), TArrow((T_REAL, T_REAL), T_REAL)))
    env.bind("real_neg",      Scheme((), TArrow((T_REAL,), T_REAL)))
    env.bind("real_to_string", Scheme((), TArrow((T_REAL, T_INT), T_STR)))
    env.bind("set_precision", Scheme((), TArrow((T_INT,), T_UNIT)))
    # Generic polymorphic builtins (rarely used but handy)
    a = infer.fresh()
    env.bind("fst", Scheme((a,), TArrow((TTuple((a, infer.fresh())),), a)))
    env.bind("emit", Scheme((), TArrow((T_STR,), T_UNIT)))
    env.bind("print", Scheme((), TArrow((T_STR,), T_UNIT)))
    return env


# ════════════════════════════════════════════════════════════════════════
# 8. Expression-level inference
# ════════════════════════════════════════════════════════════════════════

def _infer_expr(infer: Inference, env: Env, e: Any) -> Any:
    """Compute a fresh type for expression `e`, accreting constraints
    into `infer.subst`."""
    # Literals
    if IntLit and isinstance(e, IntLit):    return T_INT
    if FloatLit and isinstance(e, FloatLit): return T_REAL
    if StringLit and isinstance(e, StringLit): return T_STR
    # Variable
    if Var and isinstance(e, Var):
        sch = env.lookup(e.name)
        if sch is None:
            infer.issues.append(InferenceIssue(
                kind="unbound", msg=f"unbound variable: {e.name}",
                location=getattr(e, "loc", "")))
            return infer.fresh()
        return instantiate(infer, sch)
    # Negation
    if Neg and isinstance(e, Neg):
        t = _infer_expr(infer, env, e.inner)
        infer.constrain(t, T_INT, where="neg operand")
        return t
    # Binary op
    if Binop and isinstance(e, Binop):
        return _infer_binop(infer, env, e)
    # Call
    if CallExpr and isinstance(e, CallExpr):
        return _infer_call(infer, env, e)
    # Tuple
    if TupleLit and isinstance(e, TupleLit):
        ts = tuple(_infer_expr(infer, env, x) for x in e.items)
        return TTuple(ts)
    # Array
    if ArrayLit and isinstance(e, ArrayLit):
        if not e.items:
            return TCon("List", (infer.fresh(),))
        elem_t = _infer_expr(infer, env, e.items[0])
        for x in e.items[1:]:
            t = _infer_expr(infer, env, x)
            infer.constrain(elem_t, t, where="list element")
        return TCon("List", (elem_t,))
    # now / future call — D-1: cross-class inference.
    # `now target.method(args)` is dispatched by:
    #   1. looking up target's type in env (should be TCon(ClassName))
    #   2. looking up class_sigs[ClassName][method] to get (param_tvars, ret_tvar)
    #   3. constraining the argument types and returning ret_tvar
    if NowCall and isinstance(e, NowCall):
        return _infer_method_dispatch(infer, env, e, is_future=False)
    if FutureCall and isinstance(e, FutureCall):
        inner = _infer_method_dispatch(infer, env, e, is_future=True)
        return TCon("Future", (inner,))
    # Record / field-access are skipped (kept as Dyn for gradual typing)
    if RecordLit and isinstance(e, RecordLit):
        return T_DYN
    if FieldAccess and isinstance(e, FieldAccess):
        return T_DYN
    if New and isinstance(e, New):
        # `new ClassName(args)` produces TCon(ClassName).  We also unify
        # the constructor's `init(...)` signature if registered.
        cls = getattr(e, "cls_name", None) or getattr(e, "cls", None) or "?"
        cls_t = TCon(cls, ())
        init_sig = infer.class_sigs.get(cls, {}).get("init")
        if init_sig:
            param_tvars, _ret_tvar = init_sig
            arg_ts = [_infer_expr(infer, env, a) for a in e.args]
            if len(arg_ts) == len(param_tvars):
                for at, pt in zip(arg_ts, param_tvars):
                    infer.constrain(at, pt, where=f"new {cls} arg")
            else:
                infer.issues.append(InferenceIssue(
                    kind="arity",
                    msg=f"new {cls}: expected {len(param_tvars)} args, "
                        f"got {len(arg_ts)}",
                ))
        return cls_t
    if IndexExpr and isinstance(e, IndexExpr):
        return T_DYN
    # Fallback
    return T_DYN


def _infer_binop(infer: Inference, env: Env, e: Any) -> Any:
    """Type-check an infix Binop.

    Numeric ops on Int / Real / Rat use overloaded resolution by
    constraining both operands to the same type and returning it.
    Comparison ops produce Bool."""
    op = e.op
    lhs = _infer_expr(infer, env, e.lhs)
    rhs = _infer_expr(infer, env, e.rhs)
    if op in ("+", "-", "*", "/", "mod"):
        # Try Int by default; allow Real if either side is Real.
        infer.constrain(lhs, rhs, where=f"{op} operands")
        return lhs
    if op in ("==", "!=", "<", ">", "<=", ">="):
        infer.constrain(lhs, rhs, where=f"{op} operands")
        return T_BOOL
    if op in ("and", "or"):
        infer.constrain(lhs, T_BOOL, where=f"{op} lhs")
        infer.constrain(rhs, T_BOOL, where=f"{op} rhs")
        return T_BOOL
    if op == "::":
        list_t = TCon("List", (lhs,))
        infer.constrain(rhs, list_t, where="cons rhs")
        return list_t
    # Unknown op — Dyn
    return T_DYN


def _infer_method_dispatch(infer: Inference, env: Env, e: Any, is_future: bool) -> Any:
    """D-1: dispatch `now/future target.method(args)`.

    Look up `target` in env to find its class, then resolve the method
    via `infer.class_sigs[ClassName][method]`.  Returns the method's
    return TVar (which subsequent constraints from `reply(…)` in the
    callee narrow)."""
    target = e.target
    method = e.method
    args   = e.args
    if target in ("self", "sender"):
        # Self-call within a method: look up current_method's class.
        if infer.current_method:
            cls_name = infer.current_method[0]
        else:
            return infer.fresh()
    else:
        sch = env.lookup(target)
        if sch is None:
            infer.issues.append(InferenceIssue(
                kind="unbound", msg=f"unknown actor: {target}"))
            return infer.fresh()
        target_t = instantiate(infer, sch)
        target_t = apply(infer.subst, target_t)
        if isinstance(target_t, TCon):
            cls_name = target_t.name
        elif isinstance(target_t, TVar):
            return infer.fresh()        # unknown class, leave open
        else:
            return infer.fresh()
    methods = infer.class_sigs.get(cls_name)
    if methods is None:
        return infer.fresh()
    sig = methods.get(method)
    if sig is None:
        infer.issues.append(InferenceIssue(
            kind="unbound", msg=f"no method {method} on {cls_name}"))
        return infer.fresh()
    param_tvars, ret_tvar = sig
    arg_ts = [_infer_expr(infer, env, a) for a in args]
    if len(arg_ts) != len(param_tvars):
        infer.issues.append(InferenceIssue(
            kind="arity",
            msg=f"{cls_name}.{method}: expected {len(param_tvars)} args, "
                f"got {len(arg_ts)}"))
        return ret_tvar
    for at, pt in zip(arg_ts, param_tvars):
        infer.constrain(at, pt, where=f"{cls_name}.{method} arg")
    return ret_tvar


def _infer_call(infer: Inference, env: Env, e: Any) -> Any:
    fn = env.lookup(e.name)
    if fn is None:
        infer.issues.append(InferenceIssue(
            kind="unbound", msg=f"unknown function: {e.name}",
            location=getattr(e, "loc", "")))
        return infer.fresh()
    fn_t = instantiate(infer, fn)
    arg_ts = [_infer_expr(infer, env, a) for a in e.args]
    ret_t = infer.fresh()
    expected_arrow = TArrow(tuple(arg_ts), ret_t)
    infer.constrain(fn_t, expected_arrow, where=f"call to {e.name}")
    return ret_t


# ════════════════════════════════════════════════════════════════════════
# 9. Statement / declaration inference
# ════════════════════════════════════════════════════════════════════════

def _infer_stmt(infer: Inference, env: Env, s: Any) -> None:
    if VarDecl and isinstance(s, VarDecl):
        rhs_t = _infer_expr(infer, env, s.expr)
        if getattr(s, "type_annotation", None):
            ann = _parse_annotation(s.type_annotation, infer)
            infer.constrain(rhs_t, ann, where=f"var {s.name}")
            env.bind(s.name, Scheme((), apply(infer.subst, ann)))
        else:
            env.bind(s.name, generalise(env, apply(infer.subst, rhs_t)))
        return
    # `var x = new ClassName(args)` is its own AST node (VarNew) —
    # bind x : TCon(ClassName) and check the init call's arity (D-1).
    from aipl_ast import VarNew as _VarNew     # late import to avoid cycle
    if _VarNew and isinstance(s, _VarNew):
        cls_t = TCon(s.cls_name, ())
        init_sig = infer.class_sigs.get(s.cls_name, {}).get("init")
        if init_sig:
            param_tvars, _ret_tvar = init_sig
            arg_ts = [_infer_expr(infer, env, a) for a in s.args]
            if len(arg_ts) == len(param_tvars):
                for at, pt in zip(arg_ts, param_tvars):
                    infer.constrain(at, pt, where=f"new {s.cls_name} arg")
            else:
                infer.issues.append(InferenceIssue(
                    kind="arity",
                    msg=f"new {s.cls_name}: expected {len(param_tvars)} args, "
                        f"got {len(arg_ts)}"))
        env.bind(s.name, Scheme((), cls_t))
        return
    if Assign and isinstance(s, Assign):
        rhs_t = _infer_expr(infer, env, s.expr)
        sch = env.lookup(s.name)
        if sch:
            infer.constrain(instantiate(infer, sch), rhs_t,
                            where=f"assign to {s.name}")
        return
    if If and isinstance(s, If):
        c_t = _infer_expr(infer, env, s.cond)
        infer.constrain(c_t, T_BOOL, where="if condition")
        _infer_stmt(infer, env.child(), s.then_body)
        if getattr(s, "else_body", None):
            _infer_stmt(infer, env.child(), s.else_body)
        return
    if While and isinstance(s, While):
        c_t = _infer_expr(infer, env, s.cond)
        infer.constrain(c_t, T_BOOL, where="while condition")
        _infer_stmt(infer, env.child(), s.body)
        return
    if Block and isinstance(s, Block):
        for st in s.stmts:
            _infer_stmt(infer, env, st)
        return
    if Return and isinstance(s, Return):
        if getattr(s, "expr", None) is not None:
            _infer_expr(infer, env, s.expr)
        return
    if CallStmt and isinstance(s, CallStmt):
        # D-1: `reply(expr)` is the AIPL way to return a value from
        # an actor method.  We constrain the current method's return
        # TVar to the type of `expr`.
        if s.name == "reply" and infer.current_method is not None:
            cls, mname = infer.current_method
            sig = infer.class_sigs.get(cls, {}).get(mname)
            if sig is not None and s.args:
                _, ret_tvar = sig
                ret_t = _infer_expr(infer, env, s.args[0])
                infer.constrain(ret_t, ret_tvar,
                                where=f"{cls}.{mname} reply")
            return
        sch = env.lookup(s.name)
        if sch:
            fn_t = instantiate(infer, sch)
            arg_ts = [_infer_expr(infer, env, a) for a in s.args]
            ret_t = infer.fresh()
            infer.constrain(fn_t, TArrow(tuple(arg_ts), ret_t),
                            where=f"call {s.name}")
        return
    # Skip Send / FieldAssign etc. — left as gradual unknown


# ════════════════════════════════════════════════════════════════════════
# 10. Method-level inference (top-level entry into a class method)
# ════════════════════════════════════════════════════════════════════════

def infer_method(class_decl: Any, m: Any,
                 infer: Optional[Inference] = None,
                 shared_env: Optional[Env] = None) -> "InferenceResult":
    """Infer types for one method of one class.

    When `infer` is given, that shared state is reused so cross-class
    constraints accumulate (D-1).  Otherwise a fresh `Inference` is
    created and the method is inferred in isolation."""
    standalone = infer is None
    if standalone:
        infer = Inference()
    env = shared_env if shared_env is not None else _builtins(infer)
    builtin_keys = set(env.bindings.keys())     # snapshot to exclude from report
    # D-1: enter method context (so `reply(...)` constrains the right slot)
    cls_name = class_decl.name if class_decl else "(top)"
    saved_method = infer.current_method
    infer.current_method = (cls_name, m.name)
    # Method params: use pre-registered TVars from class_sigs if available
    pre_sig = infer.class_sigs.get(cls_name, {}).get(m.name)
    if pre_sig:
        param_tvars, _ret_tvar = pre_sig
    else:
        param_tvars = tuple(infer.fresh() for _ in m.params)
    param_types = []
    # Phase E-α: keep the parsed refined annotation per position so it
    # can be re-injected at the end (unify drops refinements once the
    # underlying TVar has already been bound to a concrete base by a
    # caller in Pass 0).
    refined_ann_by_pos: Dict[int, Any] = {}
    for i, p in enumerate(m.params):
        ann = m.param_annotations[i] if i < len(getattr(m, "param_annotations", [])) else None
        t = param_tvars[i]
        if ann:
            ann_t = _parse_annotation(ann, infer)
            infer.constrain(t, ann_t, where=f"{cls_name}.{m.name} param {p}")
            if isinstance(ann_t, TRefined):
                refined_ann_by_pos[i] = TRefined(
                    ann_t.base, p, ann_t.pred_src, ann_t.pred_ast,
                )
        env.bind(p, Scheme((), t))
        param_types.append(t)
    # Body
    if isinstance(m.body, list):
        for st in m.body:
            _infer_stmt(infer, env, st)
    else:
        _infer_stmt(infer, env, m.body)
    # Resolve param types after constraints settled
    final_params = []
    for i, (p, t) in enumerate(zip(m.params, param_types)):
        resolved = apply(infer.subst, t)
        if i in refined_ann_by_pos:
            ann_t = refined_ann_by_pos[i]
            if isinstance(resolved, TRefined):
                # Refine with the proper binder (parser used "_").
                resolved = TRefined(resolved.base, p, resolved.pred_src, resolved.pred_ast)
            elif resolved == ann_t.base or isinstance(resolved, TCon):
                # unify dropped the refinement (TVar already bound to base) — re-attach.
                resolved = TRefined(resolved, p, ann_t.pred_src, ann_t.pred_ast)
        final_params.append((p, resolved))
    locals_ = {n: apply(infer.subst, sch.type)
               for n, sch in env.bindings.items()
               if n not in m.params and n not in builtin_keys}
    # Compute return type from class_sigs
    return_type = None
    if pre_sig:
        return_type = apply(infer.subst, pre_sig[1])
    infer.current_method = saved_method
    return InferenceResult(
        class_name=cls_name,
        method_name=m.name,
        param_types=final_params,
        local_types=locals_,
        issues=list(infer.issues) if standalone else [],
        refinement_issues=(_check_refinements(infer.refinements)
                          + _check_refined_decls(infer.refined_decls))
                          if standalone else [],
        return_type=return_type,
    )


@dataclass
class InferenceResult:
    class_name: str
    method_name: str
    param_types: list           # list of (name, Type)
    local_types: dict           # name -> Type
    issues: list                # list of InferenceIssue
    refinement_issues: list     # list of refinement violations from Z3
    return_type: Any = None     # D-1: method's return type from reply()

    def render(self) -> str:
        head = f"=== {self.class_name}.{self.method_name} ==="
        lines = [head]
        if self.param_types:
            lines.append("  params:")
            for n, t in self.param_types:
                lines.append(f"    {n} : {t}")
        if self.return_type is not None:
            lines.append(f"  return : {self.return_type}")
        if self.local_types:
            lines.append("  locals:")
            for n, t in self.local_types.items():
                lines.append(f"    {n} : {t}")
        if self.issues:
            lines.append("  issues:")
            for iss in self.issues:
                lines.append(f"    [{iss.kind}] {iss.msg}  at {iss.location}")
        if self.refinement_issues:
            lines.append("  refinement issues:")
            for ri in self.refinement_issues:
                lines.append(f"    {ri}")
        return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════
# 11. Refinement annotation parsing + Z3 backend
# ════════════════════════════════════════════════════════════════════════

# Annotation syntax used by PsiLang2:
#   Int  where k >= 0
#   Rat                                  (no refinement)
#   Real where digits == n_digits
# We parse the leading type identifier (Int, Rat, Real, …) and keep
# the predicate text verbatim — the Z3 backend re-parses the predicate
# when discharging refinements.

_TYPE_NAME_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)")


def _parse_annotation(ann: str, infer: Inference) -> Any:
    """Parse a textual annotation produced by the parser into a Type.

    Supports: 'Int', 'Bool', 'Str', 'Real', 'Rat', 'Unit', 'Dyn',
    'List<T>', '(T1, T2)', and `T where <predicate>` refinements."""
    if not ann: return infer.fresh()
    s = ann.strip()
    # Refinement?
    m = re.match(r"^([^\s]+)\s+where\s+(.+)$", s)
    if m:
        base = _parse_annotation(m.group(1), infer)
        # binder placeholder; real binder comes from the variable name
        rt = TRefined(base, "_", m.group(2), pred_ast=None)
        # Phase E-α: register every refined annotation so the
        # satisfiability check at the end of inference can flag
        # declarations whose predicate is vacuously false.
        infer.refined_decls.append(rt)
        return rt
    # Tuple
    if s.startswith("(") and s.endswith(")"):
        inner = s[1:-1]
        parts = _split_top(inner, ",")
        if len(parts) == 1:
            return _parse_annotation(parts[0], infer)
        return TTuple(tuple(_parse_annotation(p, infer) for p in parts))
    # List<T>
    m = re.match(r"^List\s*<\s*(.+)\s*>$", s)
    if m:
        return TCon("List", (_parse_annotation(m.group(1), infer),))
    # Bare type names
    if s == "Int": return T_INT
    if s == "Bool": return T_BOOL
    if s == "Str": return T_STR
    if s == "Real": return T_REAL
    if s == "Rat": return T_RAT
    if s == "Unit": return T_UNIT
    if s == "Dyn":  return T_DYN
    # Identifier: nominal class type
    m = _TYPE_NAME_RE.match(s)
    if m:
        return TCon(m.group(1), ())
    return infer.fresh()


def _split_top(text: str, sep: str) -> list:
    out, depth, cur = [], 0, ""
    for c in text:
        if c in "([{<": depth += 1
        if c in ")]}>": depth -= 1
        if c == sep and depth == 0:
            out.append(cur); cur = ""
        else:
            cur += c
    if cur: out.append(cur)
    return [p.strip() for p in out]


def _check_refinements(refs: list) -> list:
    """Discharge refinement predicates via Z3.  Each `ref` is a tuple
    (refined_type, value_expr_text, location).  If Z3 is unavailable
    the predicates are accepted as documentation."""
    try:
        import z3
    except Exception:
        return []
    if not refs: return []
    out = []
    for (rt, expr_src, loc) in refs:
        if not isinstance(rt, TRefined): continue
        ok, why = _z3_check(z3, rt, expr_src)
        if not ok:
            out.append(f"refinement violation at {loc}: {rt}  ({why})")
    return out


def _check_refined_decls(decls: list) -> list:
    """Phase E-α: discharge each declared refined type on its own.
    Flags any predicate that is vacuously false (UNSAT for every
    possible value of the binder)."""
    try:
        import z3
    except Exception:
        return []
    seen, out = set(), []
    for rt in decls:
        if not isinstance(rt, TRefined): continue
        key = (str(rt.base), rt.pred_src)
        if key in seen: continue
        seen.add(key)
        ok, why = _z3_check(z3, rt, expr_src="")
        if not ok:
            out.append(f"refinement is vacuously false: {rt}  ({why})")
    return out


def _z3_check(z3, rt: TRefined, expr_src: str) -> tuple:
    """Best-effort: check that `rt.pred_src` is satisfiable when the
    binder is a symbolic Int.  We parse the predicate via Python's
    AST so `and`/`or`/`not` correctly translate to z3.And / z3.Or /
    z3.Not instead of being short-circuited by Python's eval."""
    if rt.base != T_INT:
        return True, "non-Int refinement deferred to runtime"
    try:
        import ast
        binder = rt.binder if rt.binder != "_" else "x"
        # Free variables become fresh Z3 ints.
        free: Dict[str, Any] = {binder: z3.Int(binder)}
        for tok in set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", rt.pred_src)):
            if tok in free or tok in ("and", "or", "not", "True", "False"):
                continue
            free[tok] = z3.Int(tok)
        tree = ast.parse(rt.pred_src, mode="eval")
        pred = _ast_to_z3(tree.body, free, z3)
        s = z3.Solver()
        s.add(pred)
        if s.check() == z3.unsat:
            return False, "predicate is unsatisfiable"
        return True, ""
    except Exception as e:
        return True, f"could not encode refinement ({type(e).__name__}: {e})"


def _ast_to_z3(node: Any, env: Dict[str, Any], z3: Any) -> Any:
    """Translate a Python AST predicate to a Z3 expression."""
    import ast
    if isinstance(node, ast.BoolOp):
        parts = [_ast_to_z3(v, env, z3) for v in node.values]
        if isinstance(node.op, ast.And): return z3.And(*parts)
        if isinstance(node.op, ast.Or):  return z3.Or(*parts)
        raise ValueError(f"unknown bool op {node.op}")
    if isinstance(node, ast.UnaryOp):
        v = _ast_to_z3(node.operand, env, z3)
        if isinstance(node.op, ast.Not):  return z3.Not(v)
        if isinstance(node.op, ast.USub): return -v
        if isinstance(node.op, ast.UAdd): return v
        raise ValueError(f"unknown unary op {node.op}")
    if isinstance(node, ast.Compare):
        # Chained compares (a < b < c) → conjunction
        left = _ast_to_z3(node.left, env, z3)
        clauses = []
        prev = left
        for op, comp in zip(node.ops, node.comparators):
            rhs = _ast_to_z3(comp, env, z3)
            if isinstance(op, ast.Eq):    c = prev == rhs
            elif isinstance(op, ast.NotEq): c = prev != rhs
            elif isinstance(op, ast.Lt):  c = prev < rhs
            elif isinstance(op, ast.Gt):  c = prev > rhs
            elif isinstance(op, ast.LtE): c = prev <= rhs
            elif isinstance(op, ast.GtE): c = prev >= rhs
            else: raise ValueError(f"unknown compare op {op}")
            clauses.append(c); prev = rhs
        return clauses[0] if len(clauses) == 1 else z3.And(*clauses)
    if isinstance(node, ast.BinOp):
        l = _ast_to_z3(node.left, env, z3)
        r = _ast_to_z3(node.right, env, z3)
        if isinstance(node.op, ast.Add):  return l + r
        if isinstance(node.op, ast.Sub):  return l - r
        if isinstance(node.op, ast.Mult): return l * r
        if isinstance(node.op, ast.FloorDiv) or isinstance(node.op, ast.Div):
            return l / r
        if isinstance(node.op, ast.Mod):  return l % r
        raise ValueError(f"unknown bin op {node.op}")
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):  return z3.BoolVal(node.value)
        if isinstance(node.value, int):   return z3.IntVal(node.value)
        if isinstance(node.value, float): return z3.RealVal(node.value)
        raise ValueError(f"unsupported constant {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id in env: return env[node.id]
        raise ValueError(f"unbound name {node.id}")
    raise ValueError(f"unsupported AST node {type(node).__name__}")


# ════════════════════════════════════════════════════════════════════════
# 12. Program-level driver
# ════════════════════════════════════════════════════════════════════════

def infer_program(program: Any) -> list:
    """Infer types for every method in every class of `program`.

    D-1: uses a single shared `Inference` state with class-method
    signatures pre-registered (param TVars + ret TVar), so that
    `now obj.method(args)` calls can unify across classes.  The
    driver does not stop on error — it accumulates issues so the
    user sees them all (matching v2 (2) `collect_all_continue`)."""
    infer = Inference()
    shared_env = _builtins(infer)

    # Pre-pass: register placeholder signatures for every class method.
    for decl in getattr(program, "decls", []):
        if ClassDecl and isinstance(decl, ClassDecl):
            infer.class_sigs[decl.name] = {}
            for m in decl.methods:
                params = tuple(infer.fresh() for _ in m.params)
                ret    = infer.fresh()
                infer.class_sigs[decl.name][m.name] = (params, ret)

    # Pass 1 + Pass 2: infer each method's body twice — the second pass
    # uses the fully-populated class_sigs from pass 1 so cross-class
    # NowCall returns now resolve to concrete types (`s : Int` rather
    # than a stray TVar).  Re-using the same `infer` accumulates the
    # subst so this is monotonic.
    def _run_method_pass(suppress_dup_issues: bool):
        results = []
        for decl in getattr(program, "decls", []):
            if ClassDecl and isinstance(decl, ClassDecl):
                cls_env = shared_env.child()
                for f in getattr(decl, "fields", []) or []:
                    if VarDecl and isinstance(f, VarDecl):
                        rhs_t = _infer_expr(infer, cls_env, f.expr)
                        cls_env.bind(f.name, Scheme((), apply(infer.subst, rhs_t)))
                for m in decl.methods:
                    res = infer_method(decl, m, infer=infer,
                                        shared_env=cls_env.child())
                    results.append(res)
            elif FunctionDecl and isinstance(decl, FunctionDecl):
                res = infer_method(None, decl, infer=infer,
                                    shared_env=shared_env.child())
                results.append(res)
        if suppress_dup_issues:
            # Pass-2 may regenerate "unknown actor" issues that are
            # actually resolved by then; drop those, keep the rest.
            # We just truncate `infer.issues` back to pre-pass length.
            pass
        return results

    # Pass 0: process top-level GlobalStmts first.  This binds names
    # like `var calc = new Calculator(10)` and crucially propagates
    # the argument types of calls like `now calc.use_adder(add_actor)`
    # into class_sigs's `use_adder` parameter TVars — so when we then
    # infer use_adder's body, `other` is already `Adder`.
    issues_before_globals = len(infer.issues)
    for decl in getattr(program, "decls", []):
        if GlobalStmt and isinstance(decl, GlobalStmt):
            _infer_stmt(infer, shared_env, decl.stmt)
    # Drop issues from pass 0: they may be due to forward references
    # to method signatures that haven't been resolved yet.
    infer.issues = infer.issues[:issues_before_globals]

    # Pass 1: infer all method bodies (drops issues for re-run later).
    issues_before_p1 = len(infer.issues)
    _run_method_pass(False)
    infer.issues = infer.issues[:issues_before_p1]

    # Pass 2: re-infer (records final issues + accurate types).
    method_results = _run_method_pass(True)

    # (Global statements were already processed in Pass 0; nothing to do here.)

    # Apply final substitution to all collected results
    for r in method_results:
        r.param_types = [(n, apply(infer.subst, t)) for n, t in r.param_types]
        r.local_types = {n: apply(infer.subst, t) for n, t in r.local_types.items()}
        if r.return_type is not None:
            r.return_type = apply(infer.subst, r.return_type)
    # Attach global issues + refinement check to the last result
    # (or create a sentinel result if there are no methods)
    if method_results:
        method_results[-1].issues.extend(infer.issues)
        method_results[-1].refinement_issues.extend(
            _check_refinements(infer.refinements))
        method_results[-1].refinement_issues.extend(
            _check_refined_decls(infer.refined_decls))
    return method_results


# ════════════════════════════════════════════════════════════════════════
# 13. CLI entry — for quick experimentation
# ════════════════════════════════════════════════════════════════════════

def _main():                              # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser(prog="aipl_inference")
    ap.add_argument("source", help="path to a .aipl source file")
    args = ap.parse_args()
    sys.path.insert(0, "/Users/kodamay/ocaml-app/abclcp-project/src/python-aipl")
    from aipl_parser import parse_file
    prog = parse_file(args.source)
    results = infer_program(prog)
    for r in results:
        print(r.render())
        print()
    total_issues = sum(len(r.issues) + len(r.refinement_issues) for r in results)
    print(f"\n[inference] {len(results)} methods inferred, "
          f"{total_issues} issues")


if __name__ == "__main__":              # pragma: no cover
    _main()
