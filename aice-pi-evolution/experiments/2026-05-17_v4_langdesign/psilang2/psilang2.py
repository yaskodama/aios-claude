#!/usr/bin/env python3
"""
PsiLang — a minimal ML-like functional language with arbitrary-precision
integers and rationals, evolved by MAP-Elites (see ../REPORT.md).

Top-5 consensus from the 2026-05-16_v2_langdesign evolution:
  paradigm              = functional family (5/5)
  type_system           = static_simple    (3/5, with hindley_milner/refinement options)
  arithmetic_primitives = arbitrary_int_plus_rational (3/5)
  control_flow          = pattern_match_fold + general_recursion (4/5)
  syntax_family         = ml_like                              (2/5)

This single file is the **whole language** — lexer, parser, AST,
evaluator, and stdlib — in roughly 800 lines.  Designed to be small
enough to read end-to-end (R4_ImplementabilityFeasibility), yet
expressive enough to write Chudnovsky binary-splitting for π
(R1_AlgorithmExpressivity).

Surface syntax (informal):

    # comment to end of line

    fn name (p1: T1, p2: T2) -> Ret = expr
    fn name (p)              -> Ret = expr     (parens optional for 1 arg)

    let x       = expr in body
    let (a, b)  = expr in body
    if cond then a else b
    match e with | pat1 -> e1 | pat2 -> e2 end
    e1; e2                                  -- sequence (no real effect; last value wins)

    (e1, e2)        -- 2-tuple
    [e1, e2, e3]    -- list
    []              -- empty list
    x :: xs         -- list cons

    Builtin Int        -- arbitrary precision (Python int)
    Builtin Rat        -- (num, den) auto-reduced
    Builtin Real       -- Decimal with caller-supplied precision
    Builtin Bool

Builtin functions:
    Int:    +  -  *  /  mod   ==  !=  <  >  <=  >=
    Bool:   and  or  not
    Rat:    rat(n,d)   rat_add   rat_sub   rat_mul   rat_div   rat_neg
            rat_inv    rat_num   rat_den   rat_from_int
    Real:   real_from_int   real_from_rat   real_sqrt   real_mul
            real_div         real_to_string  set_precision
    Misc:   fst   snd   length   emit   print

Run:    python3 psilang.py <file.psi>

Exit code 0 on success, 1 on error.
"""
from __future__ import annotations
import math
import re
import sys
from dataclasses import dataclass, field
from decimal import Decimal, getcontext
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


# ════════════════════════════════════════════════════════════════════════
# 1. LEXER
# ════════════════════════════════════════════════════════════════════════

# token kinds
KW = {"fn", "let", "in", "if", "then", "else", "match", "with", "end",
      "and", "or", "not", "true", "false"}

TOKEN_RE = re.compile(r"""
    \s+                           |   # whitespace
    \#[^\n]*                      |   # line comment
    (?P<NUM>[0-9][0-9_]*)         |   # digits, may have _ separators
    (?P<ID>[a-zA-Z_][a-zA-Z0-9_]*)|
    (?P<STR>"[^"]*")              |
    (?P<OP>->|::|==|!=|<=|>=|;|\|
        |[+\-*/(),=<>:\[\]])
""", re.VERBOSE)


@dataclass
class Token:
    kind: str
    text: str
    pos: int


# PsiLang2 (v4): refinement-type preprocessor.
# v4's top-1 genome includes refinement type annotations like
#     fn term(k: Int where k >= 0) -> Rat where 0 <= num <= den = ...
# but the v2 PsiLang parser only accepts `: ID` annotations.  Until a
# full refinement type checker arrives in v5, we strip `where <pred>`
# clauses at preprocessing.  The predicate runs to (in token order):
#   - `,`  or  `)`        — parameter list separator / close
#   - `=`  unless `==`    — let / def boundary
#   - the keyword `in`    — let-in boundary
#   - newline at top level
# This is conservative: complex predicates that span multiple lines
# are not supported (refactor onto one line if needed).
_WHERE_RE = re.compile(
    r'\bwhere\b'                                # the keyword
    r'(?:==|!=|<=|>=|[^,)\n=])*?'               # body: comparison ops atomic, or any non-stop char
    r'(?=,|\)|=(?!=)|\bin\b|\n)',               # stop before , ) bare-= in newline
    re.DOTALL,
)


