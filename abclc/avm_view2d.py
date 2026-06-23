#!/usr/bin/env python3
"""avm_view2d.py — run a 2-D AVM1 actor module on the Mac, EXACTLY as the Xinu
kernel VM (apps/abcl_program.c + apps/gwm.c) would, and animate it in a Tkinter
window.  This loads the SAME .avm bytes that get POSTed to Xinu, so the Mac
preview == what the board shows.

Faithful to the kernel:
  * full opcode set (PUSHI/LDF/STF/LDA/SELF/SENDER/WAIT/DUP/arith/cmp/JMP/JZ/
    SEND/SPAWN/PRINT/PRINTF/RET/LINE/CLS/TRI)
  * message-queue actor scheduler; send self.frame() loops, wait(ms) paces it
  * line() colour = palette index (bas_palette, 16 entries)
  * cls() clears the frame's line/tri set; each frame() rebuilds + we redraw
Usage:  python3 avm_view2d.py [module.avm]
"""
import sys, os, struct
from collections import deque

PAL = [  # apps/gwm.c bas_palette (ARGB -> #rrggbb)
    "#000000", "#3060ff", "#30d040", "#30d0d0",
    "#e03030", "#e040e0", "#e0e040", "#f0f0f0",
    "#808080", "#80a0ff", "#80ff80", "#80ffff",
    "#ff8080", "#ff80ff", "#ffff80", "#ffffff"]
CONTENT_BG = "#06100a"

# ---------------- AVM1 loader ----------------
class Method:
    __slots__ = ("name", "nparams", "code")
class Klass:
    __slots__ = ("name", "nfields", "methods")

def load_avm(path):
    d = open(path, "rb").read()
    assert d[:4] == b"AVM1", "not an AVM1 module"
    o = 4
    def u16():
        nonlocal o; v = d[o] | (d[o+1] << 8); o += 2; return v
    nstr = u16()
    strings = []
    for _ in range(nstr):
        ln = u16(); strings.append(d[o:o+ln].decode("utf-8", "replace")); o += ln
    nclass = u16()
    classes = []
    for _ in range(nclass):
        k = Klass(); k.name = strings[u16()]; k.nfields = u16()
        nm = u16(); k.methods = []
        for _ in range(nm):
            m = Method(); m.name = strings[u16()]; m.nparams = d[o]; o += 1
            clen = u16(); m.code = d[o:o+clen]; o += clen
            k.methods.append(m)
        classes.append(k)
    return strings, classes

# ---------------- VM ----------------
class Obj:
    __slots__ = ("cls", "fields")
    def __init__(self, cls, nf):
        self.cls = cls; self.fields = [0] * nf   # kernel zero-inits fields

