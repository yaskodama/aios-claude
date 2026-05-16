"""PhiLang parser — converts a `.phi` source file into a `Phase` dataclass.

PhiLang grammar (informal, matches REPORT.md §6.1):

    program       ::= phase_decl guarantees_block?

    phase_decl    ::= "phase" IDENT header_clause* "{" body_stmt* "}"
    header_clause ::= "within"   duration "and" cost
                   |  "drains"   "for" duration "idle" duration
                   |  "uses"     STRING_LIKE
                   |  "caffeine" "if" expr

    body_stmt     ::= IDENT "=" value
                   |  "every call has policy" "{" policy_pair* "}"
                   |  "after every" INT IDENT "{" action_stmt* "}"

    action_stmt   ::= "checkpoint" IDENT "to" QUOTED_STRING

    guarantees_block ::= "guarantees" "{" guarantee_clause* "}"
    guarantee_clause ::= IDENT ("=" value)?

The parser is line-oriented and intentionally tolerant: it relies on
newlines + leading/trailing whitespace + curly braces.  Block depth is
tracked explicitly so nested `{ ... }` (e.g. `after every` inside the
phase body) works correctly.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------

@dataclass
class AfterClause:
    n: int                # e.g. 1000
    unit: str             # "digits" | "individual" | …
    action: Dict[str, str] = field(default_factory=dict)


@dataclass
class Phase:
    name: str = ""
    within: Dict[str, float] = field(default_factory=dict)
    drains: Dict[str, float] = field(default_factory=dict)
    uses: str = ""
    caffeine_if: str = ""
    body: Dict[str, str] = field(default_factory=dict)
    every_call_policy: Dict[str, str] = field(default_factory=dict)
    after_clauses: List[AfterClause] = field(default_factory=list)
    guarantees: Dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers (also used by the interpreter)
# ---------------------------------------------------------------------------

def parse_duration(s: str) -> float:
    """ '60 s' → 60.0, '5 min' → 300.0, '2 h' → 7200.0, '60_000 ms' → 60.0 """
    s = s.strip().rstrip(";")
    m = re.match(r"([\d_]+(?:\.\d+)?)\s*(s|sec|min|h|hr|ms)\b", s)
    if not m:
        raise ValueError(f"bad duration: {s!r}")
    n = float(m.group(1).replace("_", ""))
    u = m.group(2)
    return {"s": n, "sec": n, "min": n * 60, "h": n * 3600,
            "hr": n * 3600, "ms": n / 1000}[u]


def parse_cost(s: str) -> float:
    """ '$0.30' → 0.30, '$1.50' → 1.50 """
    m = re.match(r"\$([\d_]+(?:\.\d+)?)", s.strip().rstrip(";"))
    if not m:
        raise ValueError(f"bad cost: {s!r}")
    return float(m.group(1).replace("_", ""))


def parse_int_literal(s: str) -> int:
    """ '10_000' → 10000, '60' → 60 """
    return int(s.strip().rstrip(";").replace("_", ""))


def _strip_inline_comment(line: str) -> str:
    # Allow '# ...' comments anywhere except inside quoted strings.
    out = []
    in_q = False
    for ch in line:
        if ch == '"':
            in_q = not in_q
        if ch == "#" and not in_q:
            break
        out.append(ch)
    return "".join(out).rstrip()


# ---------------------------------------------------------------------------
# Tokenisation: split source into trimmed non-empty lines
# ---------------------------------------------------------------------------

def _tokenise(src: str) -> List[str]:
    out = []
    for raw in src.splitlines():
        line = _strip_inline_comment(raw).strip()
        if line:
            out.append(line)
    return out


# ---------------------------------------------------------------------------
# Block extraction
# ---------------------------------------------------------------------------

def _find_block(lines: List[str], start: int) -> tuple:
    """Given `start` points to a line ending in '{' (or just '{'),
    return (inner_lines, end_index) where inner_lines is the list of
    raw lines strictly inside the matching braces and end_index points
    past the closing '}'."""
    depth = 0
    # The opening brace may be on `lines[start]` itself
    i = start
    if "{" in lines[i]:
        depth += lines[i].count("{") - lines[i].count("}")
        i += 1
    inner = []
    while i < len(lines) and depth > 0:
        depth += lines[i].count("{") - lines[i].count("}")
        if depth <= 0:
            return inner, i + 1
        inner.append(lines[i])
        i += 1
    raise SyntaxError(f"unterminated '{{' starting at line {start}")


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_phi(src: str) -> Phase:
    lines = _tokenise(src)
    if not lines:
        raise SyntaxError("empty source")
    phase = Phase()
    i = 0

    # 1) phase header
    m = re.match(r"phase\s+(\w+)\s*$", lines[i])
    if not m:
        raise SyntaxError(f"expected 'phase NAME', got: {lines[i]!r}")
    phase.name = m.group(1)
    i += 1

    # 2) header clauses until line containing '{'
    while i < len(lines) and "{" not in lines[i]:
        line = lines[i]
        if line.startswith("within"):
            m = re.match(r"within\s+(.+?)\s+and\s+(\$.+)", line)
            if m:
                phase.within["wall_s"] = parse_duration(m.group(1))
                phase.within["cost_usd"] = parse_cost(m.group(2))
        elif line.startswith("drains"):
            m = re.match(r"drains\s+for\s+(.+?)\s+idle\s+(.+)", line)
            if m:
                phase.drains["for_s"] = parse_duration(m.group(1))
                phase.drains["idle_s"] = parse_duration(m.group(2))
        elif line.startswith("uses"):
            phase.uses = line[len("uses"):].strip().rstrip(";")
        elif line.startswith("caffeine if"):
            phase.caffeine_if = line[len("caffeine if"):].strip().rstrip(";")
        else:
            raise SyntaxError(f"unknown header clause: {line!r}")
        i += 1

    if i >= len(lines):
        raise SyntaxError("missing '{' for phase body")

    # 3) phase body
    body_lines, i = _find_block(lines, i)
    _parse_body(body_lines, phase)

    # 4) guarantees block (optional, top-level after phase)
    while i < len(lines) and not lines[i].startswith("guarantees"):
        i += 1
    if i < len(lines):
        gline = lines[i]
        # 'guarantees {' or 'guarantees\n{'
        if "{" not in gline and i + 1 < len(lines) and lines[i + 1].startswith("{"):
            i += 1
        g_lines, _ = _find_block(lines, i)
        _parse_guarantees(g_lines, phase)

    return phase


def _parse_body(lines: List[str], phase: Phase) -> None:
    i = 0
    while i < len(lines):
        line = lines[i]

        # nested block: every call has policy { ... }
        if line.startswith("every call has policy"):
            inner, end = _find_block(lines, i)
            for pl in inner:
                m = re.match(r"(\w+)\s*:\s*(.+)", pl)
                if m:
                    phase.every_call_policy[m.group(1)] = m.group(2).strip().rstrip(";")
            i = end
            continue

        # nested block: after every N UNIT { ... }
        if line.startswith("after every"):
            mh = re.match(r"after every\s+([\d_]+)\s+(\w+)\s*\{?", line)
            if not mh:
                raise SyntaxError(f"bad after-every header: {line!r}")
            n = parse_int_literal(mh.group(1))
            unit = mh.group(2)
            inner, end = _find_block(lines, i)
            action = {}
            for al in inner:
                ma = re.match(r'checkpoint\s+(\w+)\s+to\s+"([^"]+)"', al)
                if ma:
                    action = {"type": "checkpoint",
                              "what": ma.group(1),
                              "path": ma.group(2)}
            phase.after_clauses.append(AfterClause(n=n, unit=unit, action=action))
            i = end
            continue

        # plain key = value
        m = re.match(r"(\w+)\s*=\s*(.+)", line)
        if m:
            phase.body[m.group(1)] = m.group(2).strip().rstrip(";")
        i += 1


def _parse_guarantees(lines: List[str], phase: Phase) -> None:
    for raw in lines:
        line = raw.strip().rstrip(";")
        if not line:
            continue
        m = re.match(r"(\w+)\s*=\s*(.+)", line)
        if m:
            phase.guarantees[m.group(1)] = m.group(2).strip()
        else:
            # boolean form: "no_silent_death", "partial_resume_on_kill"
            phase.guarantees[line] = True


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: philang_parser.py <program.phi>", file=sys.stderr)
        sys.exit(2)
    with open(sys.argv[1], encoding="utf-8") as f:
        ph = parse_phi(f.read())
    print(f"phase = {ph.name}")
    print(f"  within     = {ph.within}")
    print(f"  drains     = {ph.drains}")
    print(f"  uses       = {ph.uses!r}")
    print(f"  caffeine_if= {ph.caffeine_if!r}")
    print(f"  body       = {ph.body}")
    for c in ph.after_clauses:
        print(f"  after every {c.n} {c.unit}: {c.action}")
    print(f"  guarantees = {ph.guarantees}")
