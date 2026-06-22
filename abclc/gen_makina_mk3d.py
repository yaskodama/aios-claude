#!/usr/bin/env python3
"""gen_makina_mk3d.py — pack makina_walk3's mesh into an "MK3D" blob and POST it
to Xinu's kernel 3-D "Blender" display (POST /actor/loadmesh), which opens the
turntable viewer (PLAY / PAUSE / END buttons) and rotates it in full 24-bit
colour at full resolution.

MK3D (little-endian):  "MK3D" u32 nv u32 nt  i16 v[nv][3]  u16 t[nt][3]  u8 c[nt][3]
(model scaled so height ~2000; per-triangle RGB)

  python3 gen_makina_mk3d.py [host]      # default 192.168.3.50:8080
"""
import re, base64, struct, sys, urllib.request

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.3.50:8080"
if "://" not in HOST: HOST = "http://" + HOST
HTML = "/Users/kodamay/projects/milky-character/makina_walk3.html"

html = open(HTML).read()
def grab(n):
    m = re.search(r'(?:const|var|let)\s+'+n+r'\s*=\s*"([A-Za-z0-9+/=]+)"', html)
    return base64.b64decode(m.group(1)) if m else None
pb, cb = grab("POS"), grab("COL")
P = struct.unpack("<%df" % (len(pb)//4), pb); NV = len(P)//3
def vcol(i): return (cb[i*3], cb[i*3+1], cb[i*3+2]) if cb else (200,200,200)

# scale so the model (y in -1..1) is ~2000 tall; index-merge duplicate verts
S = 1000.0
GRID = 0.004                      # merge verts within ~0.4% of height
vmap = {}; verts = []
def vid(i):
    x,y,z = P[i*3], P[i*3+1], P[i*3+2]
    k = (round(x/GRID), round(y/GRID), round(z/GRID))
    j = vmap.get(k)
    if j is None:
        j = len(verts); vmap[k] = j
        verts.append((int(round(x*S)), int(round(y*S)), int(round(z*S))))
    return j

tris = []; cols = []
for t in range(0, NV-2, 3):
    a,b,c = vid(t), vid(t+1), vid(t+2)
    if a==b or b==c or a==c: continue          # collapsed by the merge
    tris.append((a,b,c))
    cr = tuple(min(255,sum(x)//3) for x in zip(vcol(t),vcol(t+1),vcol(t+2)))
    cols.append(cr)
nv, nt = len(verts), len(tris)
print(f"[mk3d] verts={nv} tris={nt} (caps 24000/48000)")
assert nv <= 24000 and nt <= 48000, "exceeds makina3d MK_VMAX/MK_TMAX"

blob = bytearray(b"MK3D") + struct.pack("<II", nv, nt)
for v in verts: blob += struct.pack("<hhh", max(-32768,min(32767,v[0])),
                                            max(-32768,min(32767,v[1])),
                                            max(-32768,min(32767,v[2])))
for t in tris:  blob += struct.pack("<HHH", *t)
for c in cols:  blob += struct.pack("<BBB", *c)
print(f"[mk3d] blob={len(blob)} bytes -> {HOST}/actor/loadmesh")

open("/tmp/Makina.mk3d","wb").write(blob)
req = urllib.request.Request(f"{HOST}/actor/loadmesh?ask=0", data=bytes(blob),
                             method="POST",
                             headers={"Content-Type":"application/octet-stream"})
try:
    r = urllib.request.urlopen(req, timeout=120).read().decode("ascii","replace").strip()
    print(f"[mk3d] {r}")
except Exception as e:
    print(f"[mk3d] POST error: {e}")
