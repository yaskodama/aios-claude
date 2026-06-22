#!/usr/bin/env python3
"""avm_blender_gui.py — the Mac "Blender display system" with a control panel.

A Tkinter window with LOAD / PLAY / STOP / QUIT buttons and a viewport.

  * LOAD  — open a .glb (loaded directly, rendered with a real Z-buffer so the
            closed eyes / layered face come out right) or a .avm actor module
            (run through the same AVM VM the Xinu kernel uses).
  * PLAY  — turntable: spin the model (glb only).
  * STOP  — halt the turntable.
  * QUIT  — exit.

No external deps: GLB/AVM parsed by hand, frames shown via Tk PhotoImage (PPM).

  python3 avm_blender_gui.py [file.glb|file.avm]
"""
import sys, os, struct, json, math, tempfile
import tkinter as tk
from tkinter import filedialog

W, H = 620, 520                       # viewport size
S = 0.42 * H; CX, CY = W / 2, 0.48 * H
G_BG = 0xFF06100A
SWAP_RB = True                        # match the .avm generator
HW_SWAP_RB = True                     # match this Pi4 framebuffer's R/B swap
PAL = [0xFF000000, 0xFF3060FF, 0xFF30D040, 0xFF30D0D0,
       0xFFE03030, 0xFFE040E0, 0xFFE0E040, 0xFFF0F0F0,
       0xFF808080, 0xFF80A0FF, 0xFF80FF80, 0xFF80FFFF,
       0xFFFF8080, 0xFFFF80FF, 0xFFFFFF80, 0xFFFFFFFF]
Lx, Ly, Lz = 0.40, 0.60, 0.70
_ln = math.sqrt(Lx*Lx+Ly*Ly+Lz*Lz); Lx, Ly, Lz = Lx/_ln, Ly/_ln, Lz/_ln


def avm_color(c):
    return (0xFF000000 | (c & 0xFFFFFF)) if (c & 0x1000000) else PAL[c & 15]


# ----------------- GLB -----------------
def load_glb(path):
    data = open(path, "rb").read()
    _, _, total = struct.unpack_from("<III", data, 0); off = 12; jb = bb = None
    while off < total:
        clen, ctype = struct.unpack_from("<II", data, off); off += 8
        ch = data[off:off+clen]; off += clen
        if ctype == 0x4E4F534A: jb = json.loads(ch)
        elif ctype == 0x004E4942: bb = ch
    g = jb; prim = g["meshes"][0]["primitives"][0]
    def acc(idx):
        a = g["accessors"][idx]; bv = g["bufferViews"][a["bufferView"]]
        base = bv.get("byteOffset", 0) + a.get("byteOffset", 0); cnt = a["count"]
        ct = a["componentType"]; nc = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
        if ct == 5126: v = struct.unpack_from("<%df" % (cnt*nc), bb, base)
        elif ct == 5121: v = struct.unpack_from("<%dB" % (cnt*nc), bb, base)
        elif ct == 5123: v = struct.unpack_from("<%dH" % (cnt*nc), bb, base)
        return [v[i*nc:(i+1)*nc] for i in range(cnt)]
    P = acc(prim["attributes"]["POSITION"])
    C = acc(prim["attributes"]["COLOR_0"]) if "COLOR_0" in prim["attributes"] else None
    def vcol(i):
        if not C: return (200, 200, 200)
        c = C[i]
        if max(c[:3]) <= 1.0001: return tuple(min(255, int(round(c[k]*255))) for k in range(3))
        return tuple(min(255, int(c[k])) for k in range(3))
    # Weld vertices by position to compute SMOOTH (area-weighted) vertex normals
    # so shading is interpolated across faces (no facet banding) — like Blender.
    key = lambda p: (round(p[0], 5), round(p[1], 5), round(p[2], 5))
    nacc = {}
    for i in range(0, len(P)-2, 3):
        a, b, c = P[i], P[i+1], P[i+2]
        ux, uy, uz = b[0]-a[0], b[1]-a[1], b[2]-a[2]
        vx, vy, vz = c[0]-a[0], c[1]-a[1], c[2]-a[2]
        fn = (uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx)     # area-weighted face normal
        for v in (a, b, c):
            k = key(v); acc = nacc.get(k)
            if acc is None: nacc[k] = [fn[0], fn[1], fn[2]]
            else: acc[0] += fn[0]; acc[1] += fn[1]; acc[2] += fn[2]
    for k, acc in nacc.items():
        l = math.sqrt(acc[0]*acc[0]+acc[1]*acc[1]+acc[2]*acc[2]) or 1.0
        acc[0] /= l; acc[1] /= l; acc[2] /= l
    tris = []
    for i in range(0, len(P)-2, 3):
        a, b, c = P[i], P[i+1], P[i+2]
        tris.append((a, b, c,
                     nacc[key(a)], nacc[key(b)], nacc[key(c)],
                     vcol(i), vcol(i+1), vcol(i+2)))
    return tris


