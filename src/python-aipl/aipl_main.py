"""CLI entry point for the Python AIPL interpreter.

Usage:
    python3 abcl_main.py program.abcl [--timeout 5.0] [--idle-ms 120]
"""

import argparse
import os
import sys

# Allow running this file directly from inside src/python-abcl/.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aipl_parser import parse_file
from aipl_interp import Interpreter


def main():
    ap = argparse.ArgumentParser(prog="python-abcl")
    ap.add_argument("source", nargs="?",
                    help="path to a .abcl file (omit to start an interactive REPL)")
    ap.add_argument("--timeout", type=float, default=5.0,
                    help="max seconds to wait for actors to drain (default 5.0)")
    ap.add_argument("--idle-ms", type=int, default=120,
                    help="ms of consecutive idle before exiting (default 120)")
    ap.add_argument("--ast", action="store_true",
                    help="print the parsed AST and exit")
    ap.add_argument("--type-check", action="store_true",
                    help="run the gradual type checker before executing; print "
                         "any issues to stderr (program still runs unless --strict)")
    ap.add_argument("--strict", action="store_true",
                    help="when combined with --type-check, abort on type errors")
    ap.add_argument("--transient", action="store_true",
                    help="(Phase 16) insert runtime type checks at every "
                         "annotated boundary (call args, var-decl rhs); "
                         "raise TransientCastError on any -> T mismatch")
    ap.add_argument("--infer", action="store_true",
                    help="(Phase C/D) run aipl_inference.py — constraint-based "
                         "Hindley-Milner inference with Z3 refinement check; "
                         "print inferred types per method to stderr and exit "
                         "(does not run the program)")
    ap.add_argument("--check", action="store_true",
                    help="(Phase E-2) run both --type-check and --infer in "
                         "one go and print a unified summary; exits without "
                         "running the program")
    ap.add_argument("--dashboard", type=int, default=0, metavar="PORT",
                    help="serve a live AI-OS usage dashboard on http://127.0.0.1:PORT/")
    args = ap.parse_args()

    if args.dashboard:
        from aipl_dashboard import start as start_dashboard
        start_dashboard(args.dashboard)

    if args.source is None:
        # Interactive REPL — useful for poking at actors live or
        # exploring the language without writing a file first.
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

    # Phase E-2: `--check` is a superset of `--type-check` + `--infer`.
    do_typeck = args.type_check or args.check
    do_infer  = args.infer       or args.check

    if do_typeck:
        from aipl_typeck import check as _typeck
        from aipl_interp import BUILTIN_SIGNATURES
        if args.check:
            print("=== --type-check (nominal + signature + effects) ===",
                  file=sys.stderr)
        issues = _typeck(program, BUILTIN_SIGNATURES)
        if issues:
            for i in issues:
                print(i.render(), file=sys.stderr)
            print(f"[type] {len(issues)} issue(s).", file=sys.stderr)
            if args.strict and not args.check:
                sys.exit(2)
        else:
            print("[type] no issues.", file=sys.stderr)
        if args.check:
            print(file=sys.stderr)

    if do_infer:
        from aipl_inference import infer_program, apply
        if args.check:
            print("=== --infer (HM + refinement + structural) ===",
                  file=sys.stderr)
        results = infer_program(program)
        total_issues = 0
        total_refs   = 0
        for r in results:
            print(r.render(), file=sys.stderr)
            print(file=sys.stderr)
            total_issues += len(r.issues)
            total_refs   += len(r.refinement_issues)
        # E-3: surface per-class field types from infer.class_fields.
        # The driver attaches the final Inference state to results[0].
        infer_state = getattr(results[0], "_infer_state", None) if results else None
        if infer_state and infer_state.class_fields:
            print("=== class fields ===", file=sys.stderr)
            for cls, fields in infer_state.class_fields.items():
                if not fields: continue
                print(f"  {cls}:", file=sys.stderr)
                for fname, ftvar in fields.items():
                    t = apply(infer_state.subst, ftvar)
                    print(f"    {fname} : {t}", file=sys.stderr)
            print(file=sys.stderr)
        print(f"[infer] {len(results)} method(s), {total_issues} unify issue(s), "
              f"{total_refs} refinement issue(s)", file=sys.stderr)
        if args.strict and (total_issues or total_refs):
            sys.exit(3)
        return                              # --infer / --check does not run the program

    if do_typeck:                           # --type-check alone: exit here
        return

    if args.dashboard:
        # Dashboard mode: hand the program lifecycle to the dashboard so it
        # can switch between programs at runtime (it shows live actors +
        # state + a console).  Run the initial program in a dashboard-managed
        # thread and keep the process alive so switching stays possible.
        import aipl_dashboard, time
        aipl_dashboard.configure_programs(args.source)
        print(f"[dashboard] actors view: "
              f"http://127.0.0.1:{args.dashboard}/actors")
        print("[dashboard] program is NOT started — press Start in the browser")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return

    interp = Interpreter(program, transient_checks=args.transient)
    try:
        interp.run(idle_ms=args.idle_ms, timeout_s=args.timeout)
    except KeyboardInterrupt:
        interp.scheduler.shutdown()


if __name__ == "__main__":
    main()
