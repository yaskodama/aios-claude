#!/usr/bin/env python3
"""mesh.py — bring up / drive a mesh of soft-Xinu N-Queens worker nodes.

Each node is a separate `aipl_main.py nq_worker_<port>.abcl` process that
exposes the actor `worker` over the Xinu-compatible actor HTTP gateway
(POST /api/json/call).  This is the same wire protocol a real Embedded-Xinu
board speaks, so the very same orchestrator drives soft nodes here or real
Pi boards later — only the host:port list changes.

Used as a library by evolve.py; also runnable standalone:

    python3 mesh.py start 4      # 4 nodes on 9101..9104, stays up (Ctrl-C)
"""
import os
import pathlib
import subprocess
import sys
import time

THIS = pathlib.Path(__file__).resolve().parent
PYAIPL = (THIS / "../../../src/python-aipl").resolve()
sys.path.insert(0, str(PYAIPL))
from aipl_remote import remote_call_sync  # noqa: E402

BASE_PORT = 9101
TMPL = (THIS / "nq_worker.tmpl.abcl").read_text()
RUNDIR = THIS / "_run"


def ports_for(m):
    return [BASE_PORT + i for i in range(m)]


def start_mesh(m, quiet=True):
    """Spawn m worker nodes; return (procs, ports) once all answer."""
    RUNDIR.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["ABCL_AI_PROVIDER"] = "mock"  # no AI used; keeps any key out of the loop
    procs, ports = [], ports_for(m)
    for p in ports:
        src = RUNDIR / f"nq_worker_{p}.abcl"
        src.write_text(TMPL.replace("__PORT__", str(p)))
        log = open(RUNDIR / f"node_{p}.log", "w")
        procs.append(subprocess.Popen(
            [sys.executable, "aipl_main.py", str(src)],
            cwd=str(PYAIPL), env=env, stdout=log, stderr=subprocess.STDOUT))
    _await_ready(ports, quiet)
    return procs, ports


def _await_ready(ports, quiet, timeout=20.0):
    deadline = time.time() + timeout
    pending = set(ports)
    while pending and time.time() < deadline:
        for p in list(pending):
            try:
                # trivial real call: solve a 1-queens subtree (cheap, deterministic)
                remote_call_sync(f"localhost:{p}", "worker", "solve", [1, 0],
                                 from_name="mesh", timeout_s=2.0)
                pending.discard(p)
                if not quiet:
                    print(f"  node :{p} ready")
            except Exception:
                time.sleep(0.2)
    if pending:
        raise RuntimeError(f"nodes never came up: {sorted(pending)}")


def stop_mesh(procs):
    for p in procs:
        if p.poll() is None:
            p.terminate()
    for p in procs:
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()


if __name__ == "__main__":
    m = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    if sys.argv[1:2] == ["start"]:
        procs, ports = start_mesh(m, quiet=False)
        print(f"mesh up: {['localhost:%d' % p for p in ports]}  (Ctrl-C to stop)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_mesh(procs)
            print("mesh stopped")
