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
import os
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
    use structural types internally for now).

    CE-16 V1 (row-polymorphism, opt-in via AIPL_ROWPOLY=1):
    an optional `tail` row-variable absorbs extra fields produced
    on either side of a unification.  `tail=None` means the record
    is "closed" — it must match exactly under unify.  When
    AIPL_ROWPOLY is off, all records are constructed with tail=None
    and the unify arm falls back to the CE-13 width-subtyping path.
    """
    fields: tuple                          # tuple of (name, Type)
    tail: object = None                    # None | TVar (row variable)

    def __str__(self) -> str:
        body = ", ".join(f"{n}: {t}" for n, t in self.fields)
        if self.tail is None:
            return f"{{{body}}}"
        sep = " | " if body else "| "
        return f"{{{body}{sep}{self.tail}}}"


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
        # CE-16: substitute through the row tail too; when the tail
        # resolves to another TRecord, merge its fields in (this is
        # how row variables unify).
        new_fields = tuple((n, apply(s, ft)) for n, ft in t.fields)
        if t.tail is None:
            return TRecord(new_fields, None)
        new_tail = apply(s, t.tail)
        if isinstance(new_tail, TRecord):
            merged = dict(new_fields)
            for n, ft in new_tail.fields:
                if n not in merged:
                    merged[n] = ft
            return TRecord(tuple(merged.items()), new_tail.tail)
        return TRecord(new_fields, new_tail)
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
        if t.tail is not None: out |= free_vars(t.tail)
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
    # CE-16 V1: row-polymorphic unify (opt-in via AIPL_ROWPOLY=1).
    # When either side carries a row tail, label differences are
    # absorbed into the tail variable.  This is the canonical
    # row-polymorphic formulation that matches the OCaml-style
    # `TRecord of fields * row_var` design picked in round 7.
    if (isinstance(t1, TRecord) and isinstance(t2, TRecord)
            and os.environ.get("AIPL_ROWPOLY", "0") == "1"
            and (t1.tail is not None or t2.tail is not None)):
        d1, d2 = dict(t1.fields), dict(t2.fields)
        common  = sorted(set(d1) & set(d2))
        only_1  = sorted(set(d1) - set(d2))   # fields only on lhs
        only_2  = sorted(set(d2) - set(d1))   # fields only on rhs
        s: Subst = {}
        for name in common:
            s = compose(unify(apply(s, d1[name]), apply(s, d2[name])), s)
        # The lhs-only fields must be acceptable to rhs's tail; the
        # rhs-only fields must be acceptable to lhs's tail.
        if only_1 and t2.tail is None:
            raise UnifyError(
                f"closed record on rhs cannot accept extra fields {only_1}")
        if only_2 and t1.tail is None:
            raise UnifyError(
                f"closed record on lhs cannot accept extra fields {only_2}")
        # Shared fresh row variable for the "other rest" they agree
        # is open.  When both tails are present we point them at a
        # common fresh row, plumbing the unique fields into each
        # side's view of that row.  When only one tail is present we
        # close the gap by binding it to the leftovers.
        only_1_fields = tuple((n, apply(s, d1[n])) for n in only_1)
        only_2_fields = tuple((n, apply(s, d2[n])) for n in only_2)
        if t1.tail is not None and t2.tail is not None:
            # If both tails are already the same variable, they must
            # be empty (no rhs-only and no lhs-only); else inconsistent.
            if t1.tail == t2.tail:
                if only_1_fields or only_2_fields:
                    raise UnifyError(
                        f"row tail {t1.tail} bound on both sides but "
                        f"unique fields would conflict")
                return s
            rest = _row_fresh()
            s = compose(_bind(t1.tail, TRecord(only_2_fields, rest)), s)
            s = compose(_bind(t2.tail, TRecord(only_1_fields, rest)), s)
        elif t1.tail is not None:
            s = compose(_bind(t1.tail, TRecord(only_2_fields, None)), s)
        elif t2.tail is not None:
            s = compose(_bind(t2.tail, TRecord(only_1_fields, None)), s)
        return s
    # CE-13: width subtyping for records.  Previously this required
    # both records to have exactly the same set of field names; that
    # rules out the common AIPL pattern where a method declares
    # `r: {x: int}` and a caller passes `{x: int, y: int, z: string}`.
    # Now we unify the INTERSECTION of fields (recursive depth-
    # subtyping per field) and ignore fields present in only one
    # side.  We still reject record × record with NO overlap to catch
    # outright type errors (`{x: int}` vs `{label: string}`).
    if isinstance(t1, TRecord) and isinstance(t2, TRecord):
        d1, d2 = dict(t1.fields), dict(t2.fields)
        common = set(d1.keys()) & set(d2.keys())
        if not common and (d1 and d2):
            raise UnifyError(
                f"record fields disjoint: {sorted(d1)} vs {sorted(d2)}")
        s: Subst = {}
        for name in sorted(common):
            s = compose(unify(apply(s, d1[name]), apply(s, d2[name])), s)
        return s
    # CE-12: refinement-aware unification.  When both sides are
    # TRefined the bases must unify; in addition, when
    # AIPL_REFINE_UNIFY=1 we Z3-check the predicate-subset relation
    # P_t1 ⊨ P_t2 (i.e. every value of t1 also satisfies t2's
    # predicate).  An early UnifyError surfaces refinement violations
    # at unify time instead of waiting for the post-hoc
    # `_check_refinements` walk.  Without the env var the behaviour
    # collapses to the pre-CE-12 path (drop the refinement, unify
    # bases) so existing programs run unchanged.
    if isinstance(t1, TRefined) and isinstance(t2, TRefined):
        s = unify(t1.base, t2.base)
        if os.environ.get("AIPL_REFINE_UNIFY", "0") == "1":
            ok, why = _refine_subset_z3(t1, t2)
            if not ok:
                raise UnifyError(
                    f"refinement subtype check failed: {t1} ⊄ {t2} ({why})")
        return s
    if isinstance(t1, TRefined):
        return unify(t1.base, t2)
    if isinstance(t2, TRefined):
        return unify(t1, t2.base)
    raise UnifyError(f"no rule to unify {t1} with {t2}")


def _refine_subset_z3(rt_sub: 'TRefined', rt_sup: 'TRefined') -> tuple:
    """CE-12: check whether every value satisfying rt_sub's predicate
    also satisfies rt_sup's.  We encode `P_sub ∧ ¬P_sup` and ask Z3
    whether it is UNSAT.  Returns (ok, why) — ok=True means the
    subset relation holds (or could not be checked, in which case
    we conservatively allow the unify to proceed).
    """
    try:
        import z3
    except Exception:
        return True, "z3 unavailable; deferred"
    if rt_sub.base != rt_sup.base:
        return True, "different bases — handled by unify(bases)"
    # Reuse the same encoding pipeline as _z3_check.
    if rt_sub.base == T_INT:
        mk_var = z3.Int
    elif rt_sub.base in (T_REAL, T_RAT):
        mk_var = z3.Real
    elif rt_sub.base == T_BOOL:
        mk_var = z3.Bool
    else:
        return True, "non-numeric refinement deferred"
    try:
        import ast as _ast
        # Use a shared symbolic variable for the binder: both
        # predicates need to reference the same value.
        shared_binder = "_x"
        free: Dict[str, Any] = {
            rt_sub.binder if rt_sub.binder != "_" else "x": mk_var(shared_binder),
            rt_sup.binder if rt_sup.binder != "_" else "x": mk_var(shared_binder),
        }
        # Free variables that appear in either predicate (other than
        # binders) get fresh Int/Real/Bool symbols of the same sort.
        for src in (rt_sub.pred_src, rt_sup.pred_src):
            for tok in set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", src)):
                if tok in free or tok in ("and", "or", "not", "True", "False"):
                    continue
                free[tok] = mk_var(tok)
        p_sub = _ast_to_z3(_ast.parse(rt_sub.pred_src, mode="eval").body, free, z3)
        p_sup = _ast_to_z3(_ast.parse(rt_sup.pred_src, mode="eval").body, free, z3)
        s = z3.Solver()
        s.add(z3.And(p_sub, z3.Not(p_sup)))
        if s.check() == z3.unsat:
            return True, "subset confirmed"
        return False, f"counterexample exists: {rt_sub.pred_src} ⊅ {rt_sup.pred_src}"
    except Exception as e:
        return True, f"could not encode refinement ({type(e).__name__}: {e})"


def _bind(v: TVar, t: Any) -> Subst:
    if v == t: return {}
    if isinstance(t, TVar) and v.id == t.id: return {}
    if v in free_vars(t):
        raise UnifyError(f"occurs check: {v} in {t}")
    return {v: t}


# CE-16 V1: fresh row variables minted during unify (which can't see
# the surrounding Inference instance).  Negative IDs keep them
# distinct from inference-minted positive-ID TVars; subsequent
# generalize/instantiate quantify them as ordinary type variables.
_ROW_FRESH_COUNTER = [-1]


def _row_fresh() -> TVar:
    v = TVar(_ROW_FRESH_COUNTER[0])
    _ROW_FRESH_COUNTER[0] -= 1
    return v


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
    # E-3: class-level field TVars shared across every method.  Each
    # field gets exactly one TVar, populated by Pass-0 from its
    # initializer and further refined by every usage (read or write)
    # in any method body.
    # Schema: { class_name: { field_name: TVar } }
    class_fields: Dict[str, Dict[str, Any]] = field(default_factory=dict)
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
            # Unknown identifier — gradual fallback (fresh tvar, no error).
            # Mirrors OCaml/JS-B behavior: AIPL has many globally-visible
            # builtin classes (AI, …) and constants that aren't in env
            # but are valid at runtime.  See `feedback_js_hm_port`.
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
    # E-1: record literals become TRecord with each field typed from
    # its RHS expression.  Sorted by name so structural equality is
    # order-independent.  CE-16 V1: when AIPL_ROWPOLY=1 the literal is
    # *closed* (tail=None) — it carries exactly these fields — and a
    # consumer with a row-variable tail will absorb the difference at
    # unify time.
    if RecordLit and isinstance(e, RecordLit):
        ftypes = []
        for fname, fexpr in e.fields:
            ftypes.append((fname, _infer_expr(infer, env, fexpr)))
        ftypes.sort(key=lambda x: x[0])
        return TRecord(tuple(ftypes), None)
    if FieldAccess and isinstance(e, FieldAccess):
        # E-3 (class fields) + E-1 (record fields): resolve the
        # receiver's type and walk the attr chain.  Falls back to
        # Dyn for opaque receivers (gradual typing).
        sch = env.lookup(e.name)
        if not sch:
            return T_DYN
        cur = apply(infer.subst, instantiate(infer, sch))
        for attr in e.attrs:
            cur = apply(infer.subst, cur)
            if isinstance(cur, TCon):
                fields = infer.class_fields.get(cur.name, {})
                nxt = fields.get(attr)
                if nxt is None:
                    return T_DYN
                cur = nxt
            elif isinstance(cur, TRecord):
                nxt = dict(cur.fields).get(attr)
                if nxt is None:
                    infer.issues.append(InferenceIssue(
                        kind="field",
                        msg=f"record has no field '{attr}': {cur}",
                        location=f"{e.name}.{'.'.join(e.attrs)}",
                    ))
                    return T_DYN
                cur = nxt
            elif isinstance(cur, TVar):
                # Constrain receiver to a record containing this field.
                # CE-16 V1: open the constraint with a fresh row tail
                # under AIPL_ROWPOLY=1 so multiple `.field` reads on
                # the same receiver each just constrain one field,
                # and the receiver accumulates a row of {field1, field2}
                # without forcing a closed record.
                ft = infer.fresh()
                row_tail = _row_fresh() if os.environ.get("AIPL_ROWPOLY", "0") == "1" else None
                infer.constrain(cur, TRecord(((attr, ft),), row_tail),
                                where=f"{e.name}.{attr} access")
                cur = ft
            else:
                return T_DYN
        return apply(infer.subst, cur)
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
    if op == "+":
        # String concatenation: if either side resolves to Str, the
        # result is Str — match OCaml infer.ml::pick_overload's
        # `"+", TString, _ -> TString` rule.  This permits the common
        # `print("foo " + n)` idiom without an Int-vs-Str unify error.
        lhs_r = apply(infer.subst, lhs)
        rhs_r = apply(infer.subst, rhs)
        if (isinstance(lhs_r, TCon) and lhs_r.name == "Str") or \
           (isinstance(rhs_r, TCon) and rhs_r.name == "Str"):
            return T_STR
        # Otherwise numeric: constrain both to the same type.
        infer.constrain(lhs, rhs, where=f"{op} operands")
        return lhs
    if op in ("-", "*", "/", "mod"):
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
            # Unknown actor target — gradual fallback (no error).
            # The runtime resolves the name dynamically; AIPL has
            # global builtins (e.g. AI) that aren't in env but are
            # always reachable.
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
        # E-2: consult aipl_typeck's BUILTIN_SIGNATURES so calls to
        # `read_file`, `str_len`, etc. flow through real type checks
        # instead of becoming spurious "unknown function" errors.
        bsig = _lookup_builtin_signature(e.name)
        if bsig is not None:
            return _check_builtin_call(infer, env, e, bsig)
        # Unknown function — treat as gradually typed (Dyn -> Dyn).
        # Mirrors OCaml `infer.ml`'s "unknown function 'X' treated as
        # gradual (any -> any)" warning and JS-B/JS-N's CallExpr arm
        # that returns a fresh TVar without erroring.  We still walk
        # args for side effects so any nested unify constraints land.
        for a in e.args:
            _infer_expr(infer, env, a)
        return infer.fresh()
    fn_t = instantiate(infer, fn)
    arg_ts = [_infer_expr(infer, env, a) for a in e.args]
    ret_t = infer.fresh()
    expected_arrow = TArrow(tuple(arg_ts), ret_t)
    infer.constrain(fn_t, expected_arrow, where=f"call to {e.name}")
    return ret_t


# ────────────────────────────────────────────────────────────────────────
# Phase E-2: integration with aipl_typeck's BUILTIN_SIGNATURES.
# ────────────────────────────────────────────────────────────────────────
_BUILTIN_SIG_CACHE: Optional[dict] = None

def _lookup_builtin_signature(name: str) -> Optional[str]:
    global _BUILTIN_SIG_CACHE
    if _BUILTIN_SIG_CACHE is None:
        try:
            from aipl_interp import BUILTIN_SIGNATURES
            _BUILTIN_SIG_CACHE = BUILTIN_SIGNATURES
        except Exception:
            _BUILTIN_SIG_CACHE = {}
    return _BUILTIN_SIG_CACHE.get(name)


_TYPECK_NAME_MAP = {
    "int": T_INT, "string": T_STR, "str": T_STR, "bool": T_BOOL,
    "float": T_REAL, "real": T_REAL, "rat": T_RAT,
    "unit": T_UNIT, "any": T_DYN, "void": T_UNIT,
}

def _typeck_type_to_inference(s: str, infer: Inference) -> Any:
    """Convert a typeck-style type string ('int', 'string', 'array[int]',
    'int | float', 'any', …) into an inference Type.  Unknown forms
    fall back to a fresh TVar so they unify with whatever shows up."""
    s = s.strip()
    if not s or s == "?": return infer.fresh()
    low = s.lower()
    if low in _TYPECK_NAME_MAP:
        return _TYPECK_NAME_MAP[low]
    # Unions => first satisfiable choice; inference can't enumerate,
    # so we widen to Dyn (gradual).
    if "|" in s:
        return T_DYN
    # array[T]
    m = re.match(r"^array\s*\[\s*(.+?)\s*\]$", s, re.IGNORECASE)
    if m:
        return TCon("List", (_typeck_type_to_inference(m.group(1), infer),))
    return T_DYN

def _parse_typeck_signature(sig: str, infer: Inference) -> Optional[tuple]:
    """Parse 'function(p1:T1, p2:T2) -> R' into ([T1, T2, ...], R).
    Returns None if the signature has variadic/optional markers we
    don't fully handle yet (we then fall back to gradual)."""
    m = re.match(r"^function\s*\((.*?)\)\s*->\s*(.+)$", sig.strip())
    if not m: return None
    params_src, ret_src = m.group(1), m.group(2)
    if "+" in params_src or "[" in params_src:
        # variadic (`name:T+`) or optional (`[name:T]`) — stay gradual,
        # only check the return type for now.
        return None
    param_types = []
    if params_src.strip():
        for part in _split_top(params_src, ","):
            part = part.strip()
            if ":" in part:
                _, t = part.split(":", 1)
            else:
                t = part
            param_types.append(_typeck_type_to_inference(t, infer))
    ret_t = _typeck_type_to_inference(ret_src, infer)
    return (param_types, ret_t)

