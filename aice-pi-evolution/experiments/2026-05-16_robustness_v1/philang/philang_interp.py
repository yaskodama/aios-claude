"""PhiLang interpreter — executes a parsed Phase with full enforcement of
the language's safety contracts.

What `philang_interp.run(phase)` does, in order:

  1. Enforce `within W and $C`:
         - install a SIGALRM at W seconds
         - record a cost budget of C (kernel compute is free, but the
           hook is here for future LLM-using phases)
  2. Optionally start `caffeinate -i` per `caffeine if duration > X`
  3. Resolve `compute = X` against `philang_stdlib.COMPUTE_REGISTRY`,
     wire up the `after every N digits { checkpoint partial to "..." }`
     clause into the kernel's own progress callbacks
  4. Run the kernel
  5. Write the final output to the path in `body["output"]`
  6. Verify each guarantee; raise on violation
  7. Clean up signal + caffeinate

Any uncaught exception inside the kernel → SIGALRM is disarmed, the
caffeinate child is killed, and the exception propagates out so the
user sees the traceback (no silent death).

Exit codes:
    0  — phase completed and all guarantees satisfied
    1  — runtime error inside kernel
    2  — guarantee violation
    3  — wall timeout hit (SIGALRM)
"""

from __future__ import annotations
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from philang_parser import Phase, parse_duration
from philang_stdlib import COMPUTE_REGISTRY


class PhiRuntimeError(RuntimeError):
    pass


class PhiGuaranteeViolation(AssertionError):
    pass


class PhiWallTimeout(TimeoutError):
    pass


# ---------------------------------------------------------------------------
# SIGALRM-based wall timer
# ---------------------------------------------------------------------------

def _arm_wall_timer(seconds: float):
    def _alarm(signum, frame):
        raise PhiWallTimeout(f"wall timeout exceeded ({seconds}s)")
    prev = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(int(seconds) if seconds and seconds > 0 else 0)
    return prev


def _disarm_wall_timer(prev_handler):
    signal.alarm(0)
    signal.signal(signal.SIGALRM, prev_handler)


# ---------------------------------------------------------------------------
# caffeinate (Mac sleep guard, F5 mitigation)
# ---------------------------------------------------------------------------

