#!/usr/bin/env python3
"""gen_makina_match_glb.py — bake a .glb into a .avm actor that matches the
"GLB direct" render of the Blender display system as closely as op_tri allows.

Why the previous MakinaDisplayActor.avm differed from the GLB-direct view:
  * COLOUR:  it was baked WITHOUT the R/B pre-swap, so the display path's single
             HW R/B swap inverted it (blond->blue, red->purple, warm skin->blue).
  * FACE:    it used painter's order + a head-only z-buffer approximation with a
             different camera (760x620, S=260), so the closed eyes leaked open and
             the figure was scaled/placed differently than render_glb (620x520).

This generator removes both gaps:
  * Same camera as render_glb (W,H,S,CX,CY,yaw,pitch from avm_blender_gui).
  * A FULL per-pixel z-buffer over the whole mesh (identical to render_glb's
    visibility) selects exactly the triangles render_glb shows -> same silhouette,
    same CLOSED eyes, same framing.
  * Each visible triangle gets ONE flat colour = mean of its 3 vertices' shaded
    colours, R/B pre-swapped just like render_glb stores them, so after the
    display path's HW swap the avm colours equal the glb colours.
  * Coords are emitted in the 760x620 frame render_avm expects, pre-scaled so
    render_avm's /760 rescale lands them back on render_glb's exact pixels.

  python3 gen_makina_match_glb.py [in.glb] [out.avm]
"""
import sys, os, math, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import avm_blender_gui as g

GLB = sys.argv[1] if len(sys.argv) > 1 else "/Users/kodamay/projects/milky-character/makina_preview.glb"
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "MakinaDisplayActor.avm")

W, H = g.W, g.H                                  # 620 x 520 (render_glb space)
S, CX, CY = g.S, g.CX, g.CY
YAW, PITCH = 0.55, 0.16
Lx, Ly, Lz = g.Lx, g.Ly, g.Lz
# render_avm maps stored coords by W/760 (x) and H/620 (y); pre-scale so the
# final on-screen pixel equals render_glb's pixel exactly.
AX, AY = 760.0 / W, 620.0 / H

NCHUNK, B, WAITMS = 42, 480, 60
CAP = NCHUNK * B

cyaw, syaw = math.cos(YAW), math.sin(YAW); cp, sp = math.cos(PITCH), math.sin(PITCH)
def rot(v):
    x, y, z = v; x2 = x*cyaw+z*syaw; z2 = -x*syaw+z*cyaw
    return (x2, y*cp-z2*sp, y*sp+z2*cp)
def shade(n, col):                               # mirrors render_glb.shade (with SWAP_RB)
    rx = n[0]*cyaw+n[2]*syaw; rz2 = -n[0]*syaw+n[2]*cyaw
    ry = n[1]*cp-rz2*sp; rz = n[1]*sp+rz2*cp
    f = 0.45 + 0.55*max(0.0, rx*Lx+ry*Ly+rz*Lz)
    r = min(255.0, col[0]*f); gg = min(255.0, col[1]*f); bl = min(255.0, col[2]*f)
    if g.SWAP_RB: r, bl = bl, r                  # store pre-swapped, like render_glb
    return r, gg, bl

# render_glb welds verts + smooth normals + vcol; reuse it verbatim.
tris = g.load_glb(GLB)
sys.stderr.write("[match] glb tris=%d\n" % len(tris))

# ---- project every front-facing triangle (render_glb's transform) ----
proj = []          # (sx1,sy1,z1, sx2,sy2,z2, sx3,sy3,z3, col24, depth)
for (a, b, c, na, nb, ncv, ca, cb, cc) in tris:
    A, B3, Cc = rot(a), rot(b), rot(c)
    # back-face cull in screen space (CCW front), same effect as render_glb's z-buffer keep
    sx1, sy1 = CX+S*A[0], CY-S*A[1]
    sx2, sy2 = CX+S*B3[0], CY-S*B3[1]
    sx3, sy3 = CX+S*Cc[0], CY-S*Cc[1]
    area2 = (sx2-sx1)*(sy3-sy1) - (sx3-sx1)*(sy2-sy1)
    if area2 == 0: continue
    r0, g0, b0 = shade(na, ca); r1, g1, b1 = shade(nb, cb); r2, g2, b2 = shade(ncv, cc)
    r = (r0+r1+r2)/3.0; gg = (g0+g1+g2)/3.0; bl = (b0+b1+b2)/3.0
    col = 0x1000000 | (int(r) << 16) | (int(gg) << 8) | int(bl)
    depth = (A[2]+B3[2]+Cc[2])/3.0
    proj.append((sx1, sy1, A[2], sx2, sy2, B3[2], sx3, sy3, Cc[2], col, depth))
