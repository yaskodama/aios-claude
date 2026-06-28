#!/usr/bin/env python3
"""gen_makina_turntable.py — SOLID MAKINA-7 turntable (flip-book) for aice-avm.

The host VM has no arrays, so we can't rotate a mesh at runtime; instead we bake
N yaw frames, each a set of painter-sorted flat-shaded tri() calls, and an Ed
actor cycles through them (cls -> draw frame k -> wait -> k++ -> loop), giving a
Blender-style turntable inside the single VM Graphics window.

  python3 gen_makina_turntable.py [frames] [cap] [pitch] [ms] [out.abcl]
    frames : yaw steps over 360 deg          (default 24)
    cap    : max tris/frame (largest-area kept; 0 = all front tris)  (default 9000)
    ms     : wait() between frames           (default 70)
"""
import sys, os, struct, json, math

# Pi4/Pi5 HDMI output is R/B-swapped vs the ARGB framebuffer (the kernel mesh3d
# renderer pre-swaps R/B to match it).  Our tri() colours must be pre-swapped
# too for correct colours on the board's screen.  SWAPRB=1 -> emit B,G,R.
# Leave unset (=RGB) for the aice-avm host VM, whose canvas is straight RGB.
SWAPRB = os.environ.get("SWAPRB", "0") == "1"

GLB = "/Users/kodamay/projects/milky-character/makina_preview.glb"
GW, GH = 820, 640
FRAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 24
CAP    = int(sys.argv[2]) if len(sys.argv) > 2 else 9000
pitch  = float(sys.argv[3]) if len(sys.argv) > 3 else 0.12
MS     = int(sys.argv[4]) if len(sys.argv) > 4 else 70
OUT    = sys.argv[5] if len(sys.argv) > 5 else "MakinaTurntable.abcl"
CHUNK  = 1500

Lx, Ly, Lz = 0.40, 0.60, 0.70
_l = math.sqrt(Lx*Lx+Ly*Ly+Lz*Lz); Lx, Ly, Lz = Lx/_l, Ly/_l, Lz/_l


def load_glb(path):
    data = open(path, "rb").read()
    _, _, total = struct.unpack_from("<III", data, 0); off = 12; jb = bb = None
    while off < total:
        clen, ctype = struct.unpack_from("<II", data, off); off += 8
        ch = data[off:off+clen]; off += clen
        if ctype == 0x4E4F534A: jb = json.loads(ch)
        elif ctype == 0x004E4942: bb = ch
    prim = jb["meshes"][0]["primitives"][0]

    def acc(idx):
        a = jb["accessors"][idx]; bv = jb["bufferViews"][a["bufferView"]]
        base = bv.get("byteOffset", 0) + a.get("byteOffset", 0); cnt = a["count"]
        ct = a["componentType"]; nc = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
        fmt = {5126: "f", 5121: "B", 5123: "H"}[ct]
        v = struct.unpack_from("<%d%s" % (cnt*nc, fmt), bb, base)
        return [v[i*nc:(i+1)*nc] for i in range(cnt)]

    P = acc(prim["attributes"]["POSITION"])
    C = acc(prim["attributes"]["COLOR_0"]) if "COLOR_0" in prim["attributes"] else None

    def vcol(i):
        if not C: return (190, 190, 200)
        c = C[i]
        if max(c[:3]) <= 1.0001: return tuple(min(255, int(round(c[k]*255))) for k in range(3))
        return tuple(min(255, int(c[k])) for k in range(3))

    return [(P[i], P[i+1], P[i+2], vcol(i), vcol(i+1), vcol(i+2)) for i in range(0, len(P)-2, 3)]


