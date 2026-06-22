#!/usr/bin/env python3
"""avm_blender_compare_gui.py — the "Blender display system", side-by-side.

LEFT  : a .glb rendered directly (real Z-buffer, smooth shading).
RIGHT : a .avm actor module run through the SAME AVM bytecode VM the Xinu kernel
        uses (Main spawns Display + Makina; Makina streams tri messages).

Both panels go through the display system's exact pixel path (render_* ->
fb_to_ppm, with this Pi4 framebuffer's R/B swap), so what you see is what the
kernel's Blender display system shows.  Buttons: RELOAD / SPIN / STOP / QUIT.

  python3 avm_blender_compare_gui.py [model.glb] [actor.avm]
"""
import sys, os, math, tempfile
import tkinter as tk
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import avm_blender_gui as g

GLB = sys.argv[1] if len(sys.argv) > 1 else "/Users/kodamay/projects/milky-character/makina_preview.glb"
AVM = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "MakinaDisplayActor.avm")
W, H = g.W, g.H


def fb_to_photo(fb, idx):
    fp = os.path.join(tempfile.gettempdir(), "_cmp_%d.ppm" % idx)
    g.fb_to_ppm(fb, fp)
    return tk.PhotoImage(file=fp)


class Compare:
    def __init__(self, root):
        self.root = root
        root.title("AIPL Blender Display System — GLB vs AVM")
        bar = tk.Frame(root, bg="#222"); bar.pack(side=tk.TOP, fill=tk.X)
        mk = lambda t, c: tk.Button(bar, text=t, width=7, command=c).pack(side=tk.LEFT, padx=3, pady=4)
        mk("RELOAD", self.reload); mk("SPIN", self.spin); mk("STOP", self.stop); mk("QUIT", root.destroy)
        self.status = tk.Label(bar, text="loading…", bg="#222", fg="#ddd"); self.status.pack(side=tk.LEFT, padx=10)

        body = tk.Frame(root, bg="#06100a"); body.pack(fill=tk.BOTH, expand=True)
        lf = tk.Frame(body, bg="#06100a"); lf.pack(side=tk.LEFT)
        rf = tk.Frame(body, bg="#06100a"); rf.pack(side=tk.LEFT)
        tk.Label(lf, text="GLB DIRECT  (Z-buffer)", bg="#06100a", fg="#cfe8ff",
                 font=("Helvetica", 13, "bold")).pack()
        tk.Label(rf, text="AVM ACTOR  (kernel VM)", bg="#06100a", fg="#ffd890",
                 font=("Helvetica", 13, "bold")).pack()
        self.cL = tk.Canvas(lf, width=W, height=H, bg="#06100a", highlightthickness=0); self.cL.pack()
        self.cR = tk.Canvas(rf, width=W, height=H, bg="#06100a", highlightthickness=0); self.cR.pack()
        self.imL = self.cL.create_image(0, 0, anchor=tk.NW)
        self.imR = self.cR.create_image(0, 0, anchor=tk.NW)

        self.yaw, self.pitch = 0.55, 0.16
        self.spinning = False; self._job = None
        root.after(50, self.reload)

    def reload(self):
        self.status.config(text="GLB: loading %s" % os.path.basename(GLB)); self.root.update()
        self.glb_tris = g.load_glb(GLB)
        self.status.config(text="AVM: running VM on %s" % os.path.basename(AVM)); self.root.update()
        self.avm_tris = g.load_avm(AVM)
        # AVM is camera-baked; render once.
        self.photoR = fb_to_photo(g.render_avm(self.avm_tris), 1)
        self.cR.itemconfig(self.imR, image=self.photoR)
        self.render_glb()
        self.status.config(text="GLB %d tris  |  AVM %d tris  (display-system pixel path)"
                            % (len(self.glb_tris), len(self.avm_tris)))

    def render_glb(self, fast=False):
        ss = 1 if fast else 2
        fb = g.render_glb(self.glb_tris, self.yaw, self.pitch, ss, not fast, False)
        self.photoL = fb_to_photo(fb, 0)
        self.cL.itemconfig(self.imL, image=self.photoL)

    def spin(self):
        if self.spinning: return
        self.spinning = True; self._tick()

    def _tick(self):
        if not self.spinning: return
        self.yaw += 0.18
        self.render_glb(fast=True)
        self._job = self.root.after(40, self._tick)

    def stop(self):
        self.spinning = False
        if self._job: self.root.after_cancel(self._job); self._job = None
        self.render_glb(fast=False)
        self.status.config(text="STOP")


def main():
    root = tk.Tk()
    Compare(root)
    root.mainloop()


if __name__ == "__main__":
    main()
