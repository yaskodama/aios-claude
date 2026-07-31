#!/bin/sh
# Philosophers5Py.aipl を Python (tkinter) 上で動かす。
set -e
cd "$(dirname "$0")"

dune build src/aipl2c.exe
./_build/default/src/aipl2c.exe abclc/Philosophers5Py.aipl \
    --python --max-msgs 0 -o /tmp/p5_py.py

exec python3 /tmp/p5_py.py
