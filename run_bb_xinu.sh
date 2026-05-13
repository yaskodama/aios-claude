#!/bin/sh
# BoundedBufferXinu.abcl を Xinu (arm-qemu) 上で動かす。
set -e
cd "$(dirname "$0")"

XINU=/Users/kodamay/projects/xinu-raz/xinu
COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi-

dune build src/aipl2c.exe
./_build/default/src/aipl2c.exe abclc/BoundedBufferXinu.abcl \
    -o /tmp/bb_xinu.c --xinu --max-msgs 0
cp /tmp/bb_xinu.c "$XINU/apps/abcl_program.c"

( cd "$XINU/compile" && \
  make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT >/tmp/xinu_build.log 2>&1 )

exec qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
    -kernel "$XINU/compile/xinu.elf" -no-reboot
