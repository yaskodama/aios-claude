"""CLI entry point for the type-inferred Python AIPL.

Sibling of `src/python-aipl/aipl_main.py`, but runs full Hindley-Milner
type inference instead of annotation-based gradual checking.  All
runtime modules (parser, interpreter, AI, remote, dashboard) are
imported from `../python-aipl/` — only the type checker differs.

Usage:
    python3 aipl_main.py program.abcl
        [--no-typecheck] [--dump-types]
        [--timeout 2.0] [--idle-ms 120]
        [--dashboard PORT]
"""

import argparse
import os
import sys

# Make the sibling python-aipl directory importable so we get parser /
# interp / AI etc. without duplicating any of them here.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SIB  = os.path.join(_HERE, "..", "python-aipl")

# Insert HERE first so our `aipl_infer.py` shadows nothing (it's unique),
# and SIB second so all other module imports resolve to python-aipl.
sys.path.insert(0, _HERE)
sys.path.insert(1, _SIB)

from aipl_parser import parse_file
from aipl_interp import Interpreter
from aipl_infer import check_program, render_result


def main():
    ap = argparse.ArgumentParser(prog="python-aipl-inferred",
        description="Python AIPL with full Hindley-Milner type inference "
                    "(annotations on var/method/function are ignored).")
    ap.add_argument("source", nargs="?",
                    help="path to a .abcl file (omit to start an interactive REPL)")
    ap.add_argument("--timeout", type=float, default=2.0,
                    help="max seconds to wait for actors to drain (default 2.0)")
    ap.add_argument("--idle-ms", type=int, default=120,
                    help="ms of consecutive idle before exiting (default 120)")
    ap.add_argument("--ast", action="store_true",
                    help="print the parsed AST and exit")
    ap.add_argument("--no-typecheck", action="store_true",
                    help="skip HM inference; run program directly (gradual)")
    ap.add_argument("--dump-types", action="store_true",
                    help="print inferred field & method types, then continue")
    ap.add_argument("--dashboard", type=int, default=0, metavar="PORT",
                    help="serve a live AI-OS usage dashboard on http://127.0.0.1:PORT/")
    args = ap.parse_args()

    if args.dashboard:
        from aipl_dashboard import start as start_dashboard
        start_dashboard(args.dashboard)

    if args.source is None:
        from aipl_interp import run_repl
        run_repl()
        return

    try:
        program = parse_file(args.source)
    except Exception as e:
        print(f"[parse error] {e}", file=sys.stderr)
        sys.exit(1)

    if args.ast:
        from pprint import pprint
        pprint(program)
        return

    if not args.no_typecheck:
        result = check_program(program)
        if args.dump_types:
            print(render_result(result), file=sys.stderr)
        if not result.ok:
            for err in result.errors:
                print(f"[type error] {err}", file=sys.stderr)
            print(f"[abort] {len(result.errors)} type error(s) "
                  f"(use --no-typecheck to skip)", file=sys.stderr)
            sys.exit(2)

    interp = Interpreter(program)
    try:
        interp.run(idle_ms=args.idle_ms, timeout_s=args.timeout)
    except KeyboardInterrupt:
        interp.scheduler.shutdown()


if __name__ == "__main__":
    main()
