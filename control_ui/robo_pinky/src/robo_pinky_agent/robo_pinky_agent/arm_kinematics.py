"""OpenMANIPULATOR-X 정·역기구학.

관절 원점은 `robo_pinky_description/urdf/omx.urdf.xacro`와 같다(ROBOTIS
open_manipulator_x 실기 값).

    link1 원점 → joint1  : (0.012, 0, 0)      z축 회전
    joint1     → joint2  : (0, 0, 0.0595)     y축 회전 (어깨)
    joint2     → joint3  : (0.024, 0, 0.128)  y축 회전 (팔꿈치)
    joint3     → joint4  : (0.124, 0, 0)      y축 회전 (손목)
    joint4     → EE      : (0.126, 0, 0)

joint2/3/4는 모두 y축이므로 어깨부터 끝단까지는 **평면 3링크**다. 여유
자유도 하나는 끝단 접근 각도(`pitch`)로 고정해 해를 유일하게 만든다.

각도 부호: +y축 회전은 +z를 +x 쪽으로 눕힌다. 즉 joint2를 키우면 팔이
앞으로 기운다.
"""

from __future__ import annotations

import math

# 링크 상수 (m)
BASE_X = 0.012
SHOULDER_Z = 0.0595
UPPER_X, UPPER_Z = 0.024, 0.128
UPPER_LEN = math.hypot(UPPER_X, UPPER_Z)          # 0.1302
UPPER_SKEW = math.atan2(UPPER_X, UPPER_Z)         # 0.1855 rad
FORE_LEN = 0.124
WRIST_LEN = 0.126

# URDF 가동범위
LIMITS = {
    "joint1": (-math.pi, math.pi),
    "joint2": (-1.5, 1.5),
    "joint3": (-1.5, 1.4),
    "joint4": (-1.7, 1.97),
}

GRIPPER_OPEN = 0.019
GRIPPER_CLOSED = -0.008


def forward(j1: float, j2: float, j3: float, j4: float) -> tuple[float, float, float]:
    """관절각 → 끝단 위치(팔 베이스 링크 기준, m)."""
    # 어깨 기준 평면 좌표 (r: 팔이 뻗는 방향, z: 높이)
    a2 = j2 + UPPER_SKEW                 # 상완이 +z에서 기운 각
    r = UPPER_LEN * math.sin(a2)
    z = UPPER_LEN * math.cos(a2)

    a3 = a2 - UPPER_SKEW + j3 + math.pi / 2   # 전완 방향(+z 기준)
    r += FORE_LEN * math.sin(a3)
    z += FORE_LEN * math.cos(a3)

    a4 = a3 + j4
    r += WRIST_LEN * math.sin(a4)
    z += WRIST_LEN * math.cos(a4)

    r += BASE_X
    z += SHOULDER_Z
    return (r * math.cos(j1), r * math.sin(j1), z)


def end_pitch(j2: float, j3: float, j4: float) -> float:
    """끝단이 향하는 각도. 0 = 수평 전방, 음수 = 아래를 향함."""
    a4 = j2 + j3 + j4 + math.pi / 2
    return math.pi / 2 - a4


def inverse(
    x: float, y: float, z: float, pitch: float = -0.5
) -> tuple[float, float, float, float] | None:
    """끝단 목표 위치 → 관절각. 도달 불가면 None.

    [pitch]는 끝단 접근 각도(rad). 0이면 수평, 음수면 위에서 내려찍는 자세다.
    화물을 로봇 데크에 내려놓을 때는 음수를 쓴다.

    풀이는 어깨 기준 (r, z) 평면의 2링크 문제로 환원한다. 각 링크가 +z에서
    기운 각을 A(상완) · B(전완) · C(손목)라 하면

        A = j2 + α,   B = j2 + j3 + π/2,   C = j2 + j3 + j4 + π/2
        C = π/2 − pitch                      (접근 각도로 고정)
        손목 중심 W = 끝단 − WRIST_LEN·(sin C, cos C)

    W를 상완·전완 2링크로 풀고 되돌린다.
    """
    j1 = math.atan2(y, x)
    r = math.hypot(x, y) - BASE_X
    zt = z - SHOULDER_Z

    c_ang = math.pi / 2 - pitch
    wr = r - WRIST_LEN * math.sin(c_ang)
    wz = zt - WRIST_LEN * math.cos(c_ang)

    d = math.hypot(wr, wz)
    if d > UPPER_LEN + FORE_LEN or d < abs(UPPER_LEN - FORE_LEN) or d < 1e-9:
        return None

    cos_d = (d * d - UPPER_LEN**2 - FORE_LEN**2) / (2 * UPPER_LEN * FORE_LEN)
    cos_d = max(-1.0, min(1.0, cos_d))
    phi = math.atan2(wr, wz)

    # 팔꿈치 두 해(위·아래) 중 가동범위를 만족하는 쪽을 쓴다.
    for delta in (math.acos(cos_d), -math.acos(cos_d)):
        a_ang = phi - math.atan2(
            FORE_LEN * math.sin(delta), UPPER_LEN + FORE_LEN * math.cos(delta)
        )
        j2 = a_ang - UPPER_SKEW
        j3 = delta + UPPER_SKEW - math.pi / 2
        j4 = -pitch - j2 - j3
        joints = (j1, j2, j3, j4)
        if all(
            lo - 1e-9 <= v <= hi + 1e-9
            for v, (lo, hi) in zip(joints, LIMITS.values())
        ):
            return joints
    return None


def clamp(joints: tuple[float, float, float, float]) -> tuple[float, ...]:
    return tuple(
        max(lo, min(hi, v))
        for v, (lo, hi) in zip(joints, LIMITS.values())
    )
