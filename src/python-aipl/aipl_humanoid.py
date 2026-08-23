"""aipl_humanoid.py —— 人型ロボット（Unitree G1 / 23 DOF）実機デバイスの組込みプリミティブ。

AIPL から二足歩行ロボットの関節を直接駆動するための最小の口。aipl_dofbot.py と
同じ構えで、バックエンドは環境変数で差替え式:

  G1_BACKEND=log     (既定) 指令を標準出力へ。実機が無くても `.abcl` は完走する。
  G1_BACKEND=sdk            G1 の車載 PC 上で unitree_sdk2py を叩く（実機駆動）。
  G1_BACKEND=http           G1_URL のブリッジへ POST（LAN 越しに駆動）。

関節 ID は G1 の SDK と同じ並び:
  1..6 左脚（股ピッチ/股ロール/股ヨー/膝/足首ピッチ/足首ロール）
  7..12 右脚（同じ）  13 腰ヨー
  14..18 左腕（肩ピッチ/肩ロール/肩ヨー/肘/手首ロール）  19..23 右腕（同じ）

効果(Capability)の割当は aipl_typeck.BUILTIN_EFFECTS 側で行う:

  g1_joint_write     -> {act}  関節の駆動（唯一の駆動権限）
  g1_joint_write_all -> {act}  23 軸同時指令
  g1_joint_read      -> {}     エンコーダ計測（read-only なので効果なし）
  g1_imu_read        -> {}     体幹 IMU の読み取り
  g1_foot_force      -> {}     足裏 6 軸力覚の読み取り
  g1_joint_writes    -> {}     発行済み指令数のカウンタ（駆動しない）

■ log バックエンドが返す「計測値」について
  実機が無いときも FootSensor / ImuActor が意味のある値を返せるよう、
  log バックエンドは指令された 23 関節角から **順運動学を実際に解いて**
  骨盤から見た左右の足裏高さを求め、低い側に荷重を寄せる。乱数や定数では
  ない（ただし浮遊基底なので絶対位置・絶対方位は求まらない。IMU のヨーは
  「両足の向きに対する骨盤の相対ヨー」を返す。roll/pitch は歩容が骨盤を
  水平に保つ前提で 0 を返す ―― ここは実機の IMU に置き換わる部分）。
"""
from __future__ import annotations

import math
import os
import urllib.request

_NUM_JOINTS = 23

# ---------------------------------------------------------------- 機体寸法
# src/layout.js の BODY と同じ値。順運動学（接地判定）に使う。
_THIGH = 0.300
_SHANK = 0.300
_ANKLE_Y = 0.040
_HIP_Z = 0.075
_MASS = 35.0
_G = 9.80665

# 可動域 [rad]。src/layout.js の JOINTS と同じ（G1 の公表可動域を本実装の
# 符号規約へ割り当てたもの）。範囲外の指令はクランプして警告する。
_LIMITS = {
    1: (-2.35, 3.05), 2: (-0.26, 2.53), 3: (-2.75, 2.75),
    4: (-2.88, 0.33), 5: (-0.68, 0.73), 6: (-0.26, 0.26),
    7: (-2.35, 3.05), 8: (-2.53, 0.26), 9: (-2.75, 2.75),
    10: (-2.88, 0.33), 11: (-0.68, 0.73), 12: (-0.26, 0.26),
    13: (-2.62, 2.62),
    14: (-2.97, 2.97), 15: (-1.59, 2.25), 16: (-2.62, 2.62),
    17: (-1.05, 2.09), 18: (-1.97, 1.97),
    19: (-2.97, 2.97), 20: (-2.25, 1.59), 21: (-2.62, 2.62),
    22: (-1.05, 2.09), 23: (-1.97, 1.97),
}
_NAMES = {
    1: "L_hip_pitch", 2: "L_hip_roll", 3: "L_hip_yaw", 4: "L_knee",
    5: "L_ankle_pitch", 6: "L_ankle_roll",
    7: "R_hip_pitch", 8: "R_hip_roll", 9: "R_hip_yaw", 10: "R_knee",
    11: "R_ankle_pitch", 12: "R_ankle_roll",
    13: "waist_yaw",
    14: "L_sho_pitch", 15: "L_sho_roll", 16: "L_sho_yaw", 17: "L_elbow", 18: "L_wrist_roll",
    19: "R_sho_pitch", 20: "R_sho_roll", 21: "R_sho_yaw", 22: "R_elbow", 23: "R_wrist_roll",
}


