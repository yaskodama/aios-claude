#!/usr/bin/env python3
"""send_avm_loadvm.py — upload a .avm actor module to Xinu's in-kernel AVM VM
and run it on the "Blender" polygon display.

Protocol (tcp_server.c /actor/loadvm, httpreq buffer 32 KB):
  POST /actor/loadvm?off=<byte>&total=<N>   body = a chunk of the .avm
  GET  /actor/loadvm?go=1&len=<N>[&save=<NAME>]   load + spawn + run -> display

  python3 send_avm_loadvm.py [host] [file.avm] [SAVENAME]
  default host=192.168.3.100  file=/tmp/MakinaGlbActor.avm  (no save)
"""
import sys, time, urllib.request

host = sys.argv[1] if len(sys.argv) > 1 else "192.168.3.100"
path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/MakinaGlbActor.avm"
save = sys.argv[3] if len(sys.argv) > 3 else None
CHUNK = 16384

data = open(path, "rb").read()
n = len(data)
print(f"[loadvm] {path}: {n} bytes -> http://{host}  ({(n+CHUNK-1)//CHUNK} chunks of {CHUNK}B)")


def post_chunk(off, chunk, total):
    req = urllib.request.Request(
        f"http://{host}/actor/loadvm?off={off}&total={total}",
        data=chunk, method="POST",
        headers={"Content-Type": "application/octet-stream"})
    return urllib.request.urlopen(req, timeout=20).read().decode("ascii", "replace").strip()


t0 = time.time()
for off in range(0, n, CHUNK):
    chunk = data[off:off + CHUNK]
    want = f"ok off={off}"
    r = ""
    for attempt in range(5):
        try:
            r = post_chunk(off, chunk, n)
        except Exception as e:
            r = f"<err {e}>"
        if r.startswith(want):
            break
        time.sleep(0.4)
    else:
        sys.exit(f"[loadvm] ABORT: chunk off={off} never acked (last: {r})")
    print(f"  off={off:>8} -> {r}")

print(f"[loadvm] staged {n} bytes in {time.time()-t0:.1f}s. triggering run...")
go = f"http://{host}/actor/loadvm?go=1&len={n}"
if save:
    go += f"&save={save}"
try:
    r = urllib.request.urlopen(go, timeout=120).read().decode("ascii", "replace").strip()
    print(f"[loadvm] {r}")
except Exception as e:
    print(f"[loadvm] go error: {e}")
print("[loadvm] done — the Blender display window should now render the MAKINA-7 actor.")
