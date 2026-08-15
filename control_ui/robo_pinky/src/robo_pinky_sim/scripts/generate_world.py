#!/usr/bin/env python3
"""관제센터 평면도(WarehouseLayout)를 그대로 Gazebo 월드로 옮긴다.

`robo_control/lib/core/layout.dart`의 상수와 1:1로 대응한다. 레이아웃을
바꾸면 아래 상수만 맞춘 뒤 이 스크립트를 다시 돌려 월드를 재생성한다.

    python3 generate_world.py ../worlds/warehouse_3temp.sdf

좌표 변환(관제 unit → 가제보 m, 창고 중심이 원점):
    x_m = (x_u - 60) * SCALE
    y_m = (36 - y_u) * SCALE        # 관제 화면은 y가 아래로 증가한다
"""

from __future__ import annotations

import sys

# ─────────────────────────────────────────── layout.dart 대응 상수
SCALE = 0.1  # m / unit
WIDTH = 120.0
HEIGHT = 72.0
CORRIDOR_Y = [6.0, 22.0, 38.0, 54.0, 68.0]
CORRIDOR_X = [5.0, 20.0, 35.0, 50.0, 65.0, 80.0, 95.0, 110.0]
RACK_ROW_Y = [13.0, 30.0, 46.0, 61.0]
RACK_X0, RACK_X1 = 8.0, 116.0
RACK_HALF_DEPTH = 2.6
AISLE_HALF_GAP = 2.8  # 세로 통로가 랙을 관통하도록 뚫는 폭의 절반

ZONE_BOUNDS = [  # (이름, x 시작, x 끝, 바닥색 rgba)
    ("ambient", 0.0, 50.0, (0.78, 0.76, 0.72, 1.0)),
    ("chilled", 50.0, 88.0, (0.68, 0.78, 0.84, 1.0)),
    ("frozen", 88.0, 120.0, (0.72, 0.82, 0.90, 1.0)),
]

RACK_COLOR = {
    "ambient": (0.62, 0.56, 0.46, 1.0),
    "chilled": (0.46, 0.60, 0.68, 1.0),
    "frozen": (0.52, 0.64, 0.74, 1.0),
}

STATIONS = [
    # (id, 종류, x_u, y_u)
    ("IN-1", "inbound", 5.0, 6.0),
    ("IN-2", "inbound", 5.0, 22.0),
    ("OUT-1", "outbound", 5.0, 54.0),
    ("OUT-2", "outbound", 5.0, 68.0),
    ("CHG-1", "charger", 20.0, 68.0),
    ("CHG-2", "charger", 35.0, 68.0),
    ("CHG-3", "charger", 65.0, 68.0),
    ("CHG-4", "charger", 95.0, 68.0),
    ("WS-1", "workstation", 35.0, 38.0),
    ("WS-2", "workstation", 65.0, 38.0),
    ("WS-3", "workstation", 95.0, 38.0),
    # 적재 스테이션 — 로봇팔이 서는 자리. 세로 통로·랙 진입선을 피한 좌표다.
    ("LOAD-A", "loading", 40.3, 38.0),
    ("LOAD-C", "loading", 68.3, 38.0),
    ("LOAD-F", "loading", 101.9, 38.0),
    ("STB-1", "standby", 50.0, 22.0),
    ("STB-2", "standby", 80.0, 54.0),
    ("ASM-1", "assembly", 5.0, 38.0),
]

STATION_STYLE = {
    "inbound": ((0.30, 0.62, 0.42, 1.0), 1.6),
    "outbound": ((0.24, 0.48, 0.78, 1.0), 1.6),
    "charger": ((0.95, 0.72, 0.16, 1.0), 1.4),
    "workstation": ((0.86, 0.40, 0.62, 1.0), 1.4),
    "loading": ((0.93, 0.64, 0.13, 1.0), 1.8),
    "standby": ((0.55, 0.58, 0.64, 1.0), 1.4),
    "assembly": ((0.85, 0.22, 0.20, 1.0), 1.8),
}

WALL_HEIGHT = 0.30
WALL_THICK = 0.06
RACK_HEIGHT = 0.32


def mx(x_u: float) -> float:
    return round((x_u - WIDTH / 2) * SCALE, 4)


