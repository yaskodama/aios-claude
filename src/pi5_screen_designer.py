"""Pi 5 Xinu screen layout designer + serial control bridge.

The Raspberry Pi 5 running bare-metal Xinu has NO working network (the BCM2712
GENET/RP1 path is unbrought-up and the GIC is unreachable with the MMU off), so
unlike the Pi 3 / Pi 4 designers — which drive the kernel over WiFi/HTTP — this
one talks to the Pi 5 over its 3-pin DEBUG UART (0x107D001000) via the Mac's
USB-serial adapter (/dev/cu.usbserial-*).

Routes:
    GET  /                  the drag/resize window designer (1920x1080 desktop)
    GET  /api/windows       the Pi 5 desktop's 6 windows (id = wm_add order)
    POST /api/send          {windows:[{id,x,y,w,h}]} -> serial move/resize cmds
    POST /api/key           {text:"..."} or {key:"\\n"} -> keystrokes to the
                            focused Shell (UART) window

Wire protocol written to the Pi 5 (parsed by serial_io_tick in loader/main.c):
    0x1D 'M' id x y \\n   move window <id> to (x,y)
    0x1D 'R' id w h  \\n   resize window <id> to w x h
    any other byte        keystroke into the Shell (UART) window

Run:  python3 src/pi5_screen_designer.py        # http://127.0.0.1:8901/
"""

from __future__ import annotations

import glob
import json
import os
import sys
import termios
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PI5_DESIGNER_PORT", "8901"))

# The 6 windows the Pi 5 kernel registers (wm_add order == id), with their
# default 1920x1080 geometry from loader/main.c.  The designer starts here and
# Reload restores these (the kernel has no read-back over serial yet).
PI5_WINDOWS = [
    {"id": 0, "name": "Xinu Pi5 (banner)", "x": 0,    "y": 0,   "w": 1920, "h": 28},
    {"id": 1, "name": "System status",     "x": 772,  "y": 44,  "w": 560,  "h": 500},
    {"id": 2, "name": "VFS tree",          "x": 1344, "y": 44,  "w": 572,  "h": 700},
    {"id": 3, "name": "Memory",            "x": 772,  "y": 556, "w": 560,  "h": 518},
    {"id": 4, "name": "Shell (UART)",      "x": 0,    "y": 44,  "w": 760,  "h": 1030},
    {"id": 5, "name": "Soft keyboard",     "x": 1344, "y": 756, "w": 572,  "h": 318},
]


def _serial_dev() -> str | None:
    devs = sorted(glob.glob("/dev/cu.usbserial-*")) + sorted(glob.glob("/dev/cu.usbmodem*"))
    return devs[0] if devs else None


def _serial_write(data: bytes) -> tuple[bool, str]:
    dev = _serial_dev()
    if not dev:
        return False, "no /dev/cu.usbserial-* found (plug in the Pi 5 debug-UART adapter)"
    try:
        fd = os.open(dev, os.O_WRONLY | os.O_NOCTTY)
        try:
            a = termios.tcgetattr(fd)
            a[4] = a[5] = termios.B115200
            a[2] = (a[2] & ~termios.PARENB & ~termios.CSTOPB & ~termios.CSIZE) \
                   | termios.CS8 | termios.CREAD | termios.CLOCAL
            termios.tcsetattr(fd, termios.TCSANOW, a)
            os.write(fd, data)
            termios.tcdrain(fd)
        finally:
            os.close(fd)
        return True, "%s <- %d bytes" % (dev, len(data))
    except Exception as e:  # noqa: BLE001
        return False, "serial write failed: %s" % e


