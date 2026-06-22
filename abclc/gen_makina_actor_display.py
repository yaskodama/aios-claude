#!/usr/bin/env python3
"""gen_makina_actor_display.py — actor-to-actor "Blender display system" on Xinu.

Bakes the makina_walk3 character into ONE .avm with THREE actors:

  * Display  — the Blender display-system actor.  Methods clear() -> cls() and
               tri(x1,y1,x2,y2,x3,y3,col) -> the kernel op_tri solid fill.  Any
               actor can drive the kernel "Blender" display by messaging it.
  * Makina   — the 3-D-DATA actor.  Holds the projected/shaded triangles as
               bytecode and STREAMS them to the Display actor with `send`.
  * Main     — spawns Display + Makina and wires them (send makina.run(display)).

Flow control: Xinu mailboxes hold MAX_MAILBOX=64 msgs, so Makina sends in
chunks of <= B (<64) and wait()s between chunks to let Display drain — no drops.

  python3 gen_makina_actor_display.py [out.avm]
"""
import re, base64, struct, math, sys

OUT  = sys.argv[1] if len(sys.argv) > 1 else "/tmp/MakinaDisplayActor.avm"
HTML = "/Users/kodamay/projects/milky-character/makina_walk3.html"
W, H = 760, 620
NCHUNK = 15          # Makina chunk methods (run + 15 <= 16 methods/class)
B      = 700         # tris per chunk (< 1024 mailbox after the kernel bump)
WAITMS = 90          # drain time between chunks (lets Display fully drain)
CAP    = NCHUNK * B  # max tris streamed (= 10500, < VMG_TRI_MAX 12000)
YAW, PITCH = 0.55, 0.16
TARGET_SRC = 45000   # keep ~all source; cull+cap limit the result

# ---- load mesh + per-vertex colours ----
html=open(HTML).read()
def grab(n):
    m=re.search(r'(?:const|var|let)\s+'+n+r'\s*=\s*"([A-Za-z0-9+/=]+)"',html)
    return base64.b64decode(m.group(1)) if m else None