def subdivide_loop(tris):
    """One level of Loop subdivision: 4x triangles + smoothed vertex positions
    (rounds the polygonal silhouette, like Blender's Subdivision Surface)."""
    from collections import defaultdict
    keyf = lambda p: (round(p[0], 5), round(p[1], 5), round(p[2], 5))
    vid = {}; VP = []; VC = []
    def getv(p, c):
        k = keyf(p); j = vid.get(k)
        if j is None: j = len(VP); vid[k] = j; VP.append(list(p)); VC.append(list(c))
        return j
    faces = [(getv(a, ca), getv(b, cb), getv(c, cc)) for (a, b, c, na, nb, ncv, ca, cb, cc) in tris]
    nV = len(VP)
    edge_opp = defaultdict(list); edge_cnt = defaultdict(int); nbrs = defaultdict(set)
    for (i, j, k) in faces:
        for (u, v, w) in ((i, j, k), (j, k, i), (k, i, j)):
            e = (u, v) if u < v else (v, u); edge_opp[e].append(w); edge_cnt[e] += 1
            nbrs[u].add(v); nbrs[v].add(u)
    ept = {}
    for e, opp in edge_opp.items():
        u, v = e
        if len(opp) == 2:
            P = [3/8*(VP[u][d]+VP[v][d]) + 1/8*(VP[opp[0]][d]+VP[opp[1]][d]) for d in range(3)]
        else:
            P = [0.5*(VP[u][d]+VP[v][d]) for d in range(3)]
        ept[e] = len(VP); VP.append(P); VC.append([0.5*(VC[u][d]+VC[v][d]) for d in range(3)])
    bnd = set()
    for e, cnt in edge_cnt.items():
        if cnt == 1: bnd.add(e[0]); bnd.add(e[1])
    newVP = [None]*nV
    for i in range(nV):
        N = nbrs[i]; n = len(N)
        if i in bnd or n == 0:
            newVP[i] = VP[i]
        else:
            beta = (1.0/n)*(5/8 - (3/8 + 0.25*math.cos(2*math.pi/n))**2)
            s = [0.0, 0.0, 0.0]
            for j in N:
                for d in range(3): s[d] += VP[j][d]
            newVP[i] = [(1-n*beta)*VP[i][d] + beta*s[d] for d in range(3)]
    for i in range(nV): VP[i] = newVP[i]
    E = lambda u, v: ept[(u, v) if u < v else (v, u)]
    idx = []
    for (i, j, k) in faces:
        a = E(i, j); b = E(j, k); c = E(k, i)
        idx += [(i, a, c), (j, b, a), (k, c, b), (a, b, c)]
    nrm = [[0.0, 0.0, 0.0] for _ in VP]
    for (i, j, k) in idx:
        ax, ay, az = VP[i]; bx, by, bz = VP[j]; cx2, cy2, cz2 = VP[k]
        ux, uy, uz = bx-ax, by-ay, bz-az; vx, vy, vz = cx2-ax, cy2-ay, cz2-az
        fx, fy, fz = uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
        for t in (i, j, k): nrm[t][0] += fx; nrm[t][1] += fy; nrm[t][2] += fz
    for nn in nrm:
        l = math.sqrt(nn[0]*nn[0]+nn[1]*nn[1]+nn[2]*nn[2]) or 1.0
        nn[0] /= l; nn[1] /= l; nn[2] /= l
    return [(VP[i], VP[j], VP[k], nrm[i], nrm[j], nrm[k],
             tuple(VC[i]), tuple(VC[j]), tuple(VC[k])) for (i, j, k) in idx]