sys.stderr.write("[match] projected=%d\n" % len(proj))

# ---- FULL per-pixel z-buffer over the whole mesh -> visible triangle set ----
zbuf = [-1e30]*(W*H); win = [-1]*(W*H)
for i, (x1, y1, z1, x2, y2, z2, x3, y3, z3, col, depth) in enumerate(proj):
    V = sorted(((y1, x1, z1), (y2, x2, z2), (y3, x3, z3)))
    (ya, xa, za), (yb, xb, zb_), (yc, xc, zc) = V
    iya, iyc = int(round(ya)), int(round(yc))
    if iyc == iya: continue
    lo = max(0, iya); hi = min(H-1, iyc)
    dy = (yc - ya) or 1e-9
    for yy in range(lo, hi+1):
        ta = (yy - ya)/dy
        xL = xa+(xc-xa)*ta; zL = za+(zc-za)*ta
        if yy < yb and yb != ya:
            tb = (yy-ya)/(yb-ya); xR = xa+(xb-xa)*tb; zR = za+(zb_-za)*tb
        elif yc != yb:
            tb = (yy-yb)/(yc-yb); xR = xb+(xc-xb)*tb; zR = zb_+(zc-zb_)*tb
        else:
            xR = xb; zR = zb_
        if xL > xR: xL, xR = xR, xL; zL, zR = zR, zL
        ix0 = max(0, int(round(xL))); ix1 = min(W-1, int(round(xR))); base = yy*W
        span = (xR-xL) or 1e-9; inv = 1.0/span
        for xx in range(ix0, ix1+1):
            z = zL+(zR-zL)*(xx-xL)*inv
            k = base+xx
            if z > zbuf[k]:
                zbuf[k] = z; win[k] = i
vis_set = set(w for w in win if w >= 0)
sys.stderr.write("[match] visible tris=%d\n" % len(vis_set))

# ---- emit visible tris, far->near, in the 760x620 frame render_avm expects ----
keep = [proj[i] for i in vis_set]
keep.sort(key=lambda t: t[10])                       # far -> near (painter's)
vis = []
for (x1, y1, z1, x2, y2, z2, x3, y3, z3, col, depth) in keep:
    vis.append((round(x1*AX), round(y1*AY), round(x2*AX), round(y2*AY),
                round(x3*AX), round(y3*AY), col))
if len(vis) > CAP:
    vis = vis[len(vis)-CAP:]
sys.stderr.write("[match] streamed=%d (cap=%d)\n" % (len(vis), CAP))

# ================= AVM1 assembler (same topology as gen_makina_actor_from_glb) =================
strs = []
def sid(s):
    if s not in strs: strs.append(s)
    return strs.index(s)
OP = dict(PUSHI=0x01, LDF=0x02, STF=0x03, LDA=0x04, SELF=0x05, WAIT=0x07,
          SEND=0x40, SPAWN=0x41, RET=0x43, TRI=0x47, CLS=0x46)
def asm(prog):
    b = bytearray()
    for ins in prog:
        o = ins[0]
        if o == 'label': continue
        b.append(OP[o])
        if o == 'PUSHI': b += struct.pack('<i', ins[1])
        elif o in ('LDF', 'STF', 'LDA'): b.append(ins[1] & 0xff)
        elif o == 'SPAWN': b += struct.pack('<H', ins[1])
        elif o == 'SEND': b += struct.pack('<H', sid(ins[1])); b.append(ins[2] & 0xff)
    return bytes(b)

DISPLAY_CI, MAKINA_CI = 1, 2
main_tick = asm([('SPAWN', DISPLAY_CI), ('STF', 0), ('SPAWN', MAKINA_CI), ('STF', 1),
                 ('LDF', 1), ('LDF', 0), ('SEND', 'run', 1), ('RET',)])