# ---------------------------------------------------------------- 3x3 回転
def _rx(a):
    c, s = math.cos(a), math.sin(a)
    return ((1, 0, 0), (0, c, -s), (0, s, c))


def _ry(a):
    c, s = math.cos(a), math.sin(a)
    return ((c, 0, s), (0, 1, 0), (-s, 0, c))


def _rz(a):
    c, s = math.cos(a), math.sin(a)
    return ((c, -s, 0), (s, c, 0), (0, 0, 1))


def _mul(A, B):
    return tuple(tuple(sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _mulv(M, v):
    return tuple(sum(M[i][k] * v[k] for k in range(3)) for i in range(3))


def _leg_sole(angles, base, side_sign):
    """骨盤原点から見た足裏中心の位置と足の向き（順運動学）。

    関節順は実機 G1 と同じ pitch → roll → yaw → 膝 → 足首ピッチ → 足首ロール。
    src/kinematics.js の legFK と同一の合成。
    """
    hp, hr, hy, kn, ap, ar = (angles[base + i] for i in range(6))
    hip = (0.0, 0.0, side_sign * _HIP_Z)
    R = _mul(_rz(hp), _mul(_rx(hr), _ry(hy)))
    knee = tuple(hip[i] + _mulv(R, (0.0, -_THIGH, 0.0))[i] for i in range(3))
    Rk = _mul(R, _rz(kn))
    ankle = tuple(knee[i] + _mulv(Rk, (0.0, -_SHANK, 0.0))[i] for i in range(3))
    Rf = _mul(Rk, _mul(_rz(ap), _rx(ar)))
    sole = tuple(ankle[i] + _mulv(Rf, (0.0, -_ANKLE_Y, 0.0))[i] for i in range(3))
    fwd = _mulv(Rf, (1.0, 0.0, 0.0))
    return sole, math.atan2(-fwd[2], fwd[0])


# ---------------------------------------------------------------- backend
class _Backend:
    """実機が無い環境でも AIPL が完走するよう、状態だけは保持する。"""

    def __init__(self):
        self.angles = [0.0] * (_NUM_JOINTS + 1)   # 1-origin（ID1..ID23）
        self.writes = 0

    def write(self, jid: int, rad: float, ms: int):
        self.angles[jid] = rad
        self.writes += 1

    def read(self, jid: int) -> float:
        return self.angles[jid]

    # ---- 指令角から解く「計測値」（実機では IMU / 力覚センサが返す） ----
    def soles(self):
        return (_leg_sole(self.angles, 1, -1.0), _leg_sole(self.angles, 7, +1.0))

    def foot_force(self, side: int) -> float:
        (lp, _ly), (rp, _ry_) = self.soles()
        total = _MASS * _G
        d = lp[1] - rp[1]                        # 左足裏 − 右足裏 の高さ差
        band = 0.004                             # この幅の中は両脚で分担する
        if d < -band:
            share_l = 1.0
        elif d > band:
            share_l = 0.0
        else:
            share_l = 0.5 - d / (2.0 * band)
        return total * (share_l if side == 0 else (1.0 - share_l))

    def imu(self):
        (_lp, lyaw), (_rp, ryaw) = self.soles()
        # 骨盤は歩容が水平に保つ前提。ヨーは両足の向きに対する相対値。
        yaw = -math.atan2(math.sin(lyaw) + math.sin(ryaw), math.cos(lyaw) + math.cos(ryaw))
        return [0.0, 0.0, yaw, 0.0, 0.0, 0.0]


class _LogBackend(_Backend):
    """実機非接続。指令をそのまま出力する（既定）。"""

    def __init__(self, quiet: bool = False):
        super().__init__()
        self.quiet = quiet

    def write(self, jid, rad, ms):
        super().write(jid, rad, ms)
        if not self.quiet:
            print(f"[joint] ID{jid:2d} {_NAMES[jid]:<14s} -> {math.degrees(rad):7.2f}deg "
                  f"in {ms:3d}ms", flush=True)


class _SdkBackend(_Backend):
    """G1 の車載 PC 上で unitree_sdk2py を叩く（実機駆動）。"""

    def __init__(self):
        super().__init__()
        self.pub = None
        try:
            from unitree_sdk2py.core.channel import ChannelPublisher, ChannelFactoryInitialize
            from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_
            ChannelFactoryInitialize(0, os.environ.get("G1_IFACE", "eth0"))
            self.pub = ChannelPublisher("rt/lowcmd", LowCmd_)
            self.pub.Init()
            self._LowCmd = LowCmd_
            print("[g1] unitree_sdk2py に接続しました", flush=True)
        except Exception as e:
            print(f"[g1] unitree_sdk2py 初期化失敗（log にフォールバック）: {e}", flush=True)

    def write(self, jid, rad, ms):
        super().write(jid, rad, ms)
        if self.pub is None:
            return
        try:
            cmd = self._LowCmd()
            m = cmd.motor_cmd[jid - 1]
            m.mode, m.q, m.dq = 1, float(rad), 0.0
            m.kp, m.kd, m.tau = float(os.environ.get("G1_KP", "60")), \
                float(os.environ.get("G1_KD", "1.5")), 0.0
            self.pub.Write(cmd)
        except Exception as e:
            print(f"[g1] sdk write 失敗: {e}", flush=True)


class _HttpBackend(_Backend):
    """LAN 越しのブリッジへ POST する。"""

    def __init__(self, url: str):
        super().__init__()
        self.url = url.rstrip("/")

    def write(self, jid, rad, ms):
        super().write(jid, rad, ms)
        body = f'{{"id":{jid},"rad":{rad},"ms":{ms}}}'.encode()
        try:
            req = urllib.request.Request(self.url + "/joint", data=body,
                                        headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=1.0).read()
        except Exception as e:
            print(f"[g1] http write 失敗: {e}", flush=True)

    def read(self, jid):
        try:
            with urllib.request.urlopen(f"{self.url}/joint/{jid}", timeout=1.0) as r:
                return float(r.read().decode().strip())
        except Exception as e:
            print(f"[g1] http read 失敗: {e}", flush=True)
        return self.angles[jid]


_backend = None


def backend():
    global _backend
    if _backend is None:
        kind = os.environ.get("G1_BACKEND", "log").lower()
        if kind == "sdk":
            _backend = _SdkBackend()
        elif kind == "http":
            _backend = _HttpBackend(os.environ.get("G1_URL", "http://192.168.123.161:8080"))
        else:
            _backend = _LogBackend(quiet=os.environ.get("G1_QUIET") == "1")
    return _backend


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


# ---------------------------------------------------------------- 関節 builtins

def b_joint_write(args, frame, interp):
    """g1_joint_write(id, rad, ms) -> int

    関節 id を rad[ラジアン] へ ms ミリ秒かけて駆動する。可動域外はクランプし、
    警告する（実機なら機構を壊す指令なので黙らせない）。
    """
    if len(args) < 2:
        return 0
    jid = int(args[0])
    rad = float(args[1])
    ms = int(args[2]) if len(args) > 2 else 20
    if not (1 <= jid <= _NUM_JOINTS):
        print(f"[joint] 不正な ID: {jid}", flush=True)
        return 0
    lo, hi = _LIMITS[jid]
    c = _clamp(rad, lo, hi)
    if abs(c - rad) > 1e-6:
        print(f"[joint] ID{jid} {_NAMES[jid]} 可動域外 "
              f"{math.degrees(rad):.2f} -> {math.degrees(c):.2f} deg にクランプ", flush=True)
    backend().write(jid, c, ms)
    return 1


def b_joint_write_all(args, frame, interp):
    """g1_joint_write_all(q, ms) -> int  —— 23 軸を同時に指令する。"""
    if not args:
        return 0
    q = args[0]
    ms = int(args[1]) if len(args) > 1 else 20
    n = min(_NUM_JOINTS, len(q))
    for i in range(n):
        b_joint_write([i + 1, float(q[i]), ms], frame, interp)
    return 1


def b_joint_read(args, frame, interp):
    """g1_joint_read(id) -> float  —— エンコーダの現在角 [rad]（read-only）。"""
    if not args:
        return 0.0
    jid = int(args[0])
    if not (1 <= jid <= _NUM_JOINTS):
        return 0.0
    return float(backend().read(jid))


def b_joint_writes(args, frame, interp):
    """g1_joint_writes() -> int  —— 発行済み関節指令の総数（ベンチ用）。"""
    return backend().writes


def b_imu_read(args, frame, interp):
    """g1_imu_read() -> array  —— 体幹 IMU。[roll, pitch, yaw, wx, wy, wz]。"""
    return backend().imu()


def b_foot_force(args, frame, interp):
    """g1_foot_force(side) -> float  —— 足裏 6 軸力覚の鉛直荷重 [N]。side: 0=左 1=右。"""
    side = int(args[0]) if args else 0
    return float(backend().foot_force(side))


# ---------------------------------------------------------------- registry

SIGNATURES = {
    # ms は必須（シグネチャの後置 [, x] は処理系が optional として解釈しないため、
    # 省略可能に見せると arity エラーになる。aipl_dofbot.py と同じ制約）。
    "g1_joint_write":     "function(id:int, rad:int|float, ms:int) -> int",
    "g1_joint_write_all": "function(q:array, ms:int) -> int",
    "g1_joint_read":      "function(id:int) -> float",
    "g1_joint_writes":    "function() -> int",
    "g1_imu_read":        "function() -> array",
    "g1_foot_force":      "function(side:int) -> float",
}

BUILTINS = {
    "g1_joint_write":     b_joint_write,
    "g1_joint_write_all": b_joint_write_all,
    "g1_joint_read":      b_joint_read,
    "g1_joint_writes":    b_joint_writes,
    "g1_imu_read":        b_imu_read,
    "g1_foot_force":      b_foot_force,
}

# 効果推論用。aipl_typeck.BUILTIN_EFFECTS へマージされる。
#
# act と mut を分ける理由は aipl_dofbot.py と同じ:
#   mut は「自分の状態を書く」、act は「外部世界へ作用する」。
#   act を持つ → その機器に繋がったノードに限定、同時に厳密に 1 つだけ
#                （二重駆動は物理的に危険。人型では転倒に直結する）
#   mut のみ   → どこでも可、複製も可
# 二足歩行では関節の二重駆動が即座に転倒を招くので、act の排他性が
# DOFBOT より強い意味を持つ。
EFFECTS = {
    "g1_joint_write":     {"act"},   # 関節の駆動 = 唯一の駆動権限
    "g1_joint_write_all": {"act"},
    "g1_joint_read":      set(),     # 計測のみ
    "g1_joint_writes":    set(),     # 発行済み指令数を返すカウンタ。駆動しない
    "g1_imu_read":        set(),     # 体幹 IMU の読み取り
    "g1_foot_force":      set(),     # 足裏力覚の読み取り
}