def _strip_refinement(src: str) -> str:
    """Remove `where <predicate>` clauses (v4 refinement annotations).

    Skip comment lines so the design notes that *mention* `where`
    are not corrupted.  Each non-comment line is processed
    independently — refinement predicates that span multiple lines
    are not supported (refactor onto one line).
    """
    out = []
    for line in src.splitlines(keepends=True):
        if line.lstrip().startswith("#"):
            out.append(line)
        else:
            out.append(_WHERE_RE.sub('', line))
    return "".join(out)


def tokenize(src: str) -> List[Token]:
    src = _strip_refinement(src)         # v4: drop refinement clauses
    toks: List[Token] = []
    i = 0
    while i < len(src):
        m = TOKEN_RE.match(src, i)
        if not m:
            raise SyntaxError(f"unexpected char {src[i]!r} at pos {i}")
        if m.group(0).strip() == "" or m.group(0).startswith("#"):
            i = m.end(); continue
        text = m.group(0)
        if m.group("NUM"):
            toks.append(Token("NUM", text.replace("_", ""), i))
        elif m.group("ID"):
            kind = text if text in KW else "ID"
            toks.append(Token(kind, text, i))
        elif m.group("STR"):
            toks.append(Token("STR", text[1:-1], i))
        else:
            toks.append(Token(text, text, i))
        i = m.end()
    toks.append(Token("EOF", "", len(src)))
    return toks


# ════════════════════════════════════════════════════════════════════════
# 2. AST  (we don't need a typechecker — static_simple types are erased
#         at runtime; the parser accepts annotations but ignores them.)
# ════════════════════════════════════════════════════════════════════════

@dataclass
class IntLit:    n: int
@dataclass
class BoolLit:   b: bool
@dataclass
class StrLit:    s: str
@dataclass
class Var:       name: str
@dataclass
class BinOp:     op: str; l: 'Expr'; r: 'Expr'
@dataclass
class UnOp:      op: str; e: 'Expr'
@dataclass
class If:        cond: 'Expr'; then_: 'Expr'; else_: 'Expr'
@dataclass
class Let:       pat: 'Pat'; rhs: 'Expr'; body: 'Expr'
@dataclass
class Tuple:     items: list
@dataclass
class ListLit:   items: list
@dataclass
class Match:     scrut: 'Expr'; arms: list   # list of (pat, expr)
@dataclass
class Call:      fn: 'Expr'; args: list
@dataclass
class Seq:       e1: 'Expr'; e2: 'Expr'

# patterns
@dataclass
class PWildcard: pass
@dataclass
class PVar:      name: str
@dataclass
class PInt:      n: int
@dataclass
class PBool:     b: bool
@dataclass
class PTuple:    items: list
@dataclass
class PCons:     head: 'Pat'; tail: 'Pat'
@dataclass
class PNil:      pass

Expr = Union[IntLit, BoolLit, StrLit, Var, BinOp, UnOp, If, Let,
             Tuple, ListLit, Match, Call, Seq]
Pat  = Union[PWildcard, PVar, PInt, PBool, PTuple, PCons, PNil]


@dataclass
class FnDecl:
    name: str
    params: list           # list of (param_name, type_annot_str_or_None)
    ret_annot: Optional[str]
    body: Expr


@dataclass
class Program:
    decls: list            # list of FnDecl
    main: Optional[Expr]   # the trailing `let result = ... in emit(...)` (or any expr)


# ════════════════════════════════════════════════════════════════════════
# 3. PARSER  (recursive descent, Pratt-ish for binops)
# ════════════════════════════════════════════════════════════════════════

