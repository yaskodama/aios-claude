#!/bin/sh
# DisasterReturnGui.aipl をビルドして起動する。
set -e
cd "$(dirname "$0")"

dune build src/aipl2c.exe
./_build/default/src/aipl2c.exe abclc/DisasterReturnGui.aipl -o /tmp/dr.c --max-msgs 0
cc -O2 -Wall -pthread $(pkg-config --cflags sdl2) \
   -o /tmp/dr /tmp/dr.c src/abcl_gui_runtime.c \
   $(pkg-config --libs sdl2) -lm
exec /tmp/dr
