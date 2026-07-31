#!/bin/sh
# PingPong.aipl を Python アクターランタイムで動かす。
set -e
cd "$(dirname "$0")"

dune build src/aipl2c.exe
./_build/default/src/aipl2c.exe abclc/PingPong.aipl \
    --python --max-msgs 12 -o /tmp/pingpong.py

exec python3 /tmp/pingpong.py