def _layout_bytes(windows) -> bytes:
    out = bytearray()
    for w in windows:
        try:
            i = int(w["id"]); x = int(w["x"]); y = int(w["y"])
            ww = int(w["w"]); hh = int(w["h"])
        except (KeyError, ValueError, TypeError):
            continue
        out += b"\x1dR%d %d %d\n" % (i, ww, hh)   # resize first, then place
        out += b"\x1dM%d %d %d\n" % (i, x, y)
    return bytes(out)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, "application/json", json.dumps(obj).encode("utf-8"))

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:  # noqa: BLE001
            return {}

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self._send(200, "text/html; charset=utf-8", _HTML.encode("utf-8"))
        elif self.path.startswith("/api/windows"):
            self._json({"windows": PI5_WINDOWS, "serial": _serial_dev()})
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        if self.path.startswith("/api/send"):
            d = self._read_json()
            data = _layout_bytes(d.get("windows", []))
            ok, msg = _serial_write(data)
            self._json({"ok": ok, "log": msg, "wire": data.decode("latin-1")})
        elif self.path.startswith("/api/key"):
            d = self._read_json()
            txt = d.get("text")
            if txt is None:
                txt = d.get("key", "")
            # never let a stray 0x1D be typed (it would be read as a command)
            payload = str(txt).replace("\x1d", "").encode("utf-8")
            ok, msg = _serial_write(payload)
            self._json({"ok": ok, "log": msg, "sent": len(payload)})
        else:
            self.send_error(404, "Not Found")


