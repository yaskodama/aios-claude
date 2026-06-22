#!/usr/bin/env python3
"""avm_blender_view.py — a host-side (Mac) reimplementation of Xinu's in-kernel
"Blender display system" (device/video/avm.c).  It loads a .avm actor module,
runs the same AVM bytecode VM (Main spawns Display + Makina; Makina streams
`tri` messages to Display; Display calls cls()/tri()), rasterises the triangles
with the SAME painter's algorithm + avm_color() the kernel uses, and writes a
PNG (then opens it).  No external deps — PNG via zlib.

It also replicates this Pi4's framebuffer R/B swap so the colours match what the
HDMI screen shows.

  python3 avm_blender_view.py [file.avm] [out.png]
"""
import sys, struct, zlib, os, subprocess

AVM = sys.argv[1] if len(sys.argv) > 1 else "/tmp/MakinaGlbActor.avm"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/MakinaGlbActor.png"
BW, BH = 760, 620
G_BG = 0xFF06100A            # content background (matches the kernel)
HW_SWAP_RB = True            # this Pi4 framebuffer swaps R/B on scanout

# ---------------- palette + colour (mirrors avm.c) ----------------
PAL = [0xFF000000, 0xFF3060FF, 0xFF30D040, 0xFF30D0D0,
       0xFFE03030, 0xFFE040E0, 0xFFE0E040, 0xFFF0F0F0,
       0xFF808080, 0xFF80A0FF, 0xFF80FF80, 0xFF80FFFF,
       0xFFFF8080, 0xFFFF80FF, 0xFFFFFF80, 0xFFFFFFFF]
def avm_color(c):
    return (0xFF000000 | (c & 0xFFFFFF)) if (c & 0x1000000) else PAL[c & 15]

# ---------------- AVM1 module loader ----------------
class Method:  __slots__ = ("name", "nparams", "code")
class Klass:   __slots__ = ("name", "nfields", "methods")

def load_module(data):
    assert data[:4] == b'AVM1', "not an AVM1 module"
    p = 4
    n_str = struct.unpack_from("<H", data, p)[0]; p += 2
    strs = []
    for _ in range(n_str):
        ln = struct.unpack_from("<H", data, p)[0]; p += 2
        strs.append(data[p:p+ln].decode("ascii", "replace")); p += ln
    nc = struct.unpack_from("<H", data, p)[0]; p += 2
    classes = []
    for _ in range(nc):
        k = Klass()
        k.name = struct.unpack_from("<H", data, p)[0]; p += 2
        k.nfields = struct.unpack_from("<H", data, p)[0]; p += 2
        nm = struct.unpack_from("<H", data, p)[0]; p += 2
        k.methods = []
        for _ in range(nm):
            m = Method()
            m.name = struct.unpack_from("<H", data, p)[0]; p += 2
            m.nparams = data[p]; p += 1
            clen = struct.unpack_from("<H", data, p)[0]; p += 2
            m.code = data[p:p+clen]; p += clen
            k.methods.append(m)
        classes.append(k)
    return strs, classes