disp_clear = asm([('CLS',), ('RET',)])
disp_tri = asm([('LDA', 0), ('LDA', 1), ('LDA', 2), ('LDA', 3), ('LDA', 4), ('LDA', 5), ('LDA', 6),
                ('TRI',), ('RET',)])
mak_run = asm([('LDA', 0), ('STF', 0), ('LDF', 0), ('SEND', 'clear', 0),
               ('SELF',), ('SEND', 'c0', 0), ('RET',)])
chunks = [vis[k*B:(k+1)*B] for k in range(NCHUNK)]
mak_c = []
for k, ch in enumerate(chunks):
    prog = []
    for (x1, y1, x2, y2, x3, y3, col) in ch:
        prog += [('LDF', 0), ('PUSHI', x1), ('PUSHI', y1), ('PUSHI', x2), ('PUSHI', y2),
                 ('PUSHI', x3), ('PUSHI', y3), ('PUSHI', col), ('SEND', 'tri', 7)]
    if k < NCHUNK-1 and (k+1) < len(chunks) and chunks[k+1]:
        prog += [('PUSHI', WAITMS), ('WAIT',), ('SELF',), ('SEND', 'c%d' % (k+1), 0)]
    elif ch:
        prog += [('PUSHI', WAITMS), ('WAIT',)]
    prog += [('RET',)]
    mak_c.append(asm(prog))

def u16(v): return struct.pack('<H', v)
def method(name, npar, code): return u16(sid(name)) + bytes([npar]) + u16(len(code)) + code
cls_main = u16(sid('Main')) + u16(2) + u16(1) + method('tick', 0, main_tick)
disp_m = method('clear', 0, disp_clear) + method('tri', 7, disp_tri)
cls_disp = u16(sid('Display')) + u16(0) + u16(2) + disp_m
mak_m = method('run', 1, mak_run)
for k in range(NCHUNK): mak_m += method('c%d' % k, 0, mak_c[k])
cls_mak = u16(sid('Makina')) + u16(1) + u16(1+NCHUNK) + mak_m

mod = bytearray(b'AVM1'); mod += u16(len(strs))
for s in strs: sb = s.encode(); mod += u16(len(sb)) + sb
mod += u16(3) + cls_main + cls_disp + cls_mak
assert 1+NCHUNK <= 320 and len(strs) <= 64
open(OUT, 'wb').write(mod)

# ---- .abcl source ----
abcl = ["// MakinaDisplayActor.abcl - baked from %s to MATCH the GLB-direct render." % os.path.basename(GLB),
        "// Same camera + full z-buffer visibility + R/B pre-swapped colour as render_glb.",
        "// col = 0x1000000 | 0xRRGGBB (B/R pre-swapped for the HW framebuffer).", "",
        "class Main {", "  var d = 0; var m = 0;",
        "  method tick() { d = new Display(); m = new Makina(); send m.run(d); }", "}", "",
        "class Display {", "  method clear() { cls(); }",
        "  method tri(a,b,c,d,e,f,g) { tri(a,b,c,d,e,f,g); }", "}", "",
        "class Makina {", "  var d = 0;",
        "  method run(disp) { d = disp; send d.clear(); send self.c0(); }"]
for k, ch in enumerate(chunks):
    abcl.append("  method c%d() {" % k)
    for (x1, y1, x2, y2, x3, y3, col) in ch:
        abcl.append("    send d.tri(%d,%d,%d,%d,%d,%d,%d);" % (x1, y1, x2, y2, x3, y3, col))
    if k < NCHUNK-1 and (k+1) < len(chunks) and chunks[k+1]:
        abcl.append("    wait(%d); send self.c%d();" % (WAITMS, k+1))
    elif ch:
        abcl.append("    wait(%d);   // final render" % WAITMS)
    abcl.append("  }")
abcl += ["}", "", "var boot = new Main(); send boot.tick();"]
stem = OUT[:-4] if OUT.endswith(".avm") else OUT
SRC = stem + ".abcl"
open(SRC, "w").write("\n".join(abcl) + "\n")
# sidecar so the Blender display GUI can re-load the 3-D mesh for SPIN/WALK/Smooth.
open(stem + ".glbsrc", "w").write(os.path.abspath(GLB) + "\n")
print("wrote %s (%d bytes) + %s + %s.glbsrc, streamed %d tris" % (OUT, len(mod), SRC, stem, len(vis)))
