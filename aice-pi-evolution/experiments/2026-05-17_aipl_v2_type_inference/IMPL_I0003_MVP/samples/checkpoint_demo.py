#!/usr/bin/env python3
"""I-4 sample: checkpoint_and_resume.

Saves a tiny actor state, then "crashes" the script, then a second
invocation restores the state.  In practice the AIPL runtime would
call save_actor_state() at safe points (e.g., after each method) and
restore_actor_state() at actor (re-)instantiation.

Run:
    rm -rf /tmp/aipl_ck_demo
    AIPL_DIST_ENABLE=1 AIPL_DIST_CHECKPOINT_DIR=/tmp/aipl_ck_demo \\
        python3 checkpoint_demo.py save
    AIPL_DIST_ENABLE=1 AIPL_DIST_CHECKPOINT_DIR=/tmp/aipl_ck_demo \\
        python3 checkpoint_demo.py restore
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PYABCL = os.path.normpath(
    os.path.join(HERE, "..", "..", "..", "..", "..", "src", "python-aipl"))
sys.path.insert(0, PYABCL)

import aipl_dist  # noqa: E402


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "save"
    print(f"is_enabled() = {aipl_dist.is_enabled()}")
    print(f"checkpoint_dir() = {aipl_dist.checkpoint_dir()}")

    if mode == "save":
        state = {"counter": 42, "history": ["hello", "world"], "user": "Bob"}
        ok = aipl_dist.save_actor_state("MyActor", state)
        print(f"save_actor_state -> {ok}, state = {state}")
    elif mode == "restore":
        st = aipl_dist.restore_actor_state("MyActor")
        print(f"restore_actor_state -> {st}")
    else:
        print(f"unknown mode: {mode}")
        sys.exit(2)

    print()
    print(f"list_actor_states() = {aipl_dist.list_actor_states()}")


if __name__ == "__main__":
    main()
