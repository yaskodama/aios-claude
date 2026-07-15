"""aipl_dofbot.py —— Yahboom DOFBOT (6DOF) 実機デバイス + TinyML の組込みプリミティブ。

AIPL から実機アームを直接駆動するための最小の口。バックエンドは差替え式:

  DOFBOT_BACKEND=log     (既定) コマンドを標準出力へ。実機が無くても動く。
  DOFBOT_BACKEND=armlib         実機の Raspberry Pi 上で Yahboom の Arm_Lib を叩く。
  DOFBOT_BACKEND=http           DOFBOT_URL のブリッジへ POST（Mac から遠隔駆動）。

実機 API は Yahboom Arm_Lib と同じ名前・同じ引数にしてあるので、`.abcl` 側は
バックエンドを問わず一切書き換えずに済む。

効果(Capability)の割当は aipl_typeck.BUILTIN_EFFECTS 側で行う:

  Arm_serial_servo_write  -> {mut}   アクチュエーション（唯一の駆動権限）
  Arm_serial_servo_read   -> {}      計測のみ（read-only なので効果なし）
  dofbot_camera_grab      -> {}      センサ読取
  tinyml_load             -> {fs}    重みをファイルから読む
  tinyml_infer            -> {ai}    ローカル推論。ai_call と違い net を伴わない
                                     ＝機外へ何も出さないことを型で保証できる。
"""
from __future__ import annotations

import json
import math
import os
import time

# ---------------------------------------------------------------- backend

_SERVO_MIN, _SERVO_MAX = 0.0, 180.0
_NUM_SERVOS = 6


class _Backend:
    """実機が無い環境でも AIPL が完走するよう、状態だけは保持する。"""

    def __init__(self):
        self.angles = [90.0] * (_NUM_SERVOS + 1)   # 1-origin（ID1..ID6）
        self.writes = 0

    def write(self, sid: int, angle: float, ms: int):
        self.angles[sid] = angle
        self.writes += 1

    def read(self, sid: int) -> float:
        return self.angles[sid]


class _LogBackend(_Backend):
    """実機非接続。指令をそのまま出力する（既定）。"""

    def __init__(self, quiet: bool = False):
        super().__init__()
        self.quiet = quiet

    def write(self, sid, angle, ms):
        super().write(sid, angle, ms)
        if not self.quiet:
            print(f"[servo] ID{sid} -> {angle:6.1f}deg in {ms:4d}ms", flush=True)


class _ArmLibBackend(_Backend):
    """DOFBOT の Raspberry Pi 上で動かす場合。実機のバスサーボを直接駆動する。"""

    def __init__(self):
        super().__init__()
        from Arm_Lib import Arm_Device        # 実機にのみ存在
        self.dev = Arm_Device()
        time.sleep(0.1)

    def write(self, sid, angle, ms):
        super().write(sid, angle, ms)
        self.dev.Arm_serial_servo_write(sid, angle, ms)

    def read(self, sid):
        v = self.dev.Arm_serial_servo_read(sid)
        if v is not None:
            self.angles[sid] = float(v)
        return self.angles[sid]


class _HttpBackend(_Backend):
    """Mac から LAN 越しに DOFBOT ブリッジを叩く場合。"""

    def __init__(self, url: str):
        super().__init__()
        self.url = url.rstrip("/")

    def write(self, sid, angle, ms):
        super().write(sid, angle, ms)
        import urllib.request
        body = json.dumps({"id": sid, "angle": angle, "ms": ms}).encode()
        req = urllib.request.Request(f"{self.url}/servo", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=2.0).read()
        except Exception as e:
            print(f"[dofbot] http write 失敗: {e}", flush=True)

    def read(self, sid):
        import urllib.request
        try:
            with urllib.request.urlopen(f"{self.url}/servo/{sid}", timeout=2.0) as r:
                self.angles[sid] = float(json.loads(r.read())["angle"])
        except Exception as e:
            print(f"[dofbot] http read 失敗: {e}", flush=True)
        return self.angles[sid]


_backend = None


def backend():
    global _backend
    if _backend is None:
        kind = os.environ.get("DOFBOT_BACKEND", "log").lower()
        if kind == "armlib":
            _backend = _ArmLibBackend()
        elif kind == "http":
            _backend = _HttpBackend(os.environ.get("DOFBOT_URL", "http://192.168.3.60:8080"))
        else:
            _backend = _LogBackend(quiet=os.environ.get("DOFBOT_QUIET") == "1")
    return _backend


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