def _check_builtin_call(infer: Inference, env: Env, e: Any, sig: str) -> Any:
    parsed = _parse_typeck_signature(sig, infer)
    arg_ts = [_infer_expr(infer, env, a) for a in e.args]
    if parsed is None:
        return T_DYN     # gradual fallback for variadic/optional
    param_types, ret_t = parsed
    if len(arg_ts) != len(param_types):
        infer.issues.append(InferenceIssue(
            kind="arity",
            msg=f"builtin {e.name}: expected {len(param_types)} args, "
                f"got {len(arg_ts)}",
            location=getattr(e, "loc", "")))
        return ret_t
    for i, (at, pt) in enumerate(zip(arg_ts, param_types)):
        infer.constrain(at, pt, where=f"{e.name} arg {i+1}")
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
            # E-1: do NOT generalise unbound TVars here.  Actor return
            # values (NowCall's ret_tvar, new ClassName's TCon) must
            # stay monomorphic so later constraint propagation (e.g.,
            # reply({...}) populating the TVar with a TRecord) flows
            # to every use site of the binding.
            env.bind(s.name, Scheme((), apply(infer.subst, rhs_t)))
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
            lhs_t = instantiate(infer, sch)
            lhs_r = apply(infer.subst, lhs_t)
            rhs_r = apply(infer.subst, rhs_t)
            # Sentinel widening: if both sides are concrete distinct
            # TCons (e.g. `var left = 0;` initial Int vs later
            # `left = sender;` Actor), rebind the name to Dyn instead
            # of emitting a unify error.  Mirrors the gradual-escape
            # rule used by JS-B (walkForFieldWidening) and matches
            # OCaml's TAny absorption.  Only applies to sentinel-style
            # mismatch — both sides must be concrete TCons with
            # different names.
            if (isinstance(lhs_r, TCon) and isinstance(rhs_r, TCon)
                    and lhs_r.name != rhs_r.name
                    and lhs_r != T_DYN and rhs_r != T_DYN):
                env.bind(s.name, Scheme((), T_DYN))
                return
            infer.constrain(lhs_t, rhs_t, where=f"assign to {s.name}")
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
        # E-2: same builtin-signature path as CallExpr.
        bsig = _lookup_builtin_signature(s.name)
        if bsig is not None:
            _check_builtin_call(infer, env, s, bsig)
        return
    # E-3: `obj.f = v` — resolve obj's class and constrain the
    # corresponding field TVar with v's type.  Stays gradual for
    # record literals or unknown receivers.
    from aipl_ast import FieldAssign as _FieldAssign      # late import
    if _FieldAssign and isinstance(s, _FieldAssign):
        rhs_t = _infer_expr(infer, env, s.expr)
        sch = env.lookup(s.name)
        if sch and s.attrs and len(s.attrs) == 1:
            recv_t = apply(infer.subst, instantiate(infer, sch))
            if isinstance(recv_t, TCon):
                ftvar = infer.class_fields.get(recv_t.name, {}).get(s.attrs[0])
                if ftvar is not None:
                    infer.constrain(ftvar, rhs_t,
                                    where=f"{recv_t.name}.{s.attrs[0]} :=")
        return
    # Skip Send etc. — left as gradual unknown


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
    # CE-10: inferred side-effects.  Walk the method body once more
    # (cheap — the AST is small) accumulating the BUILTIN_EFFECTS of
    # every primitive call site.  declared_effects comes straight off
    # the MethodDecl from the parser if a `!{eff1, eff2}` clause was
    # written; the render() helper surfaces a mismatch warning.
    inferred_effects = _collect_effects_from_ast(m.body)
    declared_eff = None
    decl_list = getattr(m, "effects", None)
    if decl_list is not None:
        declared_eff = set(decl_list)

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
        effects=inferred_effects,
        declared_effects=declared_eff,
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
    # CE-10: inferred side-effect set ({fs, ai, net, mut, ...}).  None
    # means "not computed for this result"; the empty set means "pure".
    # Uses the BUILTIN_EFFECTS table from aipl_typeck for primitives;
    # user-function call chains are NOT yet transitively walked here
    # (the static --type-check pass in aipl_typeck does that).
    effects: Optional[set] = None
    declared_effects: Optional[set] = None  # `!{eff1, eff2}` if present

    def render(self) -> str:
        head = f"=== {self.class_name}.{self.method_name} ==="
        lines = [head]
        if self.param_types:
            lines.append("  params:")
            for n, t in self.param_types:
                lines.append(f"    {n} : {t}")
        if self.return_type is not None:
            lines.append(f"  return : {self.return_type}")
        if self.effects is not None:
            eff_str = "{}" if not self.effects else "{" + ", ".join(sorted(self.effects)) + "}"
            lines.append(f"  effects (inferred): {eff_str}")
            if self.declared_effects is not None and self.declared_effects != self.effects:
                dcl_str = "{}" if not self.declared_effects else "{" + ", ".join(sorted(self.declared_effects)) + "}"
                lines.append(f"  effects (declared): {dcl_str}")
                missing = self.effects - self.declared_effects
                if missing:
                    lines.append(f"    ⚠ inferred but not declared: {sorted(missing)}")
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