def my(y_u: float) -> float:
    return round((HEIGHT / 2 - y_u) * SCALE, 4)


def ml(v: float) -> float:
    """길이 변환(부호 없음)."""
    return round(v * SCALE, 4)


def zone_of(x_u: float) -> str:
    for name, x0, x1, _ in ZONE_BOUNDS:
        if x_u < x1:
            return name
    return "frozen"


def rgba(c) -> str:
    return " ".join(str(v) for v in c)


def box_visual(name, size, pose, color, cast_shadows=True, collide=True):
    sx, sy, sz = size
    parts = [
        f'      <link name="{name}">',
        f"        <pose>{pose}</pose>",
    ]
    if collide:
        parts += [
            '        <collision name="collision">',
            f"          <geometry><box><size>{sx} {sy} {sz}</size></box></geometry>",
            "        </collision>",
        ]
    parts += [
        '        <visual name="visual">',
        f"          <geometry><box><size>{sx} {sy} {sz}</size></box></geometry>",
        "          <material>",
        f"            <ambient>{rgba(color)}</ambient>",
        f"            <diffuse>{rgba(color)}</diffuse>",
        f"            <specular>0.1 0.1 0.1 1</specular>",
        "          </material>",
        f"          <cast_shadows>{'true' if cast_shadows else 'false'}</cast_shadows>",
        "        </visual>",
        "      </link>",
    ]
    return "\n".join(parts)


def rack_segments():
    """세로 통로가 지나는 자리를 비운 랙 구간 목록."""
    gaps = sorted(x for x in CORRIDOR_X if RACK_X0 < x < RACK_X1)
    segments = []
    cursor = RACK_X0
    for g in gaps:
        if g - AISLE_HALF_GAP > cursor:
            segments.append((cursor, g - AISLE_HALF_GAP))
        cursor = g + AISLE_HALF_GAP
    if RACK_X1 > cursor:
        segments.append((cursor, RACK_X1))
    return segments