pb,cb=grab("POS"),grab("COL")
P=struct.unpack("<%df"%(len(pb)//4),pb); NV=len(P)//3
V=[(P[i*3],P[i*3+1],P[i*3+2]) for i in range(NV)]
def vcol(i): return (cb[i*3],cb[i*3+1],cb[i*3+2]) if cb else (200,200,200)
tris0=[]
for i in range(0,NV-2,3):
    cr=tuple(sum(c)//3 for c in zip(vcol(i),vcol(i+1),vcol(i+2)))  # avg RGB (full colour)
    tris0.append((V[i],V[i+1],V[i+2],cr))
sys.stderr.write(f"[mk] source tris={len(tris0)}\n")

# ---- decimate (grid-snap), keep triangle colour ----
def decimate(g):
    seen=set(); out=[]; q=lambda v:(round(v[0]/g),round(v[1]/g),round(v[2]/g))
    for (a,b,c,hue) in tris0:
        ka,kb,kc=q(a),q(b),q(c)
        if ka==kb or kb==kc or ka==kc: continue
        key=frozenset((ka,kb,kc))
        if key in seen: continue
        seen.add(key)
        out.append((tuple(x*g for x in ka),tuple(x*g for x in kb),tuple(x*g for x in kc),hue))
    return out
lo,hi=0.010,0.25
for _ in range(28):
    g=(lo+hi)/2
    if len(decimate(g))>TARGET_SRC: lo=g
    else: hi=g
tris=decimate(hi); sys.stderr.write(f"[mk] decimated tris={len(tris)} grid={hi:.4f}\n")

# ---- project / cull / shade / depth-sort (single 3/4 frame) ----
S=260.0; CX,CY=W/2,300.0
Lx,Ly,Lz=0.40,0.60,0.70; ln=math.sqrt(Lx*Lx+Ly*Ly+Lz*Lz); Lx,Ly,Lz=Lx/ln,Ly/ln,Lz/ln
cyaw,syaw=math.cos(YAW),math.sin(YAW); cp,sp=math.cos(PITCH),math.sin(PITCH)
def rot(v):
    x,y,z=v; x2=x*cyaw+z*syaw; z2=-x*syaw+z*cyaw
    return (x2, y*cp-z2*sp, y*sp+z2*cp)
def build(cull):
    out=[]
    for (a,b,c,rgb) in tris:
        A,B3,C=rot(a),rot(b),rot(c)
        ux,uy,uz=B3[0]-A[0],B3[1]-A[1],B3[2]-A[2]
        vx,vy,vz=C[0]-A[0],C[1]-A[1],C[2]-A[2]
        nx,ny,nz=uy*vz-uz*vy,uz*vx-ux*vz,ux*vy-uy*vx
        nl=math.sqrt(nx*nx+ny*ny+nz*nz)
        if nl<1e-9: continue
        nx,ny,nz=nx/nl,ny/nl,nz/nl
        if cull*nz<=0: continue
        # full-colour flat shade: modulate the true RGB by ambient+diffuse, then
        # pack 0xRRGGBB with bit24 set so the kernel renders true colour.
        f=0.45+0.55*max(0.0,nx*Lx+ny*Ly+nz*Lz)
        r=min(255,int(rgb[0]*f)); gg=min(255,int(rgb[1]*f)); bl=min(255,int(rgb[2]*f))
        col=0x1000000 | (r<<16) | (gg<<8) | bl
        x1,y1=round(CX+S*A[0]),round(CY-S*A[1])
        x2,y2=round(CX+S*B3[0]),round(CY-S*B3[1])
        x3,y3=round(CX+S*C[0]),round(CY-S*C[1])
        if abs((x2-x1)*(y3-y1)-(x3-x1)*(y2-y1))*0.5<2: continue
        out.append(((A[2]+B3[2]+C[2])/3,x1,y1,x2,y2,x3,y3,col))
    out.sort(key=lambda t:t[0])           # far first
    return [t[1:] for t in out]
vp,vn=build(1),build(-1)
vis=vp if len(vp)>=len(vn) else vn
if len(vis)>CAP: vis=vis[len(vis)-CAP:]   # keep nearest CAP
sys.stderr.write(f"[mk] visible tris streamed={len(vis)} (cap={CAP})\n")

# ================= AVM1 assembler =================
strs=[]
def sid(s):
    if s not in strs: strs.append(s)
    return strs.index(s)
OP=dict(PUSHI=0x01,LDF=0x02,STF=0x03,LDA=0x04,SELF=0x05,WAIT=0x07,
        SEND=0x40,SPAWN=0x41,RET=0x43,TRI=0x47,CLS=0x46)
def isz(i):
    o=i[0]
    if o=='label': return 0
    if o=='PUSHI': return 5
    if o in('LDF','STF','LDA'): return 2
    if o=='SPAWN': return 3
    if o=='SEND': return 4
    return 1
def asm(prog):
    b=bytearray()
    for ins in prog:
        o=ins[0]
        if o=='label': continue
        b.append(OP[o])
        if o=='PUSHI': b+=struct.pack('<i',ins[1])
        elif o in('LDF','STF','LDA'): b.append(ins[1]&0xff)
        elif o=='SPAWN': b+=struct.pack('<H',ins[1])
        elif o=='SEND': b+=struct.pack('<H',sid(ins[1])); b.append(ins[2]&0xff)
    return bytes(b)

DISPLAY_CI, MAKINA_CI = 1, 2          # class indices (0=Main)

# Main.tick(): d=new Display(); m=new Makina(); send m.run(d);
main_tick=asm([('SPAWN',DISPLAY_CI),('STF',0),
               ('SPAWN',MAKINA_CI),('STF',1),
               ('LDF',1),('LDF',0),('SEND','run',1),('RET',)])

# Display.clear(){ cls(); }   Display.tri(a..g){ tri(a,b,c,d,e,f,g); }
disp_clear=asm([('CLS',),('RET',)])
disp_tri  =asm([('LDA',0),('LDA',1),('LDA',2),('LDA',3),('LDA',4),('LDA',5),('LDA',6),
                ('TRI',),('RET',)])

# Makina.run(disp){ d=disp; send d.clear(); send self.c0(); }
mak_run=asm([('LDA',0),('STF',0),('LDF',0),('SEND','clear',0),
             ('SELF',),('SEND','c0',0),('RET',)])
# Makina.cK(){ send d.tri(...) x B; wait(WAITMS); send self.c{K+1}(); }  last -> RET
chunks=[vis[k*B:(k+1)*B] for k in range(NCHUNK)]
mak_c=[]
for k,ch in enumerate(chunks):
    prog=[]
    for (x1,y1,x2,y2,x3,y3,col) in ch:
        prog+=[('LDF',0),('PUSHI',x1),('PUSHI',y1),('PUSHI',x2),('PUSHI',y2),
               ('PUSHI',x3),('PUSHI',y3),('PUSHI',col),('SEND','tri',7)]
    if k<NCHUNK-1 and (k+1)<len(chunks) and chunks[k+1]:
        prog+=[('PUSHI',WAITMS),('WAIT',),('SELF',),('SEND',f'c{k+1}',0)]
    prog+=[('RET',)]
    mak_c.append(asm(prog))

# ---- pack module ----
def u16(v): return struct.pack('<H',v)
def method(name,npar,code): return u16(sid(name))+bytes([npar])+u16(len(code))+code
cls_main=u16(sid('Main'))+u16(2)+u16(1)+method('tick',0,main_tick)
disp_m=method('clear',0,disp_clear)+method('tri',7,disp_tri)
cls_disp=u16(sid('Display'))+u16(0)+u16(2)+disp_m
mak_m=method('run',1,mak_run)
for k in range(NCHUNK): mak_m+=method(f'c{k}',0,mak_c[k])
cls_mak=u16(sid('Makina'))+u16(1)+u16(1+NCHUNK)+mak_m

mod=bytearray(b'AVM1')+u16(len(strs))
# NOTE: strings were interned during asm()/method(); rebuild header now that sid() is fixed
mod=bytearray(b'AVM1'); mod+=u16(len(strs))
for s in strs: sb=s.encode(); mod+=u16(len(sb))+sb
mod+=u16(3)+cls_main+cls_disp+cls_mak

assert 1+NCHUNK<=16 and len(strs)<=64
sys.stderr.write(f"[mk] classes=3 makina_methods={1+NCHUNK} strings={len(strs)} bytes={len(mod)}\n")
open(OUT,'wb').write(mod)

# ---- emit the human-readable AIPL (.abcl) source for the same actor ----
abcl=[]
abcl.append("// MakinaDisplayActor.abcl - actor-to-actor \"Blender display system\" on Xinu.")
abcl.append("// Display = the display-system actor (cls/tri via the kernel op_tri solid fill).")
abcl.append("// Makina  = the 3-D-DATA actor; it STREAMS its %d triangles to Display with `send`."%len(vis))
abcl.append("// Main spawns both and wires them.  Full 24-bit colour: col = 0x1000000 | 0xRRGGBB.")
abcl.append("")
abcl.append("class Main {")
abcl.append("  var d = 0; var m = 0;")
abcl.append("  method tick() { d = new Display(); m = new Makina(); send m.run(d); }")
abcl.append("}")
abcl.append("")
abcl.append("class Display {                 // the Blender display-system actor")
abcl.append("  method clear() { cls(); }")
abcl.append("  method tri(a,b,c,d,e,f,g) { tri(a,b,c,d,e,f,g); }   // -> kernel op_tri (full colour)")
abcl.append("}")
abcl.append("")
abcl.append("class Makina {                  // the 3-D-data actor")
abcl.append("  var d = 0;")
abcl.append("  method run(disp) { d = disp; send d.clear(); send self.c0(); }")
for k,ch in enumerate(chunks):
    abcl.append("  method c%d() {"%k)
    for (x1,y1,x2,y2,x3,y3,col) in ch:
        abcl.append("    send d.tri(%d,%d,%d,%d,%d,%d,%d);"%(x1,y1,x2,y2,x3,y3,col))
    if k<NCHUNK-1 and (k+1)<len(chunks) and chunks[k+1]:
        abcl.append("    wait(%d); send self.c%d();"%(WAITMS,k+1))
    abcl.append("  }")
abcl.append("}")
abcl.append("")
abcl.append("var boot = new Main(); send boot.tick();")
SRC=OUT[:-4]+".abcl" if OUT.endswith(".avm") else OUT+".abcl"
open(SRC,"w").write("\n".join(abcl)+"\n")

print(f"wrote {OUT} ({len(mod)} bytes) + {SRC} ({len(abcl)} lines), streamed {len(vis)} tris via Display actor")