# ---------------------------------------------------------------- servo builtins

def b_servo_write(args, frame, interp):
    """Arm_serial_servo_write(id, angle, ms) -> int

    実機のバスサーボ id を angle[deg] へ ms ミリ秒かけて駆動する。
    可動域(0..180)外はクランプし、警告する（実機なら機構を壊す指令なので黙らせない）。
    """
    if len(args) < 2:
        return 0
    sid = int(args[0])
    angle = float(args[1])
    ms = int(args[2]) if len(args) > 2 else 500
    if not (1 <= sid <= _NUM_SERVOS):
        print(f"[servo] 不正な ID: {sid}", flush=True)
        return 0
    c = _clamp(angle, _SERVO_MIN, _SERVO_MAX)
    if abs(c - angle) > 1e-6:
        print(f"[servo] ID{sid} 可動域外 {angle:.1f} -> {c:.1f} にクランプ", flush=True)
    backend().write(sid, c, ms)
    return 1


def b_servo_write6(args, frame, interp):
    """Arm_serial_servo_write6(a1..a6, ms) -> int  —— 6軸を同時に指令する。"""
    if len(args) < 6:
        return 0
    ms = int(args[6]) if len(args) > 6 else 500
    for i in range(6):
        b_servo_write([i + 1, float(args[i]), ms], frame, interp)
    return 1


def b_servo_read(args, frame, interp):
    """Arm_serial_servo_read(id) -> float  —— 現在角の計測（read-only）。"""
    if not args:
        return 0.0
    sid = int(args[0])
    if not (1 <= sid <= _NUM_SERVOS):
        return 0.0
    return float(backend().read(sid))


def b_servo_writes(args, frame, interp):
    """dofbot_servo_writes() -> int  —— 発行済みサーボ指令の総数（ベンチ用）。"""
    return backend().writes


def b_belt_drive(args, frame, interp):
    """dofbot_belt_drive(cmd) -> int  —— コンベアを駆動する。

    cmd: 1=前進（次の部品をストッパまで送る） / 2=排出（ストッパを開けて流す）
         0=停止。作業セルのアクチュエータなので効果は {mut}。
    """
    cmd = int(args[0]) if args else 0
    st = interp.__dict__.setdefault("_dofbot_belt", {"cmd": 0, "n": 0})
    st["cmd"] = cmd
    st["n"] += 1
    if os.environ.get("DOFBOT_QUIET") != "1":
        name = {0: "stop", 1: "feed", 2: "eject"}.get(cmd, str(cmd))
        print(f"[belt ] {name}", flush=True)
    return 1


# ---------------------------------------------------------------- camera

def b_camera_grab(args, frame, interp):
    """dofbot_camera_grab([path]) -> array  —— 手首カメラの 1 フレームを特徴量で返す。

    実機では USB カメラから取り込む。ここでは 3Dシミュレータの手首カメラが
    書き出した実レンダ画像の特徴量(rl/capture_dataset.mjs と同一の前処理)を
    順に読み出す。どちらの場合も「TinyML に渡せる 192 次元の実測ベクトル」。
    """
    path = str(args[0]) if args else os.environ.get("DOFBOT_FRAMES", "")
    st = interp.__dict__.setdefault("_dofbot_frames", {})
    if path not in st:
        try:
            d = json.loads(open(path).read())
            # データセットはクラス順に並んでいるので、そのまま順に返すと最初の
            # 何十フレームも同じ色になる。実ラインの流れ方に合わせて混ぜる。
            order = list(range(len(d["X"])))
            import random as _r
            _r.Random(int(os.environ.get("DOFBOT_FRAME_SEED", "20260715"))).shuffle(order)
            st[path] = {"X": d["X"], "y": d.get("y", []), "order": order, "i": 0}
        except Exception as e:
            print(f"[camera] フレーム源を開けない ({path}): {e}", flush=True)
            st[path] = {"X": [], "y": [], "order": [], "i": 0}
    s = st[path]
    if not s["X"]:
        return []
    i = s["order"][s["i"] % len(s["order"])]
    s["i"] += 1
    s["last_label"] = s["y"][i] if i < len(s["y"]) else -1
    return list(s["X"][i])