class VM:
    def __init__(self, strings, classes):
        self.strings = strings; self.classes = classes
        self.objs = []
        self.lines = []   # (x1,y1,x2,y2,colidx)
        self.tris = []    # (x1,y1,x2,y2,x3,y3,colidx)
        self.queue = deque()
        self.wait_ms = 0
        self.prints = []

    def spawn(self, ci):
        k = self.classes[ci]
        self.objs.append(Obj(ci, k.nfields))
        return len(self.objs) - 1

    def find_method(self, ci, name):
        for m in self.classes[ci].methods:
            if m.name == name:
                return m
        return None

    def run_method(self, oid, mname, args):
        obj = self.objs[oid]
        m = self.find_method(obj.cls, mname)
        if m is None:
            return
        code = m.code; st = []; pc = 0; n = len(code)
        rd_i32 = lambda p: struct.unpack_from("<i", code, p)[0]
        rd_u16 = lambda p: code[p] | (code[p+1] << 8)
        while pc < n:
            op = code[pc]; pc += 1
            if op == 0x01:    st.append(rd_i32(pc)); pc += 4
            elif op == 0x02:  st.append(obj.fields[code[pc]]); pc += 1
            elif op == 0x03:  obj.fields[code[pc]] = st.pop(); pc += 1
            elif op == 0x04:  st.append(args[code[pc]]); pc += 1
            elif op == 0x05:  st.append(oid)
            elif op == 0x06:  st.append(-1)                       # sender (unused here)
            elif op == 0x07:  self.wait_ms = st.pop()             # WAIT
            elif op == 0x08:  st.append(st[-1])                   # DUP
            elif op == 0x10:  b = st.pop(); a = st.pop(); st.append(a + b)
            elif op == 0x11:  b = st.pop(); a = st.pop(); st.append(a - b)
            elif op == 0x12:  b = st.pop(); a = st.pop(); st.append(a * b)
            elif op == 0x13:  b = st.pop(); a = st.pop(); st.append(0 if b == 0 else int(a / b))
            elif op == 0x14:  b = st.pop(); a = st.pop(); st.append(0 if b == 0 else a - int(a / b) * b)
            elif op == 0x20:  b = st.pop(); a = st.pop(); st.append(1 if a < b else 0)
            elif op == 0x21:  b = st.pop(); a = st.pop(); st.append(1 if a <= b else 0)
            elif op == 0x22:  b = st.pop(); a = st.pop(); st.append(1 if a > b else 0)
            elif op == 0x23:  b = st.pop(); a = st.pop(); st.append(1 if a >= b else 0)
            elif op == 0x24:  b = st.pop(); a = st.pop(); st.append(1 if a == b else 0)
            elif op == 0x25:  b = st.pop(); a = st.pop(); st.append(1 if a != b else 0)
            elif op == 0x30:  pc = rd_u16(pc)                     # JMP
            elif op == 0x31:                                      # JZ
                tgt = rd_u16(pc); pc += 2
                if st.pop() == 0: pc = tgt
            elif op == 0x40:                                      # SEND mIdx, nargs
                mi = rd_u16(pc); pc += 2; na = code[pc]; pc += 1
                cargs = [st.pop() for _ in range(na)][::-1]
                tgt = st.pop()
                self.queue.append((tgt, self.strings[mi], cargs))
            elif op == 0x41:  ci = rd_u16(pc); pc += 2; st.append(self.spawn(ci))   # SPAWN
            elif op == 0x42:  self.prints.append(str(st.pop()))   # PRINT
            elif op == 0x43:  return                              # RET
            elif op == 0x44:                                      # PRINTF fmtIdx, nargs
                fi = rd_u16(pc); pc += 2; na = code[pc]; pc += 1
                vals = [st.pop() for _ in range(na)][::-1]
                fmt = self.strings[fi]
                try: self.prints.append(fmt % tuple(vals))
                except Exception: self.prints.append(fmt)
            elif op == 0x45:                                      # LINE
                col = st.pop(); y2 = st.pop(); x2 = st.pop(); y1 = st.pop(); x1 = st.pop()
                self.lines.append((x1, y1, x2, y2, col))
            elif op == 0x46:  self.lines = []; self.tris = []     # CLS
            elif op == 0x47:                                      # TRI
                col = st.pop(); y3 = st.pop(); x3 = st.pop()
                y2 = st.pop(); x2 = st.pop(); y1 = st.pop(); x1 = st.pop()
                self.tris.append((x1, y1, x2, y2, x3, y3, col))
            else:
                raise RuntimeError("unknown opcode 0x%02x at pc=%d" % (op, pc-1))

# ---------------- Tkinter front-end ----------------
def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "DiningPhilosophers_lines.avm")
    strings, classes = load_avm(path)
    vm = VM(strings, classes)
    # loadvm spawns class 0 (the synthetic __boot if globals exist) and kicks tick();
    # if there is no __boot, spawn the first class and call run()/tick().
    boot_ci = 0
    boot = vm.spawn(boot_ci)
    start = "tick" if vm.find_method(boot_ci, "tick") else ("run" if vm.find_method(boot_ci, "run") else None)
    vm.queue.append((boot, start, []))

    import tkinter as tk
    W, H = 820, 614
    root = tk.Tk()
    root.title("Xinu VM graphics — Dining Philosophers (.avm preview)")
    cv = tk.Canvas(root, width=W, height=H, bg=CONTENT_BG, highlightthickness=0)
    cv.pack()
    status = tk.Label(root, text="", anchor="w", font=("Menlo", 12), bg="#11161c", fg="#cfe")
    status.config(width=120); status.pack(fill="x")

    state_label = {0: "THINK", 1: "HUNGRY", 2: "EAT"}
    frame_no = [0]

    def render():
        cv.delete("all")
        for (x1, y1, x2, y2, x3, y3, c) in vm.tris:
            cv.create_polygon(x1, y1, x2, y2, x3, y3, fill=PAL[c & 15], outline="")
        for (x1, y1, x2, y2, c) in vm.lines:
            cv.create_line(x1, y1, x2, y2, fill=PAL[c & 15], width=2)

    def find_diners():
        for i, o in enumerate(vm.objs):
            if classes[o.cls].name == "Diners":
                return o
        return None

    def step():
        if not vm.queue:
            return
        vm.wait_ms = 0
        tgt, mname, cargs = vm.queue.popleft()
        vm.run_method(tgt, mname, cargs)
        render()
        if mname == "frame":
            frame_no[0] += 1
        d = find_diners()
        if d:
            # field layout (16): s0..s4, t0..t4, h0..h4, ok
            s = d.fields[0:5]
            txt = "frame %4d   " % frame_no[0] + "   ".join(
                "P%d:%s" % (i, state_label.get(s[i], "?")) for i in range(5))
            eating = sum(1 for v in s if v == 2)
            txt += "    (eating: %d)" % eating
            status.config(text=txt)
        delay = vm.wait_ms if vm.wait_ms > 0 else 16
        root.after(delay, step)

    root.after(50, step)
    root.mainloop()

if __name__ == "__main__":
    main()
