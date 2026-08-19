#!/usr/bin/env python3
"""SLAM 지도를 격자로 펼쳐 waypoint 가 어디에 놓이는지 눈으로 확인한다.

    scripts/p0_show_map.py                       기본 trihouse_map_01
    scripts/p0_show_map.py new_map_2             이름으로
    scripts/p0_show_map.py /절대/경로/my_map.yaml  경로로

## 왜 필요한가

좌표는 **어느 지도 위에서 쟀는지**에 매여 있다. 지도를 새로 그리면 프레임이
바뀌어 같은 실측값이 다른 자리를 가리킨다. 그 어긋남은 로봇이 엉뚱한 곳에
서고 나서야 드러나는데, 그때는 로그를 시각까지 맞춰 가며 뒤져야 한다.

이 도구는 지도를 바꾸기 **전에** 그것을 보여 준다 — waypoint 가 벽 안에
박혔는지, 지도 밖으로 나갔는지, 문이 어디에 뚫려 있는지.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MAPS = ROOT / "control_ui" / "rmf_control_ui" / "data" / "rmf_maps"
FEATURES = (
    ROOT
    / "control_ui"
    / "rmf_control_ui"
    / "data"
    / "import"
    / "trihouse_test_01_physical_features.jsonl"
)

# 격자에 겹쳐 그릴 때 쓸 한 글자 표시. 이름이 길어 그대로는 못 얹는다.
MARKS = "ABCDEFGHJKLMNPQRSTUVWXYZ"


def load_grid(yaml_path: Path):
    meta = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    image_path = yaml_path.parent / meta["image"]
    if not image_path.is_file():
        raise SystemExit(f"지도 이미지가 없습니다: {image_path}")
    # 확장자가 아니라 내용으로 연다. `new_map_2.pgm` 은 이름만 .pgm 이고 PNG 다.
    from PIL import Image

    with Image.open(image_path) as handle:
        grey = handle.convert("L")
        width, height = grey.size
        pixels = list(grey.getdata())
    return meta, width, height, pixels, image_path


def main() -> None:
    selector = sys.argv[1] if len(sys.argv) > 1 else "trihouse_map_01"
    yaml_path = (
        Path(selector).expanduser().resolve()
        if selector.endswith(".yaml") or "/" in selector
        else MAPS / f"{selector}.yaml"
    )
    if not yaml_path.is_file():
        print(f"[실패] SLAM yaml 이 없습니다: {yaml_path}")
        print(f"       저장소에 있는 지도: {', '.join(sorted(q.stem for q in MAPS.glob('*.yaml')))}")
        raise SystemExit(1)

    meta, width, height, pixels, image_path = load_grid(yaml_path)
    res = float(meta["resolution"])
    ox, oy = float(meta["origin"][0]), float(meta["origin"][1])
    print(f"지도   {yaml_path.name}  ({image_path.name})")
    print(f"크기   {width} x {height} px @ {res} m/px  =  {width * res:.2f} x {height * res:.2f} m")
    print(f"원점   ({ox}, {oy})   범위 x {ox:.3f}~{ox + width * res:.3f}  y {oy:.3f}~{oy + height * res:.3f}")
    print()

    points = []
    for line in FEATURES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        pose = record.get("map_pose") or {}
        if "x" not in pose or "y" not in pose:
            continue
        points.append(
            (
                record.get("rmf_waypoint_name")
                or record.get("source_id")
                or record.get("feature_code")
                or "?",
                float(pose["x"]),
                float(pose["y"]),
                record.get("temperature_zone") or record.get("record_type") or "",
            )
        )

    overlay, legend, problems = {}, [], []
    for index, (name, x, y, tag) in enumerate(points):
        mark = MARKS[index % len(MARKS)]
        col = int((x - ox) / res)
        row = height - 1 - int((y - oy) / res)
        legend.append(f"  {mark}  {name:38s} ({x:7.3f}, {y:7.3f})  {tag}")
        if not (0 <= col < width and 0 <= row < height):
            problems.append(f"  {mark} {name}: 지도 **밖**이다 ({x:.3f}, {y:.3f})")
            continue
        if pixels[row * width + col] < 100:
            problems.append(f"  {mark} {name}: 점유 격자(벽) 위다 ({x:.3f}, {y:.3f})")
        overlay[(row, col)] = mark

    for row in range(height):
        line = []
        for col in range(width):
            if (row, col) in overlay:
                line.append(overlay[(row, col)])
                continue
            value = pixels[row * width + col]
            line.append("#" if value < 100 else ("." if value > 200 else "+"))
        print("".join(line))

    print()
    print("범례   # 벽   + 미확인   . 통행 가능")
    print("\n".join(legend))
    if problems:
        print("\n[주의] 이 지도에서는 아래 지점을 쓸 수 없습니다.")
        print("\n".join(problems))
        print("\n좌표는 실측 기록의 source_map_name 지도 위에서 잰 값입니다.")
        print("지도를 바꾸면 그 위에서 다시 재야 합니다.")
    else:
        print("\n모든 지점이 통행 가능한 격자 위에 있습니다.")

    reachability(width, height, pixels, res, ox, oy, points)


# 로봇 치수. `pinky_pro/pinky_navigation/params/nav2_params.yaml` 의 footprint 다.
# 전역 costmap 은 발자국 그대로, 지역 costmap 은 footprint_padding 0.03 이 더해진다.
ROBOT_WIDTH_M = 0.12
GLOBAL_NEEDS_M = 0.08
LOCAL_NEEDS_M = 0.14


def reachability(width, height, pixels, res, ox, oy, points) -> None:
    """병목 01 에서 각 도크까지, 지날 수 있는 가장 넓은 경로의 폭을 잰다.

    통로가 로봇보다 좁으면 lane 을 어떻게 이어도 로봇은 지나가지 못한다. 지도를
    바꾼 직후 이 값을 먼저 보면, 계획이나 그래프를 건드리기 전에 물리적으로
    가능한지부터 갈린다.
    """
    import heapq
    from collections import deque

    free = [[pixels[r * width + c] > 200 for c in range(width)] for r in range(height)]

    def to_rc(x, y):
        return height - 1 - int((y - oy) / res), int((x - ox) / res)

    def to_xy(r, c):
        return ox + (c + 0.5) * res, oy + (height - 1 - r + 0.5) * res

    # 각 자유 칸에서 가장 가까운 벽까지의 거리 = 그 자리의 통로 반폭.
    infinity = 10 ** 6
    clearance = [
        [0 if not free[r][c] else infinity for c in range(width)] for r in range(height)
    ]
    queue = deque(
        (r, c) for r in range(height) for c in range(width) if not free[r][c]
    )
    while queue:
        r, c = queue.popleft()
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < height and 0 <= nc < width and clearance[nr][nc] > clearance[r][c] + 1:
                clearance[nr][nc] = clearance[r][c] + 1
                queue.append((nr, nc))

    start = next((p for p in points if p[0].startswith("bottleneck_zone_01")), None)
    if start is None:
        return
    sr, sc = to_rc(start[1], start[2])
    if not (0 <= sr < height and 0 <= sc < width and free[sr][sc]):
        return

    # 최소 여유를 **최대화**하는 경로. 최단 경로가 아니라 "가장 넓은 길" 이다.
    best = {(sr, sc): clearance[sr][sc]}
    back = {(sr, sc): None}
    heap = [(-clearance[sr][sc], sr, sc)]
    while heap:
        negative, r, c = heapq.heappop(heap)
        if -negative < best.get((r, c), -1):
            continue
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = r + dr, c + dc
            if not (0 <= nr < height and 0 <= nc < width and free[nr][nc]):
                continue
            widest = min(-negative, clearance[nr][nc])
            if widest > best.get((nr, nc), -1):
                best[(nr, nc)] = widest
                back[(nr, nc)] = (r, c)
                heapq.heappush(heap, (-widest, nr, nc))

    print()
    print(f"병목 01 에서 각 지점까지 — 로봇 폭 {ROBOT_WIDTH_M} m, "
          f"전역 {GLOBAL_NEEDS_M} m · 지역 {LOCAL_NEEDS_M} m 필요")
    for name, x, y, tag in points:
        if "loading_dock" not in name:
            continue
        goal = to_rc(x, y)
        if goal not in best:
            print(f"  {name:38s} 자유 격자로 도달 불가")
            continue
        passage = 2 * best[goal] * res
        node, path = goal, []
        while node:
            path.append(node)
            node = back[node]
        tight = min(path, key=lambda p: clearance[p[0]][p[1]])
        tx, ty = to_xy(*tight)
        verdict = (
            "통과 가능"
            if passage >= LOCAL_NEEDS_M
            else "전역만 가능 — 지역 costmap 이 막는다"
            if passage >= GLOBAL_NEEDS_M
            else "**통과 불가**"
        )
        print(f"  {name:38s} 최선 통로 {passage:.2f} m  "
              f"(가장 좁은 곳 {tx:6.3f}, {ty:6.3f})  {verdict}")


if __name__ == "__main__":
    main()
