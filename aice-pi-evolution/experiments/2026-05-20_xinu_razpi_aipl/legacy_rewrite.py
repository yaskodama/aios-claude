#!/usr/bin/env python3
"""Translate legacy AIPL syntax to the current parser's accepted form.

Legacy patterns:
  object Foo { ... }               ->  class Foo { ... }
  float x = 0;                     ->  var x = 0.;     (force float literal)
  int   x = 0;                     ->  var x = 0;
  Foo bar;                         ->  var bar = new Foo();
  send target method();            ->  send target.method();
  send target method(args);        ->  send target.method(args);
  send target method;              ->  send target.method();
"""
import re, sys, pathlib

# 1) `object Foo` -> `class Foo`
RE_OBJECT = re.compile(r'\bobject\s+([A-Z]\w*)\s*\{')

# 2a-bare) `float x = N;` -> `var x = N.;`  (literal RHS → ensure `.`)
# Use `\b` boundary instead of `^` so multiple decls on the same line
# (`float y1 = 0; float x2 = 0;`) are all rewritten.
RE_FLOAT_DECL_LIT = re.compile(
    r'\bfloat\s+(\w+)\s*=\s*([0-9]+(?:\.[0-9]*)?);')

# 2a-expr) `float x = <expr>;` (RHS is anything) -> `var x = <expr>;`
RE_FLOAT_DECL_EXPR = re.compile(
    r'\bfloat\s+(\w+)\s*=\s*([^;]+);')

# 2b) `int x = N;` -> `var x = N;`
RE_INT_DECL = re.compile(
    r'\bint\s+(\w+)\s*=\s*([^;]+);')

# 2c) `object foo;`  as a field declaration → `var foo = nil;`
RE_OBJECT_FIELD = re.compile(
    r'^(\s*)object\s+([a-z]\w*)\s*;', re.MULTILINE)

# 3) `Foo bar;` at top-level (or anywhere) where Foo is a capitalised
#    identifier and bar is lower-case — becomes `var bar = new Foo();`
#    Must not match `class Foo bar { ... }` (already handled) or `var Foo`.
RE_INSTANTIATE = re.compile(
    r'^(\s*)([A-Z]\w*)\s+([a-z]\w*)\s*;\s*$', re.MULTILINE)

# 4) `send target method(args);` -> `send target.method(args);`
RE_SEND_PARENS = re.compile(
    r'\bsend\s+([a-zA-Z_]\w*)\s+([a-z]\w*)\s*\(([^)]*)\)\s*;')

# 5) `send target method;`  (no parens / no args)
RE_SEND_NOPAREN = re.compile(
    r'\bsend\s+([a-zA-Z_]\w*)\s+([a-z]\w*)\s*;')

# 6) `if EXPR then STMT; else STMT;` (possibly multi-line)
#    -> `if (EXPR) { STMT; } else { STMT; }`
RE_IF_THEN_ELSE = re.compile(
    r'\bif\s+([^;{}]+?)\s+then\s+([^;{}]+);\s*else\s+([^;{}]+);',
    re.DOTALL)

# 7) `if EXPR then STMT;` (no else) — last so it doesn't eat the else case
RE_IF_THEN = re.compile(
    r'\bif\s+([^;{}]+?)\s+then\s+([^;{}]+);',
    re.DOTALL)

def transform(src: str) -> str:
    out = RE_OBJECT.sub(r'class \1 {', src)
    # `object foo;` field decl FIRST so `object Foo { ... }` (handled above)
    # has already been changed to `class Foo { ... }` and we don't
    # accidentally match the opening brace line.
    out = RE_OBJECT_FIELD.sub(r'\1var \2 = nil;', out)
    # Float-literal form first, so `float angle = 0` becomes `var angle = 0.`
    # and the broader RE_FLOAT_DECL_EXPR doesn't strip the type into
    # `var angle = 0` (which would infer as int).
    out = RE_FLOAT_DECL_LIT.sub(
        lambda m: f"var {m.group(1)} = " +
                  (m.group(2) if '.' in m.group(2) else m.group(2) + '.') + ';',
        out)
    out = RE_FLOAT_DECL_EXPR.sub(r'var \1 = \2;', out)
    out = RE_INT_DECL.sub(r'var \1 = \2;', out)
    out = RE_INSTANTIATE.sub(r'\1var \3 = new \2();', out)
    out = RE_SEND_PARENS.sub(r'send \1.\2(\3);', out)
    out = RE_SEND_NOPAREN.sub(r'send \1.\2();', out)
    # if/then/else legacy form — translate AFTER send rewrites so we
    # don't accidentally eat the inner `;`s.
    out = RE_IF_THEN_ELSE.sub(
        lambda m: f"if ({m.group(1).strip()}) {{ {m.group(2).strip()}; }} else {{ {m.group(3).strip()}; }}",
        out)
    out = RE_IF_THEN.sub(
        lambda m: f"if ({m.group(1).strip()}) {{ {m.group(2).strip()}; }}",
        out)
    return out

def main():
    if len(sys.argv) < 2:
        sys.exit("usage: _legacy_rewrite.py <file.abcl> ...")
    for p in sys.argv[1:]:
        src = pathlib.Path(p).read_text()
        new = transform(src)
        if new == src:
            print(f"  unchanged: {p}")
        else:
            pathlib.Path(p).write_text(new)
            print(f"  rewrote : {p}")

if __name__ == '__main__':
    main()