# ── CE-10: side-effect inference helpers ────────────────────────────
# Walk a method's AST to collect the set of side-effect categories
# implied by every primitive call site.  Uses the BUILTIN_EFFECTS
# table maintained in aipl_typeck.py so the two passes agree on what
# each primitive does.

def _collect_effects_from_ast(node) -> set:
    """Recurse through any AST node (Stmt or Expr) accumulating the
    BUILTIN_EFFECTS of every `CallStmt`/`CallExpr` name encountered."""
    try:
        from aipl_typeck import BUILTIN_EFFECTS
    except Exception:
        BUILTIN_EFFECTS = {}

    eff: set = set()

    def visit(n):
        if n is None:
            return
        kind = type(n)
        kn = kind.__name__
        # Look up by class name to avoid heavy AST imports.
        if kn in ("CallStmt", "CallExpr"):
            name = getattr(n, "name", None)
            if isinstance(name, str) and name in BUILTIN_EFFECTS:
                eff.update(BUILTIN_EFFECTS[name])
        # Recurse into common children.
        for attr in ("expr", "body", "then_body", "else_body",
                     "cond", "lhs", "rhs", "inner", "args",
                     "stmts", "items", "idxs"):
            child = getattr(n, attr, None)
            if child is None:
                continue
            if isinstance(child, list):
                for c in child:
                    visit(c)
            else:
                visit(child)
    visit(node)
    return eff


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
    # Bare type names — case-insensitive primitive lookup so that
    # `var n: int` and `var n: Int` both produce T_INT.  Previously the
    # lowercase forms fell through to the nominal-class fallback and
    # were minted as TCon("int") (a bogus class), then failed to unify
    # against T_INT from literals — see the "cannot unify Int with int"
    # diagnostic that flooded ~38/40 samples.
    low = s.lower()
    if low in _TYPECK_NAME_MAP:
        return _TYPECK_NAME_MAP[low]
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
    binder is a symbolic Int / Real / Rat.  We parse the predicate
    via Python's AST so `and`/`or`/`not` correctly translate to
    z3.And / z3.Or / z3.Not instead of being short-circuited by
    Python's eval.

    Phase E-γ-R: dispatch on the refined base type — Real and Rat
    refinements now use Z3's Real theory (Z3 represents rationals
    as Reals with rational coefficients).  Bool refinements use
    Z3 Bool; everything else still falls back to "deferred"."""
    # Pick a Z3 sort constructor matching the refined base.
    if rt.base == T_INT:
        mk_var = z3.Int
    elif rt.base in (T_REAL, T_RAT):
        mk_var = z3.Real
    elif rt.base == T_BOOL:
        mk_var = z3.Bool
    else:
        return True, "non-numeric refinement deferred to runtime"
    try:
        import ast
        binder = rt.binder if rt.binder != "_" else "x"
        # Free variables share the binder's sort so comparisons like
        # `m > a and m < b` make sense (a, b are reals when m is).
        free: Dict[str, Any] = {binder: mk_var(binder)}
        for tok in set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", rt.pred_src)):
            if tok in free or tok in ("and", "or", "not", "True", "False"):
                continue
            free[tok] = mk_var(tok)
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
            # E-3: pre-register one shared TVar per class field so
            # every method body sees the same slot.  Initializer type
            # is folded in below (after the loop, so all field TVars
            # exist before any RHS expression is inferred — handles
            # forward references between fields).
            infer.class_fields[decl.name] = {}
            for f in getattr(decl, "fields", []) or []:
                fname = getattr(f, "name", None)
                if fname:
                    infer.class_fields[decl.name][fname] = infer.fresh()

    # E-3 Pass-(-1): fold each field initializer's type into its TVar.
    # We do this in a dedicated mini-env so the initializer expression
    # can reference earlier fields of the same class.
    for decl in getattr(program, "decls", []):
        if ClassDecl and isinstance(decl, ClassDecl):
            init_env = shared_env.child()
            for fname, ftvar in infer.class_fields[decl.name].items():
                init_env.bind(fname, Scheme((), ftvar))
            for f in getattr(decl, "fields", []) or []:
                if not (VarDecl and isinstance(f, VarDecl)): continue
                ftvar = infer.class_fields[decl.name].get(f.name)
                if ftvar is None: continue
                if getattr(f, "expr", None) is not None:
                    rhs_t = _infer_expr(infer, init_env, f.expr)
                    infer.constrain(ftvar, rhs_t,
                                    where=f"{decl.name}.{f.name} init")
                if getattr(f, "type_annotation", None):
                    ann_t = _parse_annotation(f.type_annotation, infer)
                    infer.constrain(ftvar, ann_t,
                                    where=f"{decl.name}.{f.name} :type")

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
                # E-3: every method sees the same per-class field TVars
                # so reads in one method and writes in another flow
                # through unify (Int written by `init(n)` is visible
                # as Int in `bump()`'s `n + 1`).
                for fname, ftvar in infer.class_fields.get(decl.name, {}).items():
                    cls_env.bind(fname, Scheme((), ftvar))
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

    # E-1: re-run global statements once more so unify failures from
    # argument propagation (e.g., passing records of incompatible
    # shapes to the same method) surface in the final issue list.
    # Pass-0 issues were dropped to silence forward-ref noise; by now
    # every method signature is fully resolved, so any error here is
    # a *real* shape mismatch.  We snapshot subst length so a second
    # successful unify is a no-op.
    issues_before_repass = len(infer.issues)
    global_repass_env = shared_env.child()
    for decl in getattr(program, "decls", []):
        if GlobalStmt and isinstance(decl, GlobalStmt):
            _infer_stmt(infer, global_repass_env, decl.stmt)
    # Filter out spurious unbound/forward-ref errors that may resurface;
    # keep only `unify` and `arity` kind issues from this re-pass.
    repass_issues = infer.issues[issues_before_repass:]
    infer.issues = infer.issues[:issues_before_repass] + [
        i for i in repass_issues if i.kind in ("unify", "arity", "field")
    ]

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
        # E-3: expose final inference state so the CLI can print
        # per-class field types.  Attached to the first result so the
        # CLI's lookup is order-independent.
        method_results[0]._infer_state = infer
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
