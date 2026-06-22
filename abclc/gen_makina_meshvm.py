#!/usr/bin/env python3
"""gen_makina_meshvm.py — bake a .glb into a COMPACT AVM2 actor that embeds the
FULL 3-D mesh in a binary vertex-buffer region (not PUSHI literals), so the actor
can re-render the character in 3-D at any angle — equivalent to the glb.

AVM2 = AVM1 (strings + classes + methods + bytecode) followed by an optional
binary MESH section:

  u8   has_mesh (1)
  u32  nverts
  u32  ntris
  u8   idxw            # index width in bytes (2 if nverts<65536 else 4)
  i32  scale           # world coord = int16 / scale
  verts[nverts]        # each: i16 x, i16 y, i16 z, u8 r, u8 g, u8 b   (9 bytes)
  idx[ntris*3]         # idxw-byte vertex indices, CCW

A new opcode MESH3D (0x48) pops (yaw_mrad, pitch_mrad) and draws the embedded
mesh.  The actor program is tiny: Main spawns MeshDisplay and sends draw(); the
display method does cls() then mesh3d(yaw,pitch).  The heavy data lives once in
the binary region, welded + indexed, so the file is far smaller than either the
PUSHI-literal embedding (~2.4 MB) or the glb itself (~1.84 MB).

  python3 gen_makina_meshvm.py [in.glb] [out.avm]
"""
import sys, os, struct, math, json

GLB = sys.argv[1] if len(sys.argv) > 1 else "/Users/kodamay/projects/milky-character/makina_preview.glb"
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "MakinaMesh.avm")
YAW, PITCH = 0.55, 0.16


def load_glb(path):
    data = open(path, "rb").read()
    total = struct.unpack_from("<III", data, 0)[2]; off = 12; jb = bb = None
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
    return P, vcol


P, vcol = load_glb(GLB)
NV = len(P)
NT = NV // 3
sys.stderr.write("[mesh] glb verts=%d tris=%d\n" % (NV, NT))

# ---- weld vertices (position + colour) -> unique vertex list + index list ----
key = lambda p, c: (round(p[0], 5), round(p[1], 5), round(p[2], 5), c)
vid = {}; verts = []; idx = []
for i in range(0, NV - 2, 3):
    for j in (i, i+1, i+2):
        c = vcol(j); k = key(P[j], c)
        v = vid.get(k)
        if v is None:
            v = len(verts); vid[k] = v; verts.append((P[j], c))
        idx.append(v)
NUV = len(verts)
sys.stderr.write("[mesh] welded unique verts=%d  index tris=%d\n" % (NUV, len(idx)//3))

# ---- scale positions into int16 ----
maxabs = 0.0
for (p, c) in verts: maxabs = max(maxabs, abs(p[0]), abs(p[1]), abs(p[2]))
SCALE = int(32000 / (maxabs or 1.0))
sys.stderr.write("[mesh] maxabs=%.4f scale=%d (i16 precision ~%.5f world units)\n"
                 % (maxabs, SCALE, 1.0/SCALE))

idxw = 2 if NUV < 65536 else 4
ifmt = "<H" if idxw == 2 else "<I"

mesh = bytearray()
mesh += struct.pack("<B", 1)                       # has_mesh
mesh += struct.pack("<IIBi", NUV, len(idx)//3, idxw, SCALE)
for (p, c) in verts:
    xi = max(-32768, min(32767, int(round(p[0]*SCALE))))
    yi = max(-32768, min(32767, int(round(p[1]*SCALE))))
    zi = max(-32768, min(32767, int(round(p[2]*SCALE))))
    mesh += struct.pack("<3h3B", xi, yi, zi, c[0] & 255, c[1] & 255, c[2] & 255)
for v in idx:
    mesh += struct.pack(ifmt, v)
sys.stderr.write("[mesh] binary section bytes=%d\n" % len(mesh))

# ================= AVM2 program (tiny actor that draws the mesh) =================
strs = []
def sid(s):
    if s not in strs: strs.append(s)
    return strs.index(s)
OP = dict(PUSHI=0x01, LDF=0x02, STF=0x03, LDA=0x04, SELF=0x05,
          SEND=0x40, SPAWN=0x41, RET=0x43, CLS=0x46, MESH3D=0x48)
def asm(prog):
    b = bytearray()
    for ins in prog:
        b.append(OP[ins[0]])
        if ins[0] == 'PUSHI': b += struct.pack('<i', ins[1])
        elif ins[0] in ('LDF', 'STF', 'LDA'): b.append(ins[1] & 0xff)
        elif ins[0] == 'SPAWN': b += struct.pack('<H', ins[1])
        elif ins[0] == 'SEND': b += struct.pack('<H', sid(ins[1])); b.append(ins[2] & 0xff)
    return bytes(b)

DISPLAY_CI = 1
yaw_mrad = int(round(YAW * 1000)); pitch_mrad = int(round(PITCH * 1000))
main_tick = asm([('SPAWN', DISPLAY_CI), ('STF', 0),
                 ('LDF', 0), ('PUSHI', yaw_mrad), ('PUSHI', pitch_mrad),
                 ('SEND', 'draw', 2), ('RET',)])
# draw(yaw,pitch): cls(); mesh3d(yaw,pitch)   (MESH3D pops pitch then yaw)
disp_draw = asm([('CLS',), ('LDA', 0), ('LDA', 1), ('MESH3D',), ('RET',)])

def u16(v): return struct.pack('<H', v)
def method(name, npar, code): return u16(sid(name)) + bytes([npar]) + u16(len(code)) + code
cls_main = u16(sid('Main')) + u16(1) + u16(1) + method('tick', 0, main_tick)
cls_disp = u16(sid('MeshDisplay')) + u16(0) + u16(1) + method('draw', 2, disp_draw)

mod = bytearray(b'AVM2'); mod += u16(len(strs))
for s in strs: sb = s.encode(); mod += u16(len(sb)) + sb
mod += u16(2) + cls_main + cls_disp
mod += mesh                                       # <-- binary vertex-buffer region
open(OUT, 'wb').write(mod)

# ---- .abcl source (documentation) ----
abcl = ["// MakinaMesh.abcl - AVM2: full 3-D mesh embedded as a binary vertex buffer.",
        "// %d unique verts (i16 xyz + u8 rgb), %d indexed tris.  Renders in 3-D at any angle." % (NUV, len(idx)//3),
        "",
        "class Main {", "  var d = 0;",
        "  method tick() { d = new MeshDisplay(); send d.draw(%d, %d); }" % (yaw_mrad, pitch_mrad), "}", "",
        "class MeshDisplay {",
        "  // cls() clears; mesh3d(yaw,pitch) projects+shades+rasterises the embedded mesh.",
        "  method draw(yaw, pitch) { cls(); mesh3d(yaw, pitch); }", "}", "",
        "var boot = new Main(); send boot.tick();"]
SRC = OUT[:-4] + ".abcl" if OUT.endswith(".avm") else OUT + ".abcl"
open(SRC, "w").write("\n".join(abcl) + "\n")

glb_sz = os.path.getsize(GLB)
print("wrote %s  (%d bytes = %.2f MB)" % (OUT, len(mod), len(mod)/1048576))
print("  program=%d B  mesh=%d B  | glb=%d B (%.2f MB)  -> %.2fx smaller than glb"
      % (len(mod)-len(mesh), len(mesh), glb_sz, glb_sz/1048576, glb_sz/len(mod)))
print("  + %s" % SRC)
