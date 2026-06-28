#!/usr/bin/env python3
"""gen_makina_solid.py — bake the full MAKINA-7 mesh into a SOLID, flat-shaded,
coloured AIPL actor for the aice-avm host VM (uses the new tri() primitive).

Unlike the old grid-decimated white wireframe (MakinaXinuHi.abcl, line() only),
this emits one filled+shaded tri() per front-facing triangle of the real
makina_preview.glb (40112 tris, vertex colours) — painter-sorted back-to-front,
Lambert flat-shaded — so the simulator window shows a solid character close to
the Three.js reference (lecture.site44.com/robot/standalone.html).

  python3 gen_makina_solid.py [yaw] [pitch] [out.abcl]

The AVM method bytecode length is a u16, so the tri() calls are split across
chained drawer methods d0,d1,... (~1500 tris each) like the wireframe baker.
"""
import sys, os, struct, json, math

# SWAPRB=1 emits B,G,R for boards whose HDMI output is R/B-swapped vs the ARGB
# framebuffer (Pi4/Pi5). Leave unset (=RGB) for the aice-avm host VM canvas.
SWAPRB = os.environ.get("SWAPRB", "0") == "1"

GLB = "/Users/kodamay/projects/milky-character/makina_preview.glb"
GW, GH = 820, 640                         # must match server.ml gw/gh
yaw   = float(sys.argv[1]) if len(sys.argv) > 1 else 0.45
pitch = float(sys.argv[2]) if len(sys.argv) > 2 else 0.12
OUT   = sys.argv[3] if len(sys.argv) > 3 else "MakinaSolid.abcl"
CHUNK = 1500                              # tris per drawer method (u16 cap safe)

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

    tris = []
    for i in range(0, len(P)-2, 3):
        tris.append((P[i], P[i+1], P[i+2], vcol(i), vcol(i+1), vcol(i+2)))
    return tris


def main():
    tris = load_glb(GLB)
    # model bbox -> centre + fit scale
    xs = [p[0] for t in tris for p in t[:3]]
    ys = [p[1] for t in tris for p in t[:3]]
    zs = [p[2] for t in tris for p in t[:3]]
    cx3, cy3, cz3 = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2, (min(zs)+max(zs))/2
    half = max(max(ys)-min(ys), max(xs)-min(xs)) / 2 or 1.0
    s = 0.44*GH / half
    CX, CY = GW/2, GH*0.46
    cyaw, syaw = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)

    def rot(p):
        x, y, z = p[0]-cx3, p[1]-cy3, p[2]-cz3
        x2 = x*cyaw + z*syaw; z2 = -x*syaw + z*cyaw
        y3 = y*cp - z2*sp;    z3 = y*sp + z2*cp
        return x2, y3, z3

    baked = []
    for (a, b, c, ca, cb, cc) in tris:
        A, B, C = rot(a), rot(b), rot(c)
        ux, uy, uz = B[0]-A[0], B[1]-A[1], B[2]-A[2]
        vx, vy, vz = C[0]-A[0], C[1]-A[1], C[2]-A[2]
        nx, ny, nz = uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
        nl = math.sqrt(nx*nx+ny*ny+nz*nz) or 1.0
        nx, ny, nz = nx/nl, ny/nl, nz/nl
        # DOUBLE-SIDED: don't cull (thin cloth like the skirt/cape would leave
        # see-through gaps). Light whichever side faces the camera (flip normal
        # for back faces) and rely on the painter's depth sort below.
        if nz < 0.0:
            nx, ny, nz = -nx, -ny, -nz
        f = 0.42 + 0.58*max(0.0, nx*Lx+ny*Ly+nz*Lz)
        r = min(255, int((ca[0]+cb[0]+cc[0])/3*f))
        g = min(255, int((ca[1]+cb[1]+cc[1])/3*f))
        bl = min(255, int((ca[2]+cb[2]+cc[2])/3*f))
        if SWAPRB:
            r, bl = bl, r
        col = 0x1000000 | (r << 16) | (g << 8) | bl
        depth = (A[2]+B[2]+C[2])/3.0
        sx = lambda P: int(round(CX + s*P[0])); sy = lambda P: int(round(CY - s*P[1]))
        baked.append((depth, sx(A), sy(A), sx(B), sy(B), sx(C), sy(C), col))

    baked.sort(key=lambda t: t[0])          # back (small z) -> front : painter's
    n = len(baked)
    chunks = [baked[i:i+CHUNK] for i in range(0, n, CHUNK)]

    out = []
    out.append("// MakinaSolid.abcl - SOLID flat-shaded MAKINA-7 for aice-avm (tri()).")
    out.append("// %d front-facing tris, yaw=%.3f pitch=%.3f, painter-sorted." % (n, yaw, pitch))
    out.append("")
    out.append("class Main {")
    out.append("  var r = 0;")
    out.append("  method tick() { r = new Ed(); send r.run(); }")
    out.append("}")
    out.append("")
    out.append("class Ed {")
    out.append("  method run() { cls(); send self.d0(); }")
    for ci, ch in enumerate(chunks):
        out.append("  method d%d() {" % ci)
        for (_d, x1, y1, x2, y2, x3, y3, col) in ch:
            out.append("    tri(%d,%d,%d,%d,%d,%d,%d);" % (x1, y1, x2, y2, x3, y3, col))
        if ci+1 < len(chunks):
            out.append("    send self.d%d();" % (ci+1))
        out.append("  }")
    out.append("}")
    out.append("")
    out.append("// (no top-level statement: the VM auto-starts class0 Main.tick())")
    open(OUT, "w").write("\n".join(out))
    print("wrote %s : %d front tris in %d methods" % (OUT, n, len(chunks)))


if __name__ == "__main__":
    main()