_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Py-I &mdash; Pi5 Xinu screen designer</title>
<style>
 body{font-family:ui-monospace,Menlo,Consolas,monospace;background:#0b0f14;color:#d8dee9;margin:0;padding:16px}
 h2{margin:0 0 6px} .muted{color:#8aa;font-size:13px}
 #bar{margin:8px 0}
 button{font:inherit;background:#243;color:#d8ffd8;border:1px solid #4a6;border-radius:6px;padding:6px 14px;cursor:pointer}
 button.send{background:#354a7a;color:#dde8ff;border-color:#6a8}
 #desk{position:relative;background:#102035;border:1px solid #355;margin-top:10px}
 .win{position:absolute;background:rgba(40,60,90,0.85);border:1px solid #8be;border-radius:3px;
      box-sizing:border-box;overflow:hidden;cursor:move;font-size:11px}
 .win.sel{outline:2px solid #ffd24d}
 .win .t{background:#205070;color:#fff;padding:1px 5px;white-space:nowrap;overflow:hidden}
 .win .sz{padding:2px 5px;color:#bcd;font-size:10px;pointer-events:none}
 .win .h{position:absolute;right:0;bottom:0;width:12px;height:12px;background:#8be;cursor:nwse-resize}
 #kb{margin-top:10px}
 input{font:inherit;background:#11161d;color:#d8dee9;border:1px solid #3b4757;border-radius:5px;padding:5px 8px;width:360px}
 #log{white-space:pre-wrap;background:#0d1117;border:1px solid #333;border-radius:6px;
      padding:8px;margin-top:10px;max-height:150px;overflow:auto;font-size:12px}
</style></head><body>
<h2>Pi5 Xinu screen designer <span class=muted>(serial &rarr; debug UART, host = bare-metal Pi 5)</span></h2>
<div class=muted>Drag a window to move it; drag the corner handle to resize. Frame = the Pi 5 1920&times;1080 HDMI desktop.
 送信 ships the geometry to the Pi 5 over the 3-pin debug UART. Click a window to select it (yellow), pick <b>Shell (UART)</b>,
 then type below to send keystrokes into that bare-metal window.</div>
<div id=bar>
  <button onclick="reload()">&#8635; 既定に戻す (Reload)</button>
  <button class=send onclick="send()">送信 (Send) &rarr;</button>
  <span id=status class=muted></span>
</div>
<div id=desk></div>
<div id=kb>
  <span class=muted>Selected: <b id=selname>(none)</b> &nbsp; keys&rarr;</span>
  <input id=keyin placeholder="type here, Enter sends a line to the Shell window" autocomplete=off>
  <button onclick="sendKeys()">send keys</button>
</div>
<div id=log class=muted>ready.</div>
<script>
const DW=1920, DH=1080, SCALE=0.45;
let wins=[], sel=-1;
const desk=document.getElementById('desk'), status=document.getElementById('status'),
      logEl=document.getElementById('log'), selname=document.getElementById('selname'),
      keyin=document.getElementById('keyin');
desk.style.width=(DW*SCALE)+'px'; desk.style.height=(DH*SCALE)+'px';
function log(s){ logEl.textContent=s; }
function render(){
  desk.innerHTML='';
  wins.forEach((w,idx)=>{
    const d=document.createElement('div'); d.className='win'+(idx===sel?' sel':''); d.dataset.i=idx;
    d.style.left=(w.x*SCALE)+'px'; d.style.top=(w.y*SCALE)+'px';
    d.style.width=(w.w*SCALE)+'px'; d.style.height=(w.h*SCALE)+'px';
    const t=document.createElement('div'); t.className='t'; t.textContent=w.id+': '+w.name; d.appendChild(t);
    const sz=document.createElement('div'); sz.className='sz'; sz.textContent=w.w+'x'+w.h+' ('+w.x+','+w.y+')'; d.appendChild(sz);
    const h=document.createElement('div'); h.className='h'; d.appendChild(h);
    desk.appendChild(d);
    d.addEventListener('mousedown', e=>{ select(idx); if(e.target===h) startResize(e,idx); else startMove(e,idx); });
  });
}
function select(idx){ sel=idx; selname.textContent = idx>=0 ? wins[idx].name : '(none)'; render(); }
function startMove(e,idx){ e.preventDefault();
  const w=wins[idx], sx=e.clientX, sy=e.clientY, ox=w.x, oy=w.y;
  function mv(ev){ w.x=Math.max(0,Math.round(ox+(ev.clientX-sx)/SCALE)); w.y=Math.max(0,Math.round(oy+(ev.clientY-sy)/SCALE)); render(); }
  function up(){ document.removeEventListener('mousemove',mv); document.removeEventListener('mouseup',up); }
  document.addEventListener('mousemove',mv); document.addEventListener('mouseup',up);
}
function startResize(e,idx){ e.preventDefault(); e.stopPropagation();
  const w=wins[idx], sx=e.clientX, sy=e.clientY, ow=w.w, oh=w.h;
  function mv(ev){ w.w=Math.max(40,Math.round(ow+(ev.clientX-sx)/SCALE)); w.h=Math.max(24,Math.round(oh+(ev.clientY-sy)/SCALE)); render(); }
  function up(){ document.removeEventListener('mousemove',mv); document.removeEventListener('mouseup',up); }
  document.addEventListener('mousemove',mv); document.addEventListener('mouseup',up);
}
async function reload(){
  status.textContent='loading...';
  try{ const r=await fetch('/api/windows'); const j=await r.json();
    wins=j.windows||[]; status.textContent=wins.length+' windows'+(j.serial?(' · '+j.serial):' · NO serial');
    log(j.serial?('serial: '+j.serial):'no /dev/cu.usbserial-* — plug in the debug-UART adapter'); render();
  }catch(e){ log('reload failed: '+e); }
}
async function send(){
  status.textContent='sending (serial)...';
  const payload={windows:wins.map(w=>({id:w.id,x:w.x,y:w.y,w:w.w,h:w.h}))};
  try{ const r=await fetch('/api/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const j=await r.json(); status.textContent=j.ok?'sent ✓':'send error';
    log('--- wire (to Pi5 UART) ---\\n'+(j.wire||'')+'\\n'+(j.log||''));
  }catch(e){ log('send failed: '+e); }
}
async function sendKeys(){
  const t=keyin.value; if(!t){ return; }
  try{ const r=await fetch('/api/key',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:t+"\\n"})});
    const j=await r.json(); log('keys sent ('+j.sent+' bytes): '+JSON.stringify(t)+'\\n'+(j.log||'')); keyin.value='';
  }catch(e){ log('key send failed: '+e); }
}
keyin.addEventListener('keydown', e=>{ if(e.key==='Enter'){ e.preventDefault(); sendKeys(); } });
reload();
</script></body></html>"""


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    dev = _serial_dev() or "(none yet — plug in the adapter)"
    print("Pi5 screen designer on http://127.0.0.1:%d/  serial=%s" % (PORT, dev),
          file=sys.stderr)
    srv.serve_forever()


if __name__ == "__main__":
    main()
