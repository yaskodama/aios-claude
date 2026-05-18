#!/usr/bin/env python3
# Minimal AIPL Self-Host bootstrap loader (Level Z).
# Reads a user .abcl, concats the AIPL-side lexer + parser + eval + driver,
# then hands the lot to the host AIPL runtime.  No analysis on the host side.
import os, pathlib, runpy, sys
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]                                  # repo root
LC   = ROOT / "aipl-self-host" / "level-c"
USER = pathlib.Path(sys.argv[1]).resolve()              # user .abcl
TMP  = pathlib.Path("/tmp/_aipl_level_z.abcl")
parts = [(LC / f).read_text() for f in ("lexer.abcl", "parser.abcl", "eval.abcl")]
parts.append((HERE / "driver_head.abcl").read_text())
parts.append(f'var __USER_SRC = read_file("{USER}");\nvar __B = new Bootstrap();\nsend __B.run(__USER_SRC);\n')
TMP.write_text("\n".join(parts))
sys.path.insert(0, str(ROOT / "src" / "python-aipl"))
sys.setrecursionlimit(20000)
sys.argv = ["aipl_main.py", str(TMP), "--timeout", str(int(os.environ.get("LEVELZ_TIMEOUT", 15)))]
runpy.run_path(str(ROOT / "src" / "python-aipl" / "aipl_main.py"), run_name="__main__")