def b_camera_truth(args, frame, interp):
    """dofbot_camera_truth([path]) -> int  —— 直前フレームの正解ラベル（答え合わせ用）。"""
    path = str(args[0]) if args else os.environ.get("DOFBOT_FRAMES", "")
    st = interp.__dict__.get("_dofbot_frames", {})
    return int(st.get(path, {}).get("last_label", -1))


# ---------------------------------------------------------------- TinyML

def b_tinyml_load(args, frame, interp):
    """tinyml_load(path) -> model  —— 学習済みの小型NNを読む（fs 効果）。"""
    if not args:
        return None
    try:
        m = json.loads(open(str(args[0])).read())
    except Exception as e:
        print(f"[tinyml] モデルを読めない: {e}", flush=True)
        return None
    return m


def b_tinyml_infer(args, frame, interp):
    """tinyml_infer(model, features) -> array[float]  —— クラス確率を返す。

    192→H(tanh)→3(softmax) を素で計算する。外部へ一切出ないローカル推論なので
    効果は {ai} のみ（ai_call 系の {ai, net} と対比される）。
    """
    if len(args) < 2:
        return []
    m, x = args[0], args[1]
    if not isinstance(m, dict) or not isinstance(x, list) or not x:
        return []
    nf, H = int(m["nfeat"]), int(m["hidden"])
    w1, b1, w2, b2 = m["w1"], m["b1"], m["w2"], m["b2"]
    nc = len(b2)
    h = []
    for j in range(H):
        s = b1[j]
        base = j * nf
        for i in range(min(nf, len(x))):
            s += w1[base + i] * x[i]
        h.append(math.tanh(s))
    o = []
    for k in range(nc):
        s = b2[k]
        base = k * H
        for j in range(H):
            s += w2[base + j] * h[j]
        o.append(s)
    mx = max(o)
    ex = [math.exp(v - mx) for v in o]
    t = sum(ex)
    return [v / t for v in ex]


def b_tinyml_argmax(args, frame, interp):
    """tinyml_argmax(probs) -> int  —— 最尤クラスの添字。"""
    p = args[0] if args else []
    if not isinstance(p, list) or not p:
        return -1
    return max(range(len(p)), key=lambda k: p[k])


# ---------------------------------------------------------------- registry

SIGNATURES = {
    # 実機 Arm_Lib と同じく ms は必須（シグネチャの後置 [, x] は処理系が
    # optional として解釈しない ―― 先頭の [x,] 形式のみ対応 ―― ため、
    # ここで省略可能に見せると arity エラーになる）。
    "Arm_serial_servo_write":  "function(id:int, angle:int|float, ms:int) -> int",
    "Arm_serial_servo_write6": "function(int|float+) -> int",
    "Arm_serial_servo_read":   "function(id:int) -> float",
    "dofbot_servo_writes":     "function() -> int",
    "dofbot_belt_drive":       "function(cmd:int) -> int",
    "dofbot_camera_grab":      "function([path:string]) -> array",
    "dofbot_camera_truth":     "function([path:string]) -> int",
    "tinyml_load":             "function(path:string) -> any",
    "tinyml_infer":            "function(model:any, features:array) -> array",
    "tinyml_argmax":           "function(probs:array) -> int",
}

BUILTINS = {
    "Arm_serial_servo_write":  b_servo_write,
    "Arm_serial_servo_write6": b_servo_write6,
    "Arm_serial_servo_read":   b_servo_read,
    "dofbot_servo_writes":     b_servo_writes,
    "dofbot_belt_drive":       b_belt_drive,
    "dofbot_camera_grab":      b_camera_grab,
    "dofbot_camera_truth":     b_camera_truth,
    "tinyml_load":             b_tinyml_load,
    "tinyml_infer":            b_tinyml_infer,
    "tinyml_argmax":           b_tinyml_argmax,
}

# 効果推論用。aipl_typeck.BUILTIN_EFFECTS へマージされる。
EFFECTS = {
    "Arm_serial_servo_write":  {"mut"},
    "Arm_serial_servo_write6": {"mut"},
    "Arm_serial_servo_read":   set(),
    "dofbot_servo_writes":     set(),
    "dofbot_belt_drive":       {"mut"},   # コンベアも作業セルのアクチュエータ
    "dofbot_camera_grab":      set(),
    "dofbot_camera_truth":     set(),
    "tinyml_load":             {"fs"},
    "tinyml_infer":            {"ai"},
    "tinyml_argmax":           set(),
}