class Rig:
    """Forward-kinematics walk rig ported from makina_walk3.html: classify the
    triangles into 10 body parts, build hip/knee/shoulder/elbow pivots, and pose
    them with a sin-based gait.  pose(0) == the original static mesh."""
    def __init__(self, tris):
        self.tris = tris
        xs = []; ys = []; zs = []
        for (a, b, c, *_ ) in tris:
            for p in (a, b, c): xs.append(p[0]); ys.append(p[1]); zs.append(p[2])
        minX, maxX = min(xs), max(xs); minY, maxY = min(ys), max(ys); minZ, maxZ = min(zs), max(zs)
        H = maxY-minY; cx = (minX+maxX)/2; cz = (minZ+maxZ)/2; halfW = (maxX-minX)/2
        self.swing_x = (maxX-minX) >= (maxZ-minZ)          # frontIsZ -> swing about X
        yKnee = minY+0.27*H; yHip = minY+0.50*H; armMid = minY+0.64*H
        yShld = minY+0.78*H; yNeck = minY+0.86*H; armX = 0.42*halfW
        self.H = H; self.baseY = yHip
        parts = []; sx = {}; cn = {}
        for (a, b, c, *_ ) in tris:
            ax = (a[0]+b[0]+c[0])/3; ay = (a[1]+b[1]+c[1])/3
            side = 'L' if ax < cx else 'R'
            if abs(ax-cx) > armX:      k = ('uarm' if ay >= armMid else 'farm')+side
            elif ay < yHip:            k = ('thigh' if ay >= yKnee else 'shin')+side
            else:                      k = 'head' if ay >= yNeck else 'torso'
            parts.append(k); sx[k] = sx.get(k, 0)+ax; cn[k] = cn.get(k, 0)+1
        self.parts = parts
        mX = lambda k: (sx[k]/cn[k]) if cn.get(k) else cx
        self.P = dict(root=(cx, yHip, cz),
                      hipL=(mX('thighL'), yHip, cz), kneeL=(mX('thighL'), yKnee, cz),
                      hipR=(mX('thighR'), yHip, cz), kneeR=(mX('thighR'), yKnee, cz),
                      shldL=(mX('uarmL'), yShld, cz), elbL=(mX('uarmL'), armMid, cz),
                      shldR=(mX('uarmR'), yShld, cz), elbR=(mX('uarmR'), armMid, cz))
        self.A_HIP = 0.42; self.A_KNEE = 0.95; self.A_SH = 0.40; self.A_EL = 0.6
        self.A_BOB = 0.030*H; self.A_SWAY = 0.045
        self.chain = {'torso': 'spine', 'head': 'spine',
                      'thighL': ('U', 'hipL', 'aHipL'), 'shinL': ('L', 'hipL', 'kneeL', 'aHipL', 'aKneeL'),
                      'thighR': ('U', 'hipR', 'aHipR'), 'shinR': ('L', 'hipR', 'kneeR', 'aHipR', 'aKneeR'),
                      'uarmL': ('U', 'shldL', 'aShL'), 'farmL': ('L', 'shldL', 'elbL', 'aShL', 'aElL'),
                      'uarmR': ('U', 'shldR', 'aShR'), 'farmR': ('L', 'shldR', 'elbR', 'aShR', 'aElR')}

    def pose(self, p):
        s = math.sin(p); pi = math.pi
        ang = dict(aHipL=self.A_HIP*math.sin(p), aHipR=self.A_HIP*math.sin(p+pi),
                   aKneeL=-self.A_KNEE*max(0.0, math.sin(p+pi*0.5)),
                   aKneeR=-self.A_KNEE*max(0.0, math.sin(p+pi*1.5)),
                   aShL=self.A_SH*math.sin(p+pi), aShR=self.A_SH*math.sin(p),
                   aElL=-self.A_EL*(0.4+0.4*math.sin(p)), aElR=-self.A_EL*(0.4+0.4*math.sin(p+pi)))
        sway = self.A_SWAY*s; twist = 0.12*s; bob = self.A_BOB*abs(s)
        P = self.P; root = P['root']; rootpos = (root[0], self.baseY+bob, root[2])
        swing_x = self.swing_x
        def Rsw(v, an):
            c = math.cos(an); si = math.sin(an)
            if swing_x: return (v[0], v[1]*c-v[2]*si, v[1]*si+v[2]*c)
            return (v[0]*c-v[1]*si, v[0]*si+v[1]*c, v[2])
        def Ry(v, an):
            c = math.cos(an); si = math.sin(an); return (v[0]*c+v[2]*si, v[1], -v[0]*si+v[2]*c)
        cs = math.cos(sway); ss_ = math.sin(sway)
        def rootApply(l):
            return (rootpos[0]+l[0]*cs-l[1]*ss_, rootpos[1]+l[0]*ss_+l[1]*cs, rootpos[2]+l[2])
        tf = {}
        for key, ch in self.chain.items():
            if ch == 'spine':
                def f(v, root=root):
                    return rootApply(Ry((v[0]-root[0], v[1]-root[1], v[2]-root[2]), twist))
            elif ch[0] == 'U':
                piv = P[ch[1]]; a = ang[ch[2]]; off = (piv[0]-root[0], piv[1]-root[1], piv[2]-root[2])
                def f(v, piv=piv, a=a, off=off):
                    l = Rsw((v[0]-piv[0], v[1]-piv[1], v[2]-piv[2]), a)
                    return rootApply((off[0]+l[0], off[1]+l[1], off[2]+l[2]))
            else:
                piv1 = P[ch[1]]; piv2 = P[ch[2]]; a1 = ang[ch[3]]; a2 = ang[ch[4]]
                off1 = (piv1[0]-root[0], piv1[1]-root[1], piv1[2]-root[2])
                off2 = (piv2[0]-piv1[0], piv2[1]-piv1[1], piv2[2]-piv1[2])
                def f(v, piv2=piv2, a1=a1, a2=a2, off1=off1, off2=off2):
                    l = Rsw((v[0]-piv2[0], v[1]-piv2[1], v[2]-piv2[2]), a2)
                    g2 = Rsw((off2[0]+l[0], off2[1]+l[1], off2[2]+l[2]), a1)
                    return rootApply((off1[0]+g2[0], off1[1]+g2[1], off1[2]+g2[2]))
            tf[key] = f
        parts = self.parts; out = []
        for i, (a, b, c, na, nb, nc, ca, cb, cc) in enumerate(self.tris):
            f = tf[parts[i]]
            out.append((f(a), f(b), f(c), na, nb, nc, ca, cb, cc))
        return out


