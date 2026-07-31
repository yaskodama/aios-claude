#!/bin/sh
# Rotate4LinesXinu.aipl を Xinu (arm-qemu, PL110 LCD + PL050 mouse) 上で動かす。
#  1. aipl2c --xinu で Xinu 用 C を生成
#  2. apps/abcl_program.c に配置
#  3. Xinu kernel をビルド
#  4. QEMU でグラフィカル起動 (Cocoa ウィンドウが開く)
set -e
cd "$(dirname "$0")"

XINU=/Users/kodamay/projects/xinu-raz/xinu
COMPILER_ROOT=/opt/homebrew/bin/arm-none-eabi-

dune build src/aipl2c.exe
./_build/default/src/aipl2c.exe abclc/Rotate4LinesXinu.aipl \
    -o /tmp/r4l_xinu.c --xinu --max-msgs 0
cp /tmp/r4l_xinu.c "$XINU/apps/abcl_program.c"

( cd "$XINU/compile" && \
  make PLATFORM=arm-qemu COMPILER_ROOT=$COMPILER_ROOT >/tmp/xinu_build.log 2>&1 )

# QEMU を実機相当 GUI モードで起動 (Cocoa ウィンドウに 640x480 LCD 出力)
exec qemu-system-arm -M versatilepb -cpu arm1176 -m 256M \
    -kernel "$XINU/compile/xinu.elf" \
    -no-reboot
