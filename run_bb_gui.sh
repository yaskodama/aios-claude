#!/bin/sh
# BoundedBufferGui.aipl をビルドして起動する。
set -e
cd "$(dirname "$0")"

dune build src/aipl2c.exe
./_build/default/src/aipl2c.exe abclc/BoundedBufferGui.aipl -o /tmp/bb.c --max-msgs 0
cc -O2 -Wall -pthread $(pkg-config --cflags sdl2) \
   -o /tmp/bb /tmp/bb.c src/abcl_gui_runtime.c \
   $(pkg-config --libs sdl2) -lm
exec /tmp/bb