def bake_frame(tris, yaw, pitch, cx3, cy3, cz3, s, CX, CY):
    cyaw, syaw = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)

    def rot(p):
        x, y, z = p[0]-cx3, p[1]-cy3, p[2]-cz3
        x2 = x*cyaw + z*syaw; z2 = -x*syaw + z*cyaw
        return x2, y*cp - z2*sp, y*sp + z2*cp

    out = []
    for (a, b, c, ca, cb, cc) in tris:
        A, B, C = rot(a), rot(b), rot(c)
        ux, uy, uz = B[0]-A[0], B[1]-A[1], B[2]-A[2]
        vx, vy, vz = C[0]-A[0], C[1]-A[1], C[2]-A[2]
        nx, ny, nz = uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
        nl = math.sqrt(nx*nx+ny*ny+nz*nz) or 1.0
        nx, ny, nz = nx/nl, ny/nl, nz/nl
        # DOUBLE-SIDED: don't cull (thin skirt/cape would show see-through gaps).
        # Light whichever side faces the camera; the area cap keeps the big skirt
        # panels and the painter's depth sort orders them.
        if nz < 0.0:
            nx, ny, nz = -nx, -ny, -nz
        f = 0.42 + 0.58*max(0.0, nx*Lx+ny*Ly+nz*Lz)
        r = min(255, int((ca[0]+cb[0]+cc[0])/3*f)); g = min(255, int((ca[1]+cb[1]+cc[1])/3*f))
        bl = min(255, int((ca[2]+cb[2]+cc[2])/3*f))
        if SWAPRB:
            r, bl = bl, r
        col = 0x1000000 | (r << 16) | (g << 8) | bl
        x1 = int(round(CX+s*A[0])); y1 = int(round(CY-s*A[1]))
        x2 = int(round(CX+s*B[0])); y2 = int(round(CY-s*B[1]))
        x3 = int(round(CX+s*C[0])); y3 = int(round(CY-s*C[1]))
        area = abs((x2-x1)*(y3-y1) - (x3-x1)*(y2-y1))
        out.append(((A[2]+B[2]+C[2])/3.0, area, x1, y1, x2, y2, x3, y3, col))
    if CAP and len(out) > CAP:                       # keep largest-area -> stays solid
        out.sort(key=lambda t: t[1], reverse=True); out = out[:CAP]
    out.sort(key=lambda t: t[0])                      # back -> front (painter's)
    return out


def main():
    tris = load_glb(GLB)
    xs = [p[0] for t in tris for p in t[:3]]; ys = [p[1] for t in tris for p in t[:3]]
    zs = [p[2] for t in tris for p in t[:3]]
    cx3, cy3, cz3 = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2, (min(zs)+max(zs))/2
    half = max(max(ys)-min(ys), max(xs)-min(xs)) / 2 or 1.0
    s = 0.44*GH/half; CX, CY = GW/2, GH*0.46

    L = []
    L.append("// MakinaTurntable.abcl - SOLID MAKINA-7 turntable for aice-avm (tri()).")
    L.append("// %d frames, cap=%d tris, pitch=%.3f, %dms/frame. VM auto-starts class0." % (FRAMES, CAP, pitch, MS))
    L.append("")
    L.append("class Main { var e = 0; method tick() { e = new Ed(); send e.frame(); } }")
    L.append("")
    L.append("class Ed {")
    L.append("  var k = 0;")
    # dispatcher: cls then jump into frame k's first chunk
    disp = "  method frame() { cls();"
    for fk in range(FRAMES):
        disp += (" if" if fk == 0 else " else if") + (" (k == %d) { send self.m%d_0(); }" % (fk, fk))
    disp += " }"
    L.append(disp)
    L.append("  method tock() { k = k + 1; if (k >= %d) { k = 0; } wait(%d); send self.frame(); }" % (FRAMES, MS))
    total = 0
    for fk in range(FRAMES):
        yaw = 2*math.pi*fk/FRAMES
        fr = bake_frame(tris, yaw, pitch, cx3, cy3, cz3, s, CX, CY)
        total += len(fr)
        chunks = [fr[i:i+CHUNK] for i in range(0, len(fr), CHUNK)] or [[]]
        for ci, ch in enumerate(chunks):
            L.append("  method m%d_%d() {" % (fk, ci))
            for (_d, _a, x1, y1, x2, y2, x3, y3, col) in ch:
                L.append("    tri(%d,%d,%d,%d,%d,%d,%d);" % (x1, y1, x2, y2, x3, y3, col))
            L.append("    send self.m%d_%d();" % (fk, ci+1) if ci+1 < len(chunks) else "    send self.tock();")
            L.append("  }")
    L.append("}")
    open(OUT, "w").write("\n".join(L))
    print("wrote %s : %d frames, ~%d tris total, %.1f MB" % (OUT, FRAMES, total, len(open(OUT).read())/1e6))


if __name__ == "__main__":
    main()
