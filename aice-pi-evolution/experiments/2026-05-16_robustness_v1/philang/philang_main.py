"""PhiLang CLI entry point.

Usage:
    python3 philang_main.py <program.phi>
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

# Allow running from anywhere
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from philang_parser import parse_phi
from philang_interp import run


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: philang_main.py <program.phi>", file=sys.stderr)
        return 2
    src_path = Path(sys.argv[1]).resolve()
    src = src_path.read_text(encoding="utf-8")
    phase = parse_phi(src)
    # The program's relative paths are resolved against the .phi file's dir.
    return run(phase, work_dir=src_path.parent)


if __name__ == "__main__":
    sys.exit(main())