def render_glb(tris, yaw, pitch, ss=1, smooth=True, wire=False):
    """Render at ss x resolution, then box-downsample -> anti-aliased.  smooth=
    True: Gouraud shading (per-vertex normals interpolated across the face, like
    Blender's smooth shading) — no facet banding.  smooth=False: fast flat."""
    w, h = W*ss, H*ss; s = S*ss; cx, cy = CX*ss, CY*ss
    cyaw, syaw = math.cos(yaw), math.sin(yaw); cp, sp = math.cos(pitch), math.sin(pitch)
    def rot(v):
        x, y, z = v; x2 = x*cyaw+z*syaw; z2 = -x*syaw+z*cyaw
        return (x2, y*cp-z2*sp, y*sp+z2*cp)
    def shade(n, col):                       # rotate the vertex normal, light it
        rx = n[0]*cyaw+n[2]*syaw; rz2 = -n[0]*syaw+n[2]*cyaw
        ry = n[1]*cp-rz2*sp; rz = n[1]*sp+rz2*cp
        f = 0.45 + 0.55*max(0.0, rx*Lx+ry*Ly+rz*Lz)
        r = min(255.0, col[0]*f); gg = min(255.0, col[1]*f); bl = min(255.0, col[2]*f)
        if SWAP_RB: r, bl = bl, r
        return r, gg, bl
    fb = [G_BG]*(w*h); zb = [-1e30]*(w*h)
    for (a, b, c, na, nb, ncv, ca, cb, cc) in tris:
        A, B3, Cc = rot(a), rot(b), rot(c)
        if smooth:
            r0, g0, b0 = shade(na, ca); r1, g1, b1 = shade(nb, cb); r2, g2, b2 = shade(ncv, cc)
        else:
            ux, uy, uz = B3[0]-A[0], B3[1]-A[1], B3[2]-A[2]
            vx, vy, vz = Cc[0]-A[0], Cc[1]-A[1], Cc[2]-A[2]
            nx, ny, nz = uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
            nl = math.sqrt(nx*nx+ny*ny+nz*nz) or 1.0
            f = 0.45 + 0.55*max(0.0, (nx*Lx+ny*Ly+nz*Lz)/nl)
            rgb = tuple(sum(t)//3 for t in zip(ca, cb, cc))
            rr = min(255.0, rgb[0]*f); gg = min(255.0, rgb[1]*f); bb = min(255.0, rgb[2]*f)
            if SWAP_RB: rr, bb = bb, rr
            r0 = r1 = r2 = rr; g0 = g1 = g2 = gg; b0 = b1 = b2 = bb
        V = [(int(round(cx+s*A[0])),  int(round(cy-s*A[1])),  A[2],  r0, g0, b0),
             (int(round(cx+s*B3[0])), int(round(cy-s*B3[1])), B3[2], r1, g1, b1),
             (int(round(cx+s*Cc[0])), int(round(cy-s*Cc[1])), Cc[2], r2, g2, b2)]
        if wire:                                   # draw the 3 edges only (see-through)
            for p, q in ((0, 1), (1, 2), (2, 0)):
                xA, yA = V[p][0], V[p][1]; xB, yB = V[q][0], V[q][1]
                col = 0xFF000000 | (int(V[p][3]) << 16) | (int(V[p][4]) << 8) | int(V[p][5])
                nseg = max(abs(xB-xA), abs(yB-yA), 1)
                for t in range(nseg+1):
                    xx = xA + (xB-xA)*t//nseg; yy = yA + (yB-yA)*t//nseg
                    if 0 <= xx < w and 0 <= yy < h: fb[yy*w+xx] = col
            continue
        V.sort(key=lambda t: t[1])
        (x0, y0, z0, ra0, ga0, ba0), (x1, y1, z1, ra1, ga1, ba1), (x2, y2, z2, ra2, ga2, ba2) = V
        if y2 == y0: continue
        tot = y2 - y0
        lo = max(0, y0); hi = min(h-1, y2)
        for yy in range(lo, hi+1):
            ta = (yy-y0)/tot
            xa = x0+(x2-x0)*ta; za = z0+(z2-z0)*ta
            rA = ra0+(ra2-ra0)*ta; gA = ga0+(ga2-ga0)*ta; bA = ba0+(ba2-ba0)*ta
            if yy < y1 and y1 != y0:
                tb = (yy-y0)/(y1-y0)
                xb = x0+(x1-x0)*tb; zbb = z0+(z1-z0)*tb
                rB = ra0+(ra1-ra0)*tb; gB = ga0+(ga1-ga0)*tb; bB = ba0+(ba1-ba0)*tb
            elif y2 != y1:
                tb = (yy-y1)/(y2-y1)
                xb = x1+(x2-x1)*tb; zbb = z1+(z2-z1)*tb
                rB = ra1+(ra2-ra1)*tb; gB = ga1+(ga2-ga1)*tb; bB = ba1+(ba2-ba1)*tb
            else:
                xb = x1; zbb = z1; rB = ra1; gB = ga1; bB = ba1
            if xa > xb:
                xa, xb = xb, xa; za, zbb = zbb, za; rA, rB = rB, rA; gA, gB = gB, gA; bA, bB = bB, bA
            span = xb - xa; inv = (1.0/span) if span > 0 else 0.0
            xi0 = max(0, int(xa)); xi1 = min(w-1, int(xb)); base = yy*w
            for xx in range(xi0, xi1+1):
                tt = (xx-xa)*inv
                z = za+(zbb-za)*tt; idx = base+xx
                if z > zb[idx]:
                    zb[idx] = z
                    rr = rA+(rB-rA)*tt; gg = gA+(gB-gA)*tt; bb = bA+(bB-bA)*tt
                    fb[idx] = 0xFF000000 | (int(rr) << 16) | (int(gg) << 8) | int(bb)
    if ss == 1:
        return fb
    out = [0]*(W*H); n = ss*ss
    for Y in range(H):
        oy = Y*ss; orow = Y*W
        for X in range(W):
            ox = X*ss; rr = gg2 = bb = 0
            for dy in range(ss):
                bse = (oy+dy)*w + ox
                for dx in range(ss):
                    u = fb[bse+dx]; rr += (u >> 16) & 0xFF; gg2 += (u >> 8) & 0xFF; bb += u & 0xFF
            out[orow+X] = 0xFF000000 | ((rr//n) << 16) | ((gg2//n) << 8) | (bb//n)
    return out


# ----------------- AVM <-> source-mesh companion -----------------
def companion_glb(avm_path):
    """An .avm is a single-pose 2-D projection, so SPIN/WALK/Smooth/Subdiv need the
    original 3-D mesh.  Find the .glb the avm was baked from: (1) a sidecar
    <stem>.glbsrc holding a path, (2) a same-stem .glb beside the avm, (3) the
    default MAKINA preview mesh.  Returns a path or None."""
    stem = avm_path[:-4] if avm_path.lower().endswith(".avm") else avm_path
    side = stem + ".glbsrc"
    if os.path.exists(side):
        p = open(side).read().strip()
        if p and os.path.exists(p): return p
    if os.path.exists(stem + ".glb"): return stem + ".glb"
    dflt = "/Users/kodamay/projects/milky-character/makina_preview.glb"
    return dflt if os.path.exists(dflt) else None


# ----------------- AVM2: binary vertex-buffer region (full 3-D mesh) -----------------
def _parse_avm_header(data):
    """Read the shared AVM1/AVM2 header (strings + classes). Returns (strs, classes, p)
    where p is the byte offset just past the class table (start of any MESH section)."""
    p = 4
    n_str = struct.unpack_from("<H", data, p)[0]; p += 2
    strs = []
    for _ in range(n_str):
        ln = struct.unpack_from("<H", data, p)[0]; p += 2
        strs.append(data[p:p+ln].decode("ascii", "replace")); p += ln
    nc = struct.unpack_from("<H", data, p)[0]; p += 2
    classes = []
    for _ in range(nc):
        name = struct.unpack_from("<H", data, p)[0]; p += 2
        nf = struct.unpack_from("<H", data, p)[0]; p += 2
        nm = struct.unpack_from("<H", data, p)[0]; p += 2
        methods = []
        for _ in range(nm):
            mn = struct.unpack_from("<H", data, p)[0]; p += 2
            npar = data[p]; p += 1
            clen = struct.unpack_from("<H", data, p)[0]; p += 2
            methods.append((mn, npar, data[p:p+clen])); p += clen
        classes.append((name, nf, methods))
    return strs, classes, p


def load_avm2_mesh(path):
    """Load an AVM2 actor whose binary MESH region embeds the full 3-D mesh, and
    decode it into glb-style triangles [(a,b,c, na,nb,nc, ca,cb,cc), ...] with
    smooth (area-weighted) vertex normals — identical shape to load_glb, so every
    3-D feature (SPIN / WALK / Smooth / Subdiv / AA / Wire) works straight from the
    .avm with NO external mesh.  Also runs the tiny actor program so MESH3D's
    baked (yaw,pitch) is honoured.  Returns (tris, yaw, pitch)."""
    data = open(path, "rb").read()
    assert data[:4] == b'AVM2', "not an AVM2 module"
    strs, classes, p = _parse_avm_header(data)
    assert data[p] == 1, "AVM2 has no mesh section"; p += 1
    nuv, ntri, idxw, scale = struct.unpack_from("<IIBi", data, p); p += 13
    ifmt = "<H" if idxw == 2 else "<I"
    inv = 1.0 / (scale or 1)
    pos = [None]*nuv; col = [None]*nuv
    for i in range(nuv):
        xi, yi, zi, r, gbb, b = struct.unpack_from("<3h3B", data, p); p += 9
        pos[i] = (xi*inv, yi*inv, zi*inv); col[i] = (r, gbb, b)
    idx = [struct.unpack_from(ifmt, data, p + k*idxw)[0] for k in range(ntri*3)]
    p += ntri*3*idxw

    # smooth vertex normals (area-weighted), accumulated over the index list
    nrm = [[0.0, 0.0, 0.0] for _ in range(nuv)]
    for t in range(ntri):
        ia, ib, ic = idx[t*3], idx[t*3+1], idx[t*3+2]
        a, b, c = pos[ia], pos[ib], pos[ic]
        ux, uy, uz = b[0]-a[0], b[1]-a[1], b[2]-a[2]
        vx, vy, vz = c[0]-a[0], c[1]-a[1], c[2]-a[2]
        fx, fy, fz = uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
        for v in (ia, ib, ic):
            nrm[v][0] += fx; nrm[v][1] += fy; nrm[v][2] += fz
    for n in nrm:
        l = math.sqrt(n[0]*n[0]+n[1]*n[1]+n[2]*n[2]) or 1.0
        n[0] /= l; n[1] /= l; n[2] /= l
    tris = []
    for t in range(ntri):
        ia, ib, ic = idx[t*3], idx[t*3+1], idx[t*3+2]
        tris.append((pos[ia], pos[ib], pos[ic], nrm[ia], nrm[ib], nrm[ic],
                     col[ia], col[ib], col[ic]))

    # run the actor program so MESH3D(yaw,pitch) reports the baked camera
    yaw, pitch = [0.55], [0.16]
    objs = []; q = []
    def spawn(ci): objs.append([ci, [0]*24]); return len(objs)-1
    def find(ci, nm):
        for (mn, npar, code) in classes[ci][2]:
            if strs[mn] == nm: return code
        return None
    def dispatch(recv, sender, mname, args):
        if not (0 <= recv < len(objs)): return
        ci, fields = objs[recv]; code = find(ci, mname)
        if code is None: return
        clen = len(code); pc = 0; stk = []
        while pc < clen:
            op = code[pc]; pc += 1
            if op == 0x01: stk.append(struct.unpack_from("<i", code, pc)[0]); pc += 4
            elif op == 0x02: f = code[pc]; pc += 1; stk.append(fields[f] if f < 24 else 0)
            elif op == 0x03: f = code[pc]; pc += 1; v = stk.pop() if stk else 0; (fields.__setitem__(f, v) if f < 24 else None)
            elif op == 0x04: aa = code[pc]; pc += 1; stk.append(args[aa] if aa < len(args) else 0)
            elif op == 0x05: stk.append(recv)
            elif op == 0x40:
                mn = struct.unpack_from("<H", code, pc)[0]; pc += 2; na = code[pc]; pc += 1
                va = [stk.pop() for _ in range(na)][::-1]; rc = stk.pop() if stk else 0
                if 0 <= mn < len(strs): q.append((rc, recv, strs[mn], va))
            elif op == 0x41: ci2 = struct.unpack_from("<H", code, pc)[0]; pc += 2; stk.append(spawn(ci2))
            elif op == 0x43: pc = clen
            elif op == 0x46: pass                                  # CLS
            elif op == 0x48:                                       # MESH3D: pop pitch, yaw
                pitch[0] = (stk.pop() if stk else 160) / 1000.0
                yaw[0] = (stk.pop() if stk else 550) / 1000.0
            else:
                # skip operands of any other ops we don't model here
                if op in (0x30, 0x31): pc += 2
    boot = spawn(0); q.append((boot, -1, "tick", [])); guard = 0
    while q and guard < 100000:
        guard += 1; rc, sn, mn, ar = q.pop(0); dispatch(rc, sn, mn, ar)
    return tris, yaw[0], pitch[0]


# ----------------- AVM VM (for .avm files) -----------------
def load_avm(path):
    data = open(path, "rb").read()
    assert data[:4] == b'AVM1'
    p = 4; n_str = struct.unpack_from("<H", data, p)[0]; p += 2
    strs = []
    for _ in range(n_str):
        ln = struct.unpack_from("<H", data, p)[0]; p += 2
        strs.append(data[p:p+ln].decode("ascii", "replace")); p += ln
    nc = struct.unpack_from("<H", data, p)[0]; p += 2
    classes = []
    for _ in range(nc):
        name = struct.unpack_from("<H", data, p)[0]; p += 2
        nf = struct.unpack_from("<H", data, p)[0]; p += 2
        nm = struct.unpack_from("<H", data, p)[0]; p += 2
        methods = []
        for _ in range(nm):
            mn = struct.unpack_from("<H", data, p)[0]; p += 2
            npar = data[p]; p += 1
            clen = struct.unpack_from("<H", data, p)[0]; p += 2
            methods.append((mn, npar, data[p:p+clen])); p += clen
        classes.append((name, nf, methods))
    # run VM, collect triangles (2D)
    objs = []; q = []; tris = []
    def spawn(ci): objs.append([ci, [0]*24]); return len(objs)-1
    def find(ci, nm):
        for (mn, npar, code) in classes[ci][2]:
            if strs[mn] == nm: return code
        return None
    def dispatch(recv, sender, mname, args):
        if recv < 0 or recv >= len(objs): return
        ci, fields = objs[recv]; code = find(ci, mname)
        if code is None: return
        clen = len(code); pc = 0; stk = []
        while pc < clen:
            op = code[pc]; pc += 1
            if op == 0x01: stk.append(struct.unpack_from("<i", code, pc)[0]); pc += 4
            elif op == 0x02: f = code[pc]; pc += 1; stk.append(fields[f] if f < 24 else 0)
            elif op == 0x03: f = code[pc]; pc += 1; v = stk.pop() if stk else 0; fields.__setitem__(f, v) if f < 24 else None
            elif op == 0x04: aa = code[pc]; pc += 1; stk.append(args[aa] if aa < len(args) else 0)
            elif op == 0x05: stk.append(recv)
            elif op == 0x06: stk.append(sender)
            elif op == 0x07: (stk.pop() if stk else 0)
            elif op == 0x08: stk.append(stk[-1] if stk else 0)
            elif 0x10 <= op <= 0x14:
                b = stk.pop(); a = stk.pop()
                stk.append({0x10: a+b, 0x11: a-b, 0x12: a*b, 0x13: (a//b if b else 0), 0x14: (a % b if b else 0)}[op])
            elif 0x20 <= op <= 0x25:
                b = stk.pop(); a = stk.pop()
                stk.append(int({0x20: a < b, 0x21: a <= b, 0x22: a > b, 0x23: a >= b, 0x24: a == b, 0x25: a != b}[op]))
            elif op == 0x30: pc = struct.unpack_from("<H", code, pc)[0]
            elif op == 0x31:
                t = struct.unpack_from("<H", code, pc)[0]; pc += 2
                if (stk.pop() if stk else 0) == 0: pc = t
            elif op == 0x40:
                mn = struct.unpack_from("<H", code, pc)[0]; pc += 2; na = code[pc]; pc += 1
                va = [stk.pop() for _ in range(na)][::-1]; rc = stk.pop() if stk else 0
                if 0 <= mn < len(strs): q.append((rc, recv, strs[mn], va))
            elif op == 0x41: ci2 = struct.unpack_from("<H", code, pc)[0]; pc += 2; stk.append(spawn(ci2))
            elif op == 0x43: pc = clen
            elif op == 0x46: tris.clear()
            elif op == 0x47:
                col = stk.pop(); y3 = stk.pop(); x3 = stk.pop(); y2 = stk.pop(); x2 = stk.pop(); y1 = stk.pop(); x1 = stk.pop()
                tris.append((x1, y1, x2, y2, x3, y3, col))
            else: pc = clen
    boot = spawn(0); q.append((boot, -1, "tick", [])); guard = 0
    while q and guard < 2_000_000:
        guard += 1; recv, sender, mn, args = q.pop(0); dispatch(recv, sender, mn, args)
    return tris


def render_avm(tris2d, ss=3, wire=False):
    # .avm coords were generated for 760x620; scale into ss x viewport, then
    # box-downsample -> anti-aliased (matches the glb view's smoothness).
    # ss>1 = AA toggle; wire=True draws each triangle's 3 edges only (see-through).
    w, h = W*ss, H*ss
    sx, sy = w/760.0, h/620.0
    fb = [G_BG]*(w*h)
    for (x1, y1, x2, y2, x3, y3, c) in tris2d:
        col = avm_color(c)
        X = [int(x1*sx), int(x2*sx), int(x3*sx)]; Y = [int(y1*sy), int(y2*sy), int(y3*sy)]
        if wire:
            for p, q in ((0, 1), (1, 2), (2, 0)):
                xa, ya = X[p], Y[p]; xb, yb = X[q], Y[q]
                n = max(abs(xb-xa), abs(yb-ya), 1)
                for t in range(n+1):
                    xx = xa + (xb-xa)*t//n; yy = ya + (yb-ya)*t//n
                    if 0 <= xx < w and 0 <= yy < h: fb[yy*w+xx] = col
            continue
        pts = sorted(zip(Y, X)); (ya, xa), (yb, xb), (yc, xc) = pts
        if yc == ya: continue
        lo = max(0, ya); hi = min(h-1, yc)
        for yy in range(lo, hi+1):
            xl = xa + (xc-xa)*(yy-ya)//(yc-ya)
            if yy < yb and yb != ya: xr = xa + (xb-xa)*(yy-ya)//(yb-ya)
            elif yc != yb:           xr = xb + (xc-xb)*(yy-yb)//(yc-yb)
            else:                    xr = xb
            if xl > xr: xl, xr = xr, xl
            if xl < 0: xl = 0
            if xr >= w: xr = w-1
            base = yy*w
            for xx in range(xl, xr+1): fb[base+xx] = col
    if ss == 1:
        return fb
    out = [0]*(W*H); n = ss*ss
    for Y in range(H):
        oy = Y*ss; orow = Y*W
        for X in range(W):
            ox = X*ss; rr = gg2 = bb = 0
            for dy in range(ss):
                bse = (oy+dy)*w + ox
                for dx in range(ss):
                    u = fb[bse+dx]; rr += (u >> 16) & 0xFF; gg2 += (u >> 8) & 0xFF; bb += u & 0xFF
            out[orow+X] = 0xFF000000 | ((rr//n) << 16) | ((gg2//n) << 8) | (bb//n)
    return out


def fb_to_ppm(fb, path):
    out = bytearray(b"P6\n%d %d\n255\n" % (W, H))
    for u in fb:
        if HW_SWAP_RB: out += bytes((u & 0xFF, (u >> 8) & 0xFF, (u >> 16) & 0xFF))
        else:          out += bytes(((u >> 16) & 0xFF, (u >> 8) & 0xFF, u & 0xFF))
    open(path, "wb").write(out)


# ----------------- GUI -----------------
WALK_FRAMES = 24                    # baked frames over one gait cycle


class App:
    def __init__(self, root, initial=None):
        self.root = root
        root.title("AIPL Blender Display System")
        bar = tk.Frame(root, bg="#222"); bar.pack(side=tk.TOP, fill=tk.X)
        mk = lambda t, c: tk.Button(bar, text=t, width=6, command=c).pack(side=tk.LEFT, padx=3, pady=4)
        mk("LOAD", self.on_load); mk("WALK", self.on_walk); mk("SPIN", self.on_play)
        mk("STOP", self.on_stop); mk("QUIT", root.destroy)
        # feature ON/OFF toggles
        self.f_smooth = tk.BooleanVar(value=True)
        self.f_aa = tk.BooleanVar(value=True)
        self.f_subdiv = tk.BooleanVar(value=False)
        self.f_wire = tk.BooleanVar(value=False)
        # AVM: when an .avm is loaded with its 3-D companion, ON shows the actual
        # kernel avm raster; OFF shows the glb 3-D (full Blender smooth/subdiv).
        self.f_avm = tk.BooleanVar(value=True)
        for label, var in (("Smooth", self.f_smooth), ("AA", self.f_aa),
                           ("Subdiv", self.f_subdiv), ("Wire", self.f_wire),
                           ("AVM", self.f_avm)):
            tk.Checkbutton(bar, text=label, variable=var, command=self.on_toggle,
                           bg="#222", fg="#cde", selectcolor="#333",
                           activebackground="#222", activeforeground="#fff").pack(side=tk.LEFT, padx=2)
        self.status = tk.Label(bar, text="LOAD a .glb or .avm", bg="#222", fg="#9cf")
        self.status.pack(side=tk.LEFT, padx=10)
        self.canvas = tk.Canvas(root, width=W, height=H, bg="#06100a", highlightthickness=0)
        self.canvas.pack()
        self.img = tk.PhotoImage(width=W, height=H)
        self.cimg = self.canvas.create_image(0, 0, anchor=tk.NW, image=self.img)
        self.tmp = os.path.join(tempfile.gettempdir(), "_avm_gui_frame.ppm")
        self.glb_tris = None; self.avm_tris = None
        self.glb_sub = None                         # cached subdivided mesh
        self.rig = None
        self.walk_frames = []; self.walk_yaw = None; self.walk_idx = 0
        self.yaw = 0.55; self.pitch = 0.16
        self.spinning = False; self.walking = False; self._job = None
        if initial: self.load(initial)

    def show(self, fb):
        fb_to_ppm(fb, self.tmp)
        self.img = tk.PhotoImage(file=self.tmp)
        self.canvas.itemconfig(self.cimg, image=self.img)

    def active_tris(self):
        if self.f_subdiv.get():
            if self.glb_sub is None:
                self.status.config(text="subdividing ..."); self.root.update()
                self.glb_sub = subdivide_loop(self.glb_tris)
            return self.glb_sub
        return self.glb_tris

    def render_static(self):
        # AVM raster when an avm is loaded and the AVM toggle is on (or no 3-D
        # companion); otherwise the glb 3-D view with full Blender features.
        if self.avm_tris is not None and (self.glb_tris is None or self.f_avm.get()):
            ss = 3 if self.f_aa.get() else 1        # AA toggle applies to the avm too
            self.show(render_avm(self.avm_tris, ss, self.f_wire.get()))  # Wire toggle too
        elif self.glb_tris is not None:
            ss = 4 if self.f_aa.get() else 1
            self.show(render_glb(self.active_tris(), self.yaw, self.pitch,
                                 ss, self.f_smooth.get(), self.f_wire.get()))

    def on_toggle(self):
        if self.walking or self.spinning: return    # toggles apply to the static view
        feats = [n for n, v in (("Smooth", self.f_smooth), ("AA", self.f_aa),
                                ("Subdiv", self.f_subdiv), ("Wire", self.f_wire)) if v.get()]
        self.status.config(text="rendering [%s] ..." % (" ".join(feats) or "flat")); self.root.update()
        self.render_static()
        self.status.config(text="features: %s" % (" ".join(feats) or "(all off)"))

    def load(self, path):
        self.on_stop(); self.glb_sub = None; self.walk_frames = []; self.rig = None
        self.status.config(text="loading %s ..." % os.path.basename(path)); self.root.update()
        try:
            if path.lower().endswith(".glb"):
                self.glb_tris = load_glb(path); self.avm_tris = None
                self.yaw = 0.55; self.rig = Rig(self.glb_tris); self.render_static()
                self.status.config(text="GLB: %s  (%d tris) — WALK / SPIN / toggles" % (os.path.basename(path), len(self.glb_tris)))
            elif path.lower().endswith(".avm"):
                magic = open(path, "rb").read(4)
                if magic == b'AVM2':
                    # AVM2 embeds the full 3-D mesh in its binary vertex buffer ->
                    # decode straight to 3-D tris; every feature works from the avm.
                    self.glb_tris, self.yaw, self.pitch = load_avm2_mesh(path)
                    self.avm_tris = None; self.rig = Rig(self.glb_tris)
                    self.render_static()
                    self.status.config(text="AVM2 mesh: %s  (%d tris, native 3D) — WALK / SPIN / toggles"
                                        % (os.path.basename(path), len(self.glb_tris)))
                else:
                    self.avm_tris = load_avm(path)
                    src = companion_glb(path)       # 3-D mesh for SPIN/WALK/Smooth/Subdiv
                    if src:
                        self.glb_tris = load_glb(src); self.rig = Rig(self.glb_tris); self.yaw = 0.55
                        note = "  +3D companion: WALK/SPIN/Smooth/Subdiv enabled"
                    else:
                        self.glb_tris = None
                        note = "  (no .glb companion -> SPIN/WALK disabled)"
                    self.render_static()
                    self.status.config(text="AVM: %s  (%d tris)%s" % (os.path.basename(path), len(self.avm_tris), note))
            else:
                self.status.config(text="unsupported file (need .glb or .avm)")
        except Exception as e:
            self.status.config(text="load error: %s" % e)

    def on_load(self):
        p = filedialog.askopenfilename(title="Open mesh",
                                       filetypes=[("Mesh/Actor", "*.glb *.avm"), ("glTF binary", "*.glb"),
                                                  ("AVM actor", "*.avm"), ("All", "*.*")])
        if p: self.load(p)

    # ---- turntable spin (glb) ----
    def on_play(self):
        if self.glb_tris is None:
            self.status.config(text="SPIN needs a .glb — LOAD one first"); return
        self.on_stop(quiet=True); self.spinning = True
        self.status.config(text="SPIN — turntable"); self._spin_tick()

    def _spin_tick(self):
        if not self.spinning: return
        self.yaw += 0.20
        self.show(render_glb(self.glb_tris, self.yaw, self.pitch, 1, False, self.f_wire.get()))
        self._job = self.root.after(40, self._spin_tick)

    # ---- walk (glb) ----
    def bake_walk(self):
        """Pre-render one gait cycle (fast flat, current yaw) into PhotoImages."""
        self.walk_frames = []; self.walk_yaw = round(self.yaw, 3)
        for k in range(WALK_FRAMES):
            self.status.config(text="baking walk %d/%d ..." % (k+1, WALK_FRAMES)); self.root.update()
            ph = 2*math.pi*k/WALK_FRAMES
            posed = self.rig.pose(ph)
            fb = render_glb(posed, self.yaw, self.pitch, 1, False, self.f_wire.get())
            fp = os.path.join(tempfile.gettempdir(), "_walk_%02d.ppm" % k)
            fb_to_ppm(fb, fp); self.walk_frames.append(tk.PhotoImage(file=fp))

    def on_walk(self):
        if self.glb_tris is None:
            self.status.config(text="WALK needs a .glb — LOAD one first"); return
        if self.walking:                            # toggle off -> back to static
            self.on_stop(); return
        self.on_stop(quiet=True)
        if not self.walk_frames or self.walk_yaw != round(self.yaw, 3):
            self.bake_walk()
        self.walking = True; self.walk_idx = 0
        self.status.config(text="WALK — animating (release with STOP)"); self._walk_tick()

    def _walk_tick(self):
        if not self.walking or not self.walk_frames: return
        self.canvas.itemconfig(self.cimg, image=self.walk_frames[self.walk_idx])
        self.walk_idx = (self.walk_idx + 1) % len(self.walk_frames)
        self._job = self.root.after(60, self._walk_tick)

    def on_stop(self, quiet=False):
        moving = self.spinning or self.walking
        self.spinning = False; self.walking = False
        if self._job: self.root.after_cancel(self._job); self._job = None
        if not quiet:
            if moving and self.glb_tris is not None:
                self.status.config(text="STOP — static view"); self.root.update()
                self.render_static()
            self.status.config(text="STOP")


def main():
    root = tk.Tk()
    initial = sys.argv[1] if len(sys.argv) > 1 else None
    App(root, initial)
    root.mainloop()


if __name__ == "__main__":
    main()