class Parser:
    def __init__(self, toks: List[Token]):
        self.toks = toks
        self.i = 0

    def peek(self) -> Token:                  return self.toks[self.i]
    def advance(self) -> Token:
        t = self.toks[self.i]; self.i += 1; return t
    def accept(self, kind: str) -> Optional[Token]:
        if self.peek().kind == kind: return self.advance()
        return None
    def expect(self, kind: str) -> Token:
        t = self.peek()
        if t.kind != kind:
            raise SyntaxError(f"expected {kind!r}, got {t.kind!r} ({t.text!r}) at pos {t.pos}")
        return self.advance()

    # ---- top level ----
    def parse_program(self) -> Program:
        decls = []
        main: Optional[Expr] = None
        while self.peek().kind != "EOF":
            if self.peek().kind == "fn":
                decls.append(self.parse_fn())
            else:
                main = self.parse_expr()
                break
        if self.peek().kind != "EOF":
            raise SyntaxError(f"junk after main expression: {self.peek()}")
        return Program(decls=decls, main=main)

    def parse_fn(self) -> FnDecl:
        self.expect("fn")
        name = self.expect("ID").text
        self.expect("(")
        params = []
        if self.peek().kind != ")":
            while True:
                pname = self.expect("ID").text
                ann = None
                if self.accept(":"):
                    ann = self.expect("ID").text
                params.append((pname, ann))
                if not self.accept(","):
                    break
        self.expect(")")
        ret_annot = None
        if self.accept("->"):
            ret_annot = self.expect("ID").text
        self.expect("=")
        body = self.parse_expr()
        return FnDecl(name=name, params=params, ret_annot=ret_annot, body=body)

    # ---- expressions ----
    # precedence (low → high): seq ; → if/let/match/lambda → or → and →
    #   cmp → :: → +- → */ mod → unary → app → atom
    def parse_expr(self) -> Expr:
        return self.parse_seq()

    def parse_seq(self) -> Expr:
        e = self.parse_or()
        while self.accept(";"):
            e2 = self.parse_or()
            e = Seq(e, e2)
        return e

    def parse_or(self) -> Expr:
        l = self.parse_and()
        while self.peek().kind == "or":
            self.advance()
            r = self.parse_and()
            l = BinOp("or", l, r)
        return l

    def parse_and(self) -> Expr:
        l = self.parse_cmp()
        while self.peek().kind == "and":
            self.advance()
            r = self.parse_cmp()
            l = BinOp("and", l, r)
        return l

    CMP_OPS = {"==", "!=", "<", ">", "<=", ">="}
    def parse_cmp(self) -> Expr:
        l = self.parse_cons()
        if self.peek().kind in self.CMP_OPS:
            op = self.advance().text
            r = self.parse_cons()
            return BinOp(op, l, r)
        return l

    def parse_cons(self) -> Expr:
        l = self.parse_add()
        if self.accept("::"):
            r = self.parse_cons()    # right-associative
            return BinOp("::", l, r)
        return l

    def parse_add(self) -> Expr:
        l = self.parse_mul()
        while self.peek().kind in ("+", "-"):
            op = self.advance().text
            r = self.parse_mul()
            l = BinOp(op, l, r)
        return l

    def parse_mul(self) -> Expr:
        l = self.parse_unary()
        while self.peek().kind in ("*", "/") or \
              (self.peek().kind == "ID" and self.peek().text == "mod"):
            op = self.advance().text
            r = self.parse_unary()
            l = BinOp(op, l, r)
        return l

    def parse_unary(self) -> Expr:
        if self.accept("-"):
            return UnOp("-", self.parse_unary())
        if self.peek().kind == "not":
            self.advance()
            return UnOp("not", self.parse_unary())
        return self.parse_app()

    def parse_app(self) -> Expr:
        e = self.parse_atom()
        # function application is f(a, b, c), explicit parens
        while self.peek().kind == "(" and isinstance(e, (Var, Call)):
            self.advance()
            args = []
            if self.peek().kind != ")":
                while True:
                    args.append(self.parse_expr())
                    if not self.accept(","):
                        break
            self.expect(")")
            e = Call(e, args)
        return e

    def parse_atom(self) -> Expr:
        t = self.peek()
        if t.kind == "NUM":
            self.advance()
            return IntLit(int(t.text))
        if t.kind == "true":
            self.advance(); return BoolLit(True)
        if t.kind == "false":
            self.advance(); return BoolLit(False)
        if t.kind == "STR":
            self.advance(); return StrLit(t.text)
        if t.kind == "ID":
            self.advance()
            return Var(t.text)
        if t.kind == "(":
            self.advance()
            if self.accept(")"):
                # () => unit (encoded as empty tuple)
                return Tuple([])
            e1 = self.parse_expr()
            if self.accept(","):
                items = [e1]
                while True:
                    items.append(self.parse_expr())
                    if not self.accept(","):
                        break
                self.expect(")")
                return Tuple(items)
            self.expect(")")
            return e1
        if t.kind == "[":
            self.advance()
            items = []
            if self.peek().kind != "]":
                while True:
                    items.append(self.parse_expr())
                    if not self.accept(","):
                        break
            self.expect("]")
            return ListLit(items)
        if t.kind == "if":
            self.advance()
            cond = self.parse_expr()
            self.expect("then")
            th = self.parse_expr()
            self.expect("else")
            el = self.parse_expr()
            return If(cond, th, el)
        if t.kind == "let":
            self.advance()
            pat = self.parse_pat()
            # optional type annotation in let — accept and discard
            if self.accept(":"):
                _ = self.expect("ID").text
            self.expect("=")
            rhs = self.parse_expr()
            self.expect("in")
            body = self.parse_expr()
            return Let(pat, rhs, body)
        if t.kind == "match":
            self.advance()
            scrut = self.parse_expr()
            self.expect("with")
            arms = []
            while self.accept("|"):
                p = self.parse_pat()
                self.expect("->")
                e = self.parse_or()    # arms can't contain top-level `;`
                arms.append((p, e))
            self.expect("end")
            return Match(scrut, arms)
        raise SyntaxError(f"unexpected token {t.kind!r} ({t.text!r}) at pos {t.pos}")

    # ---- patterns ----
    def parse_pat(self) -> Pat:
        p = self.parse_pat_atom()
        if self.accept("::"):
            tail = self.parse_pat()
            return PCons(p, tail)
        return p

    def parse_pat_atom(self) -> Pat:
        t = self.peek()
        if t.kind == "NUM":
            self.advance(); return PInt(int(t.text))
        if t.kind == "true":
            self.advance(); return PBool(True)
        if t.kind == "false":
            self.advance(); return PBool(False)
        if t.kind == "-":
            self.advance()
            n = self.expect("NUM").text
            return PInt(-int(n))
        if t.kind == "ID":
            self.advance()
            if t.text == "_":
                return PWildcard()
            return PVar(t.text)
        if t.kind == "(":
            self.advance()
            if self.accept(")"):
                return PTuple([])
            p1 = self.parse_pat()
            if self.accept(","):
                items = [p1]
                while True:
                    items.append(self.parse_pat())
                    if not self.accept(","):
                        break
                self.expect(")")
                return PTuple(items)
            self.expect(")")
            return p1
        if t.kind == "[":
            self.advance()
            self.expect("]")
            return PNil()
        raise SyntaxError(f"bad pattern at {t.kind!r}")