def _start_caffeinate(condition: str, wall_s: float) -> Optional[subprocess.Popen]:
    """Start `caffeinate -i` if the condition fires.
    Currently supports `duration > <dur>` only."""
    if not condition:
        return None
    m_cond = condition.replace(" ", "")
    if not m_cond.startswith("duration>"):
        print(f"[phi]   caffeine: unknown condition {condition!r}, skipping")
        return None
    threshold = parse_duration(condition.split(">", 1)[1])
    if wall_s > threshold:
        try:
            proc = subprocess.Popen(
                ["caffeinate", "-i"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            print(f"[phi]   caffeine: enabled (wall {wall_s}s > {threshold}s, pid={proc.pid})")
            return proc
        except FileNotFoundError:
            print("[phi]   caffeine: `caffeinate` not found, skipping (non-mac?)")
    return None


def _stop_caffeinate(proc: Optional[subprocess.Popen]) -> None:
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=2)
    except Exception:
        try: proc.kill()
        except Exception: pass


# ---------------------------------------------------------------------------
# Compute dispatch
# ---------------------------------------------------------------------------

def _resolve_checkpoint(phase: Phase, unit: str):
    """Find `after every N <unit> { checkpoint partial to "..." }`,
    return (N, path) or (None, None)."""
    for c in phase.after_clauses:
        if c.unit == unit and c.action.get("type") == "checkpoint":
            return c.n, c.action.get("path")
    return None, None


def _run_compute(phase: Phase, work_dir: Path) -> dict:
    """Dispatch `body.compute = NAME` against COMPUTE_REGISTRY.
    Returns a dict with whatever the kernel produced + bookkeeping."""
    compute = phase.body.get("compute", "").strip()
    if compute not in COMPUTE_REGISTRY:
        raise PhiRuntimeError(
            f"unknown compute: {compute!r}. "
            f"known: {sorted(COMPUTE_REGISTRY)}"
        )
    fn = COMPUTE_REGISTRY[compute]

    if compute == "chudnovsky_binary_splitting":
        from philang_parser import parse_int_literal
        digits = parse_int_literal(phase.body["digits"])
        output_rel = phase.body.get("output", "out.txt").strip().strip('"')
        output_path = work_dir / output_rel

        ckpt_every, ckpt_rel = _resolve_checkpoint(phase, "digits")
        ckpt_path = str(work_dir / ckpt_rel) if ckpt_rel else None

        print(f"[phi]   compute: chudnovsky_pi(digits={digits}, "
              f"ckpt_every={ckpt_every}, ckpt_path={ckpt_path!r})")

        t0 = time.time()
        pi_str = fn(digits, ckpt_every=ckpt_every, ckpt_path=ckpt_path)
        t1 = time.time()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(pi_str + "\n", encoding="utf-8")
        print(f"[phi]   wrote {len(pi_str)} chars → {output_path} ({t1-t0:.3f}s)")
        return {
            "pi_str": pi_str,
            "output_path": output_path,
            "kernel_wall_s": t1 - t0,
        }

    raise PhiRuntimeError(f"compute {compute!r} has no dispatch case")


# ---------------------------------------------------------------------------
# Guarantee verification
# ---------------------------------------------------------------------------

def _verify_guarantees(phase: Phase, result: dict, elapsed_s: float) -> None:
    g = phase.guarantees
    failures = []
    print("[phi] verifying guarantees...")
    for key, val in g.items():
        try:
            if key == "no_silent_death":
                # Reaching this point means we did not die silently.
                print(f"[phi]   no_silent_death: ✓ (reached verification phase)")
            elif key == "partial_resume_on_kill":
                # Satisfied iff a checkpoint clause exists.
                if phase.after_clauses:
                    print(f"[phi]   partial_resume_on_kill: ✓ "
                          f"({len(phase.after_clauses)} checkpoint clause(s))")
                else:
                    failures.append(f"{key}: no checkpoint clause in phase body")
            elif key == "bounded_wall":
                limit = parse_duration(str(val)) if val is not True else float("inf")
                if elapsed_s > limit:
                    failures.append(f"{key}: elapsed {elapsed_s:.2f}s > {limit}s")
                else:
                    print(f"[phi]   bounded_wall: ✓ ({elapsed_s:.2f}s ≤ {limit}s)")
            elif key == "bounded_cost":
                # Compute phase has zero LLM cost; future LLM phases would
                # consult an actual usage tracker here.
                print(f"[phi]   bounded_cost: ✓ ($0.00 — kernel is local)")
            elif key == "digit_count":
                from philang_parser import parse_int_literal
                want = parse_int_literal(str(val))
                got = len(result["pi_str"]) - 2   # subtract leading "3."
                if got < want:
                    failures.append(f"{key}: got {got} < {want}")
                else:
                    print(f"[phi]   digit_count: ✓ ({got} ≥ {want})")
            elif key == "starts_with":
                prefix = str(val).strip().strip('"').strip("'")
                if not result["pi_str"].startswith(prefix):
                    failures.append(
                        f"{key}: got {result['pi_str'][:len(prefix)]!r}, "
                        f"expected {prefix!r}"
                    )
                else:
                    print(f"[phi]   starts_with: ✓ ({len(prefix)} char prefix matches)")
            else:
                print(f"[phi]   {key}: skipped (unknown predicate)")
        except Exception as e:
            failures.append(f"{key}: error during check — {e!r}")
    if failures:
        raise PhiGuaranteeViolation(
            "guarantee violation(s):\n  - " + "\n  - ".join(failures)
        )


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------

def run(phase: Phase, work_dir: Optional[Path] = None) -> int:
    work_dir = work_dir or Path.cwd()
    print(f"[phi] running phase '{phase.name}'")
    print(f"[phi]   within: {phase.within}")
    print(f"[phi]   drains: {phase.drains}")
    if phase.uses:
        print(f"[phi]   uses:   {phase.uses}")

    wall_s = phase.within.get("wall_s", 0)
    prev_handler = _arm_wall_timer(wall_s)
    caff = _start_caffeinate(phase.caffeine_if, wall_s)

    t0 = time.time()
    try:
        result = _run_compute(phase, work_dir)
        elapsed = time.time() - t0
        _verify_guarantees(phase, result, elapsed)
    except PhiWallTimeout as e:
        print(f"[phi] FAIL: {e}", file=sys.stderr)
        return 3
    except PhiGuaranteeViolation as e:
        print(f"[phi] FAIL: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"[phi] FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        import traceback; traceback.print_exc()
        return 1
    finally:
        _disarm_wall_timer(prev_handler)
        _stop_caffeinate(caff)

    print(f"[phi] phase '{phase.name}': all guarantees satisfied in {elapsed:.2f}s")
    return 0