def build() -> str:
    out = []
    out.append('<?xml version="1.0" ?>')
    out.append('<sdf version="1.9">')
    out.append('  <world name="warehouse_3temp">')
    out.append("""
    <physics name="1ms" type="ignored">
      <max_step_size>0.002</max_step_size>
      <real_time_factor>1.0</real_time_factor>
    </physics>

    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-contact-system" name="gz::sim::systems::Contact"/>
    <plugin filename="gz-sim-imu-system" name="gz::sim::systems::Imu"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>

    <scene>
      <ambient>0.85 0.85 0.88 1</ambient>
      <background>0.62 0.68 0.76 1</background>
      <grid>false</grid>
      <shadows>false</shadows>
    </scene>

    <gui fullscreen="0">
      <plugin filename="MinimalScene" name="3D View">
        <gz-gui>
          <property type="string" key="state">docked</property>
        </gz-gui>
        <engine>ogre2</engine>
        <scene>scene</scene>
        <ambient_light>0.85 0.85 0.88</ambient_light>
        <background_color>0.62 0.68 0.76</background_color>
        <camera_pose>0 -7.5 9.0 0 0.95 1.5708</camera_pose>
      </plugin>
      <plugin filename="EntityContextMenuPlugin" name="Entity context menu">
        <gz-gui>
          <property key="state" type="string">floating</property>
          <property key="width" type="double">5</property>
          <property key="height" type="double">5</property>
          <property key="showTitleBar" type="bool">false</property>
        </gz-gui>
      </plugin>
      <plugin filename="GzSceneManager" name="Scene Manager"/>
      <plugin filename="InteractiveViewControl" name="Interactive view control"/>
      <plugin filename="CameraTracking" name="Camera Tracking"/>
      <plugin filename="MarkerManager" name="Marker manager"/>
      <plugin filename="SelectEntities" name="Select Entities"/>
      <plugin filename="Spawn" name="Spawn Entities"/>
      <plugin filename="VisualizationCapabilities" name="Visualization Capabilities"/>
      <plugin filename="WorldControl" name="World control">
        <gz-gui>
          <title>World control</title>
          <property type="bool" key="showTitleBar">false</property>
          <property type="bool" key="resizable">false</property>
          <property type="double" key="height">72</property>
          <property type="double" key="z">1</property>
          <property type="string" key="state">floating</property>
          <anchors target="3D View">
            <line own="left" target="left"/>
            <line own="bottom" target="bottom"/>
          </anchors>
        </gz-gui>
        <play_pause>true</play_pause>
        <step>true</step>
        <use_event>true</use_event>
      </plugin>
      <plugin filename="WorldStats" name="World stats">
        <gz-gui>
          <title>World stats</title>
          <property type="bool" key="showTitleBar">false</property>
          <property type="bool" key="resizable">false</property>
          <property type="double" key="height">110</property>
          <property type="double" key="width">290</property>
          <property type="double" key="z">1</property>
          <property type="string" key="state">floating</property>
          <anchors target="3D View">
            <line own="right" target="right"/>
            <line own="bottom" target="bottom"/>
          </anchors>
        </gz-gui>
        <sim_time>true</sim_time>
        <real_time>true</real_time>
        <real_time_factor>true</real_time_factor>
      </plugin>

      <!-- 도형 배치 · 이동/회전 · 스크린샷 · 엔티티 조회.
           장애물을 놓아 보거나 로봇을 통로로 옮기려면 필요하다. -->
      <plugin filename="Shapes" name="Shapes">
        <gz-gui>
          <property key="resizable" type="bool">false</property>
          <property key="x" type="double">0</property>
          <property key="y" type="double">0</property>
          <property key="width" type="double">300</property>
          <property key="height" type="double">50</property>
          <property key="state" type="string">floating</property>
          <property key="showTitleBar" type="bool">false</property>
          <property key="cardBackground" type="string">#666666</property>
        </gz-gui>
      </plugin>
      <plugin filename="TransformControl" name="Transform control">
        <gz-gui>
          <property key="resizable" type="bool">false</property>
          <property key="x" type="double">0</property>
          <property key="y" type="double">50</property>
          <property key="width" type="double">250</property>
          <property key="height" type="double">50</property>
          <property key="state" type="string">floating</property>
          <property key="showTitleBar" type="bool">false</property>
          <property key="cardBackground" type="string">#777777</property>
        </gz-gui>
      </plugin>
      <plugin filename="Screenshot" name="Screenshot">
        <gz-gui>
          <property key="resizable" type="bool">false</property>
          <property key="x" type="double">250</property>
          <property key="y" type="double">50</property>
          <property key="width" type="double">50</property>
          <property key="height" type="double">50</property>
          <property key="state" type="string">floating</property>
          <property key="showTitleBar" type="bool">false</property>
          <property key="cardBackground" type="string">#777777</property>
        </gz-gui>
      </plugin>
      <plugin filename="ComponentInspector" name="Component inspector">
        <gz-gui>
          <property type="bool" key="showTitleBar">false</property>
          <property type="string" key="state">docked</property>
        </gz-gui>
      </plugin>
      <plugin filename="EntityTree" name="Entity tree">
        <gz-gui>
          <property type="bool" key="showTitleBar">false</property>
          <property type="string" key="state">docked</property>
        </gz-gui>
      </plugin>
    </gui>

    <light type="directional" name="sun">
      <cast_shadows>false</cast_shadows>
      <pose>0 0 8 0 0 0</pose>
      <diffuse>0.9 0.9 0.9 1</diffuse>
      <specular>0.1 0.1 0.1 1</specular>
      <direction>-0.3 0.4 -0.9</direction>
    </light>
""")

    # 구획별 천장 조명 — 조도(상온 320 / 냉장 240 / 냉동 180 lx)를 밝기로 표현
    for name, x0, x1, _ in ZONE_BOUNDS:
        intensity = {"ambient": 1.0, "chilled": 0.75, "frozen": 0.55}[name]
        cx = mx((x0 + x1) / 2)
        out.append(f"""    <light type="point" name="light_{name}">
      <pose>{cx} 0 2.2 0 0 0</pose>
      <diffuse>{intensity} {intensity} {intensity} 1</diffuse>
      <specular>0.1 0.1 0.1 1</specular>
      <attenuation><range>12</range><linear>0.05</linear><constant>0.3</constant></attenuation>
      <cast_shadows>false</cast_shadows>
    </light>""")

    # ── 바닥: 구획별 색 + 충돌면
    out.append('    <model name="floor">')
    out.append("      <static>true</static>")
    for name, x0, x1, color in ZONE_BOUNDS:
        w = ml(x1 - x0)
        cx = mx((x0 + x1) / 2)
        out.append(
            box_visual(
                f"floor_{name}",
                (w, ml(HEIGHT), 0.02),
                f"{cx} 0 -0.01 0 0 0",
                color,
                cast_shadows=False,
            )
        )
    out.append("    </model>")

    # ── 외벽
    out.append('    <model name="walls">')
    out.append("      <static>true</static>")
    hw, hh = ml(WIDTH) / 2, ml(HEIGHT) / 2
    wall_color = (0.42, 0.44, 0.48, 1.0)
    walls = [
        ("wall_north", (ml(WIDTH) + WALL_THICK, WALL_THICK, WALL_HEIGHT), f"0 {hh} {WALL_HEIGHT/2} 0 0 0"),
        ("wall_south", (ml(WIDTH) + WALL_THICK, WALL_THICK, WALL_HEIGHT), f"0 {-hh} {WALL_HEIGHT/2} 0 0 0"),
        ("wall_west", (WALL_THICK, ml(HEIGHT), WALL_HEIGHT), f"{-hw} 0 {WALL_HEIGHT/2} 0 0 0"),
        ("wall_east", (WALL_THICK, ml(HEIGHT), WALL_HEIGHT), f"{hw} 0 {WALL_HEIGHT/2} 0 0 0"),
    ]
    for n, size, pose in walls:
        out.append(box_visual(n, size, pose, wall_color))
    out.append("    </model>")

    # ── 랙 (세로 통로 자리는 비어 있다)
    out.append('    <model name="racks">')
    out.append("      <static>true</static>")
    for row, y_u in enumerate(RACK_ROW_Y):
        for si, (x0, x1) in enumerate(rack_segments()):
            zone = zone_of((x0 + x1) / 2)
            out.append(
                box_visual(
                    f"rack_r{row + 1}_s{si + 1}",
                    (ml(x1 - x0), ml(RACK_HALF_DEPTH * 2), RACK_HEIGHT),
                    f"{mx((x0 + x1) / 2)} {my(y_u)} {RACK_HEIGHT / 2} 0 0 0",
                    RACK_COLOR[zone],
                )
            )
    out.append("    </model>")

    # ── 스테이션 마커(바닥 데칼) + 충전소 기둥
    out.append('    <model name="stations">')
    out.append("      <static>true</static>")
    for sid, kind, x_u, y_u in STATIONS:
        color, radius_u = STATION_STYLE[kind]
        r = ml(radius_u)
        tag = sid.replace("-", "_")
        out.append(f"""      <link name="station_{tag}">
        <pose>{mx(x_u)} {my(y_u)} 0.005 0 0 0</pose>
        <visual name="visual">
          <geometry><cylinder><radius>{r}</radius><length>0.01</length></cylinder></geometry>
          <material>
            <ambient>{rgba(color)}</ambient>
            <diffuse>{rgba(color)}</diffuse>
          </material>
          <cast_shadows>false</cast_shadows>
        </visual>
      </link>""")
        if kind == "charger":
            out.append(
                box_visual(
                    f"charger_post_{tag}",
                    (0.04, 0.04, 0.22),
                    f"{mx(x_u)} {my(y_u - 2.0)} 0.11 0 0 0",
                    color,
                )
            )
    out.append("    </model>")

    out.append("  </world>")
    out.append("</sdf>")
    return "\n".join(out) + "\n"


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else "-"
    sdf = build()
    if target == "-":
        sys.stdout.write(sdf)
    else:
        with open(target, "w", encoding="utf-8") as fp:
            fp.write(sdf)
        segs = len(rack_segments()) * len(RACK_ROW_Y)
        print(f"{target} 생성 완료 — 랙 {segs}개, 스테이션 {len(STATIONS)}개, "
              f"창고 {ml(WIDTH)}m × {ml(HEIGHT)}m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