# ════════════════════════════════════════════════════════════════════════
# 4. VALUES + STDLIB
# ════════════════════════════════════════════════════════════════════════

# Values are plain Python objects:
#   Int  -> Python int                                 (arbitrary precision)
#   Bool -> Python bool
#   Str  -> Python str
#   Rat  -> tuple ("rat", num, den)  with gcd(num,den)=1, den>0
#   Real -> tuple ("real", Decimal)
#   Tup  -> tuple ("tup", e1, e2, ...)
#   List -> tuple ("list", [v1, v2, ...])              (Python list inside)
#   Fn   -> tuple ("fn", FnDecl, env)                  (closure)


def is_rat(v): return isinstance(v, tuple) and len(v) == 3 and v[0] == "rat"
def is_real(v): return isinstance(v, tuple) and len(v) == 2 and v[0] == "real"
def is_tup(v): return isinstance(v, tuple) and len(v) >= 1 and v[0] == "tup"
def is_list(v): return isinstance(v, tuple) and len(v) == 2 and v[0] == "list"


def mk_rat(n, d):
    if d == 0: raise ZeroDivisionError("rat: zero denominator")
    g = math.gcd(abs(int(n)), abs(int(d)))
    if d < 0: n, d = -n, -d
    return ("rat", int(n)//g, int(d)//g)


def rat_add(a, b):
    _, n1, d1 = a; _, n2, d2 = b
    return mk_rat(n1*d2 + n2*d1, d1*d2)

def rat_sub(a, b):
    _, n1, d1 = a; _, n2, d2 = b
    return mk_rat(n1*d2 - n2*d1, d1*d2)

def rat_mul(a, b):
    _, n1, d1 = a; _, n2, d2 = b
    return mk_rat(n1*n2, d1*d2)

def rat_div(a, b):
    _, n1, d1 = a; _, n2, d2 = b
    return mk_rat(n1*d2, d1*n2)

def rat_neg(a):
    _, n, d = a; return mk_rat(-n, d)

def rat_inv(a):
    _, n, d = a; return mk_rat(d, n)


def real_from_int(n):
    return ("real", Decimal(int(n)))

def real_from_rat(r, prec):
    _, n, d = r
    old = getcontext().prec
    getcontext().prec = max(28, int(prec))
    try:
        v = Decimal(n) / Decimal(d)
        return ("real", v)
    finally:
        getcontext().prec = old

def real_sqrt(r, prec):
    _, x = r
    old = getcontext().prec
    getcontext().prec = max(28, int(prec))
    try:
        return ("real", x.sqrt())
    finally:
        getcontext().prec = old

def real_add(a, b):
    _, x = a; _, y = b
    return ("real", x + y)

def real_sub(a, b):
    _, x = a; _, y = b
    return ("real", x - y)

def real_mul(a, b):
    _, x = a; _, y = b
    return ("real", x * y)

def real_div(a, b):
    _, x = a; _, y = b
    return ("real", x / y)

def real_neg(a):
    _, x = a
    return ("real", -x)

def real_to_string(r, n_decimal):
    _, x = r
    s = str(x)
    # keep "3." + n_decimal chars
    if "." not in s:
        return s
    head, tail = s.split(".", 1)
    if len(tail) > int(n_decimal):
        tail = tail[:int(n_decimal)]
    return f"{head}.{tail}"


def set_precision(p):
    getcontext().prec = max(28, int(p))
    return ("tup",)   # unit


# ════════════════════════════════════════════════════════════════════════
# 5. EVALUATOR  (tree-walker)
# ════════════════════════════════════════════════════════════════════════

class Env:
    def __init__(self, parent: Optional['Env'] = None):
        self.bindings: Dict[str, Any] = {}
        self.parent = parent
    def get(self, name: str) -> Any:
        if name in self.bindings: return self.bindings[name]
        if self.parent: return self.parent.get(name)
        raise NameError(f"unbound: {name}")
    def set(self, name: str, val: Any) -> None:
        self.bindings[name] = val
    def child(self) -> 'Env':
        return Env(self)


def match_pat(pat: Pat, val: Any, env: Env) -> bool:
    """Match `val` against `pat` and bind variables in `env`.  Return True
    on success, False on failure."""
    if isinstance(pat, PWildcard):
        return True
    if isinstance(pat, PVar):
        env.set(pat.name, val); return True
    if isinstance(pat, PInt):
        return isinstance(val, int) and val == pat.n
    if isinstance(pat, PBool):
        return isinstance(val, bool) and val == pat.b
    if isinstance(pat, PTuple):
        if not is_tup(val) or len(val) - 1 != len(pat.items): return False
        for p, v in zip(pat.items, val[1:]):
            if not match_pat(p, v, env): return False
        return True
    if isinstance(pat, PNil):
        return is_list(val) and len(val[1]) == 0
    if isinstance(pat, PCons):
        if not is_list(val) or len(val[1]) == 0: return False
        head = val[1][0]
        tail = ("list", val[1][1:])
        if not match_pat(pat.head, head, env): return False
        if not match_pat(pat.tail, tail, env): return False
        return True
    raise RuntimeError(f"bad pattern {pat}")


def eval_expr(e: Expr, env: Env) -> Any:
    if isinstance(e, IntLit):   return e.n
    if isinstance(e, BoolLit):  return e.b
    if isinstance(e, StrLit):   return e.s
    if isinstance(e, Var):      return env.get(e.name)
    if isinstance(e, UnOp):
        v = eval_expr(e.e, env)
        if e.op == "-":   return -v if isinstance(v, int) else rat_neg(v) if is_rat(v) else _real_neg(v)
        if e.op == "not": return not v
        raise RuntimeError(f"bad unop {e.op}")
    if isinstance(e, BinOp):
        # short-circuit
        if e.op == "and": return eval_expr(e.l, env) and eval_expr(e.r, env)
        if e.op == "or":  return eval_expr(e.l, env) or  eval_expr(e.r, env)
        l = eval_expr(e.l, env); r = eval_expr(e.r, env)
        return apply_binop(e.op, l, r)
    if isinstance(e, If):
        c = eval_expr(e.cond, env)
        return eval_expr(e.then_ if c else e.else_, env)
    if isinstance(e, Let):
        v = eval_expr(e.rhs, env)
        child = env.child()
        if not match_pat(e.pat, v, child):
            raise RuntimeError(f"let pattern did not match")
        return eval_expr(e.body, child)
    if isinstance(e, Tuple):
        return ("tup",) + tuple(eval_expr(it, env) for it in e.items)
    if isinstance(e, ListLit):
        return ("list", [eval_expr(it, env) for it in e.items])
    if isinstance(e, Match):
        v = eval_expr(e.scrut, env)
        for p, body in e.arms:
            child = env.child()
            if match_pat(p, v, child):
                return eval_expr(body, child)
        raise RuntimeError(f"non-exhaustive match: value = {v!r}")
    if isinstance(e, Call):
        fn = eval_expr(e.fn, env)
        args = [eval_expr(a, env) for a in e.args]
        return apply_fn(fn, args)
    if isinstance(e, Seq):
        eval_expr(e.e1, env)
        return eval_expr(e.e2, env)
    raise RuntimeError(f"unknown expr {e}")


def _real_neg(v):
    _, x = v; return ("real", -x)


def apply_binop(op, l, r):
    # Int / Int
    if isinstance(l, int) and isinstance(r, int):
        if op == "+":  return l + r
        if op == "-":  return l - r
        if op == "*":  return l * r
        if op == "/":  return l // r if r != 0 else (_ for _ in ()).throw(ZeroDivisionError("/ by 0"))
        if op == "mod":return l %  r
        if op == "==": return l == r
        if op == "!=": return l != r
        if op == "<":  return l <  r
        if op == ">":  return l >  r
        if op == "<=": return l <= r
        if op == ">=": return l >= r
    # Bool
    if isinstance(l, bool) and isinstance(r, bool) and op in ("==", "!="):
        return (l == r) if op == "==" else (l != r)
    # List cons
    if op == "::":
        if not is_list(r): raise RuntimeError(f"::: rhs must be list, got {r!r}")
        return ("list", [l] + list(r[1]))
    # String concat with +
    if op == "+" and isinstance(l, str) and isinstance(r, str):
        return l + r
    raise RuntimeError(f"binop {op} not defined for {type(l).__name__} / {type(r).__name__}")


def apply_fn(fn, args):
    """Apply a function with tail-call optimisation.

    A call in *tail position* — i.e. one that would have been the last
    thing the caller did — is turned into a trampoline jump instead of
    a Python recursive call.  Tail positions are detected by descending
    through If, Let, and Match: whichever branch wins, its result is
    the function's result.  When that result is itself a Call, we
    rebind `fn` + `args` and loop back to the top, reusing the Python
    frame.  Non-tail subexpressions still recurse via `eval_expr`.

    Without TCO, computing π by Machin's arctan (~7150 terms) blows
    Python's call stack despite `sys.setrecursionlimit`.
    """
    while True:
        if callable(fn):                                       # builtin
            return fn(*args)
        if not (isinstance(fn, tuple) and fn[0] == "fn"):
            raise RuntimeError(f"not callable: {fn!r}")
        _, decl, captured_env = fn
        if len(decl.params) != len(args):
            raise RuntimeError(f"{decl.name}: arity {len(decl.params)}, "
                               f"got {len(args)}")
        env = captured_env.child()
        for (pname, _ann), v in zip(decl.params, args):
            env.set(pname, v)
        body = decl.body
        # Descend through tail-position constructs without recursing.
        while True:
            if isinstance(body, If):
                cond = eval_expr(body.cond, env)
                body = body.then_ if cond else body.else_
                continue
            if isinstance(body, Let):
                rhs = eval_expr(body.rhs, env)
                env = env.child()
                if not match_pat(body.pat, rhs, env):
                    raise RuntimeError("let pattern did not match")
                body = body.body
                continue
            if isinstance(body, Match):
                v = eval_expr(body.scrut, env)
                hit = False
                for p, arm_body in body.arms:
                    arm_env = env.child()
                    if match_pat(p, v, arm_env):
                        env = arm_env
                        body = arm_body
                        hit = True
                        break
                if hit: continue
                raise RuntimeError(f"non-exhaustive match: {v!r}")
            if isinstance(body, Seq):
                # last value of a Seq is its tail position
                eval_expr(body.e1, env)
                body = body.e2
                continue
            if isinstance(body, Call):
                # Tail call: trampoline.
                fn = eval_expr(body.fn, env)
                args = [eval_expr(a, env) for a in body.args]
                break
            # Not a tail-position construct — evaluate and return.
            return eval_expr(body, env)


# ════════════════════════════════════════════════════════════════════════
# 6. BUILTINS + DRIVER
# ════════════════════════════════════════════════════════════════════════

def make_globals() -> Env:
    g = Env()
    # arithmetic on Rat
    g.set("rat", lambda n, d: mk_rat(n, d))
    g.set("rat_add", rat_add)
    g.set("rat_sub", rat_sub)
    g.set("rat_mul", rat_mul)
    g.set("rat_div", rat_div)
    g.set("rat_neg", rat_neg)
    g.set("rat_inv", rat_inv)
    g.set("rat_num", lambda r: r[1])
    g.set("rat_den", lambda r: r[2])
    g.set("rat_from_int", lambda n: mk_rat(n, 1))
    # Real
    g.set("real_from_int", real_from_int)
    g.set("real_from_rat", real_from_rat)
    g.set("real_sqrt", real_sqrt)
    g.set("real_add", real_add)
    g.set("real_sub", real_sub)
    g.set("real_mul", real_mul)
    g.set("real_div", real_div)
    g.set("real_neg", real_neg)
    g.set("real_to_string", real_to_string)
    g.set("set_precision", set_precision)
    # generic
    g.set("fst",   lambda t: t[1])
    g.set("snd",   lambda t: t[2])
    g.set("length", lambda l: len(l[1]) if is_list(l) else len(l)-1)
    g.set("emit",  lambda s: (print(s), ("tup",))[1])
    g.set("print", lambda *a: (print(*a), ("tup",))[1])
    g.set("int_to_string", lambda n: str(int(n)))
    # Int "stdlib" — same level as +, *.  Provided as builtins so the
    # user's PsiLang code does not need 4000-deep recursion just to
    # compute (6k)! for the leaf terms of binary splitting.
    g.set("int_fact", lambda n: _fact(int(n)))
    g.set("int_pow",  lambda b, e: int(b) ** int(e))
    g.set("int_abs",  lambda n: abs(int(n)))
    g.set("int_sign", lambda n: (1 if n > 0 else -1 if n < 0 else 0))
    return g


def _fact(n: int) -> int:
    if n < 0: raise ValueError("int_fact: negative")
    r = 1
    for k in range(2, n + 1):
        r *= k
    return r


def run_program(program: Program) -> Any:
    env = make_globals()
    # 1st pass: insert all fn decls so they can be mutually recursive
    for decl in program.decls:
        env.set(decl.name, ("fn", decl, env))
    # eval main, if any
    if program.main is not None:
        return eval_expr(program.main, env)
    return ("tup",)


def main():
    if len(sys.argv) < 2:
        print("usage: psilang.py <file.psi>", file=sys.stderr); return 2
    sys.setrecursionlimit(100_000)   # binary-splitting tree-walker is deep
    src = open(sys.argv[1], encoding="utf-8").read()
    try:
        toks = tokenize(src)
        prog = Parser(toks).parse_program()
        run_program(prog)
        return 0
    except Exception as exc:
        print(f"[psilang error] {type(exc).__name__}: {exc}", file=sys.stderr)
        import traceback; traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