# ---------------- VM ----------------
class VM:
    def __init__(self, strs, classes):
        self.strs = strs; self.classes = classes
        self.objs = []                       # (cls_idx, fields[24])
        self.q = []                          # (recv, sender, method_name, args[])
        self.tris = []                       # accumulated (x1,y1,x2,y2,x3,y3,col)
        self.lines = []

    def spawn(self, ci):
        self.objs.append([ci, [0]*24]); return len(self.objs)-1

    def enqueue(self, recv, sender, mname, args):
        self.q.append((recv, sender, mname, list(args)))

    def find_method(self, ci, mname):
        for m in self.classes[ci].methods:
            if self.strs[m.name] == mname: return m
        return None

    def dispatch(self, recv, sender, mname, args):
        if recv < 0 or recv >= len(self.objs): return
        ci, fields = self.objs[recv]
        m = self.find_method(ci, mname)
        if m is None: return
        code = m.code; clen = len(code); pc = 0; stk = []
        def i32(o): return struct.unpack_from("<i", code, o)[0]
        def u16(o): return struct.unpack_from("<H", code, o)[0]
        guard = 0
        while pc < clen:
            guard += 1
            if guard > 5_000_000: break
            op = code[pc]; pc += 1
            if op == 0x01: stk.append(i32(pc)); pc += 4
            elif op == 0x02: f = code[pc]; pc += 1; stk.append(fields[f] if f < 24 else 0)
            elif op == 0x03: f = code[pc]; pc += 1; v = stk.pop() if stk else 0; (fields.__setitem__(f, v) if f < 24 else None)
            elif op == 0x04: a = code[pc]; pc += 1; stk.append(args[a] if a < len(args) else 0)
            elif op == 0x05: stk.append(recv)
            elif op == 0x06: stk.append(sender)
            elif op == 0x07:  # WAIT (frame boundary) — host renders the final frame, so just pop
                (stk.pop() if stk else 0)
            elif op == 0x08: stk.append(stk[-1] if stk else 0)
            elif op == 0x10: b = stk.pop(); a = stk.pop(); stk.append(a+b)
            elif op == 0x11: b = stk.pop(); a = stk.pop(); stk.append(a-b)
            elif op == 0x12: b = stk.pop(); a = stk.pop(); stk.append(a*b)
            elif op == 0x13: b = stk.pop(); a = stk.pop(); stk.append(a//b if b else 0)
            elif op == 0x14: b = stk.pop(); a = stk.pop(); stk.append(a % b if b else 0)
            elif op == 0x20: b = stk.pop(); a = stk.pop(); stk.append(1 if a < b else 0)
            elif op == 0x21: b = stk.pop(); a = stk.pop(); stk.append(1 if a <= b else 0)
            elif op == 0x22: b = stk.pop(); a = stk.pop(); stk.append(1 if a > b else 0)
            elif op == 0x23: b = stk.pop(); a = stk.pop(); stk.append(1 if a >= b else 0)
            elif op == 0x24: b = stk.pop(); a = stk.pop(); stk.append(1 if a == b else 0)
            elif op == 0x25: b = stk.pop(); a = stk.pop(); stk.append(1 if a != b else 0)
            elif op == 0x30: pc = u16(pc)
            elif op == 0x31: t = u16(pc); pc += 2; v = (stk.pop() if stk else 0); pc = t if v == 0 else pc
            elif op == 0x40:  # SEND
                mn = u16(pc); pc += 2; na = code[pc]; pc += 1
                va = [stk.pop() for _ in range(na)][::-1]
                rc = stk.pop() if stk else 0
                if 0 <= mn < len(self.strs): self.enqueue(rc, recv, self.strs[mn], va)
            elif op == 0x41: ci2 = u16(pc); pc += 2; stk.append(self.spawn(ci2))
            elif op == 0x42: (stk.pop() if stk else 0)
            elif op == 0x43: pc = clen
            elif op == 0x44: u16(pc); na = code[pc+2]; pc += 3; [stk.pop() for _ in range(na) if stk]
            elif op == 0x45:  # LINE
                col = stk.pop(); y2 = stk.pop(); x2 = stk.pop(); y1 = stk.pop(); x1 = stk.pop()
                self.lines.append((x1, y1, x2, y2, col))
            elif op == 0x46: self.tris.clear(); self.lines.clear()   # CLS
            elif op == 0x47:  # TRI
                col = stk.pop(); y3 = stk.pop(); x3 = stk.pop(); y2 = stk.pop(); x2 = stk.pop(); y1 = stk.pop(); x1 = stk.pop()
                self.tris.append((x1, y1, x2, y2, x3, y3, col))
            else: pc = clen
        # JMPZ proper handling (re-do 0x31 cleanly via a second interpreter path not needed here)

    def run(self):
        boot = self.spawn(0)
        self.enqueue(boot, -1, "tick", [])
        steps = 0
        while self.q:
            steps += 1
            if steps > 2_000_000: break
            recv, sender, mname, args = self.q.pop(0)
            self.dispatch(recv, sender, mname, args)

# ---------------- rasteriser (mirrors buf_tri_band, full triangle) ----------------
def raster(vm):
    fb = [G_BG] * (BW * BH)
    def tri(x0, y0, x1, y1, x2, y2, col):
        if y1 < y0: x0, x1, y0, y1 = x1, x0, y1, y0
        if y2 < y0: x0, x2, y0, y2 = x2, x0, y2, y0
        if y2 < y1: x1, x2, y1, y2 = x2, x1, y2, y1
        if y2 == y0: return
        ya = max(0, y0); yb = min(BH-1, y2)
        for yy in range(ya, yb+1):
            xa = x0 + (x2-x0)*(yy-y0)//(y2-y0)
            if yy < y1 and y1 != y0:  xb = x0 + (x1-x0)*(yy-y0)//(y1-y0)
            elif y2 != y1:            xb = x1 + (x2-x1)*(yy-y1)//(y2-y1)
            else:                     xb = x1
            if xa > xb: xa, xb = xb, xa
            if xa < 0: xa = 0
            if xb >= BW: xb = BW-1
            base = yy*BW
            for xx in range(xa, xb+1):
                fb[base+xx] = col
    for (x1, y1, x2, y2, x3, y3, c) in vm.tris:
        tri(x1, y1, x2, y2, x3, y3, avm_color(c))
    def line(x0, y0, x1, y1, col):
        dx = abs(x1-x0); sx = 1 if x0 < x1 else -1
        dy = -abs(y1-y0); sy = 1 if y0 < y1 else -1
        err = dx+dy
        while True:
            if 0 <= x0 < BW and 0 <= y0 < BH: fb[y0*BW+x0] = col
            if x0 == x1 and y0 == y1: break
            e2 = 2*err
            if e2 >= dy: err += dy; x0 += sx
            if e2 <= dx: err += dx; y0 += sy
    for (x1, y1, x2, y2, c) in vm.lines:
        line(x1, y1, x2, y2, avm_color(c))
    return fb

# ---------------- PNG out ----------------
def write_png(path, fb):
    raw = bytearray()
    for y in range(BH):
        raw.append(0)
        row = fb[y*BW:(y+1)*BW]
        for u in row:
            if HW_SWAP_RB:                       # framebuffer R/B swap -> correct colour
                raw += bytes((u & 0xFF, (u >> 8) & 0xFF, (u >> 16) & 0xFF))
            else:
                raw += bytes(((u >> 16) & 0xFF, (u >> 8) & 0xFF, u & 0xFF))
    def chunk(typ, d):
        return struct.pack(">I", len(d)) + typ + d + struct.pack(">I", zlib.crc32(typ+d) & 0xffffffff)
    ihdr = struct.pack(">IIBBBBB", BW, BH, 8, 2, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        f.write(chunk(b'IHDR', ihdr))
        f.write(chunk(b'IDAT', zlib.compress(bytes(raw), 6)))
        f.write(chunk(b'IEND', b''))

def main():
    data = open(AVM, "rb").read()
    strs, classes = load_module(data)
    print("[avm] strings=%d classes=%d" % (len(strs), len(classes)))
    vm = VM(strs, classes)
    vm.run()
    print("[avm] triangles=%d lines=%d" % (len(vm.tris), len(vm.lines)))
    fb = raster(vm)
    write_png(OUT, fb)
    print("[avm] wrote %s (%d x %d)" % (OUT, BW, BH))
    try: subprocess.run(["open", OUT], check=False)
    except Exception: pass

if __name__ == "__main__":
    main()
