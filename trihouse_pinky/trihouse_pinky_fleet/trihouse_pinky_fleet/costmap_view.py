"""Nav2 costmap 을 ROS 없이 조회할 수 있는 스냅샷.

목적: 승인된 복구 좌표까지 **가는 길**이 지금 이 순간 비어 있는지 확인한다.
`motion_plan.canonicalize_recovery_action` 은 좌표 값 하나만 보고 지도를 보지 않으므로,
"목적지는 비어 있지만 가는 길에 기둥이 있다" 를 막지 못한다. 그 자리를 채운다.

호출법: `fleet_node` 가 `/local_costmap/costmap` 과 `/global_costmap/costmap` 을
구독해 `CostmapSnapshot.from_occupancy_grid` 로 담아 두고, `CostmapView` 에 넘겨
`costmap_free` / `footprint_fits` 를 질의한다. ROS 타입은 여기 들어오지 않는다 —
그래야 로봇 없이 테스트할 수 있다.

5080 의 복구 worker 도 이 모듈과 `recovery_path_check` 를 그대로 쓴다.
`CostmapSnapshot.from_map_yaml` 로 정적 지도를 읽어, 승인 요청 전에 벽이나
지도 밖으로 가는 후보를 로봇과 같은 규칙으로 지운다.

원본: `upstream/dev_driving/02_pipeline_core/nav2_costmap_query.py` 의 조회 규칙을
그대로 옮겼고, 프레임 변환은 호출부가 넘겨주는 함수로 분리했다.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Sequence


# nav2_costmap_2d -> OccupancyGrid 변환 관례.
UNKNOWN = -1
# 이 이상이면 발자국 반경 근사 기준으로 충돌 확정이다.
INSCRIBED_INFLATED = 99
LETHAL = 100

# 발자국 12 x 12 cm 안쪽에 꽉 차는 원의 반지름. `trihouse_pinky_safety.geometry`
# 의 같은 이름 상수와 값이 같아야 하고, `test_recovery_path_check.py` 가 묶는다.
FOOTPRINT_INSCRIBED_RADIUS_M = 0.06

# 발자국 적합 판정에 쓰는 원 둘레 표본 수. 12 x 12 cm 처럼 작고 거의 정사각형인
# 몸에는 8 점이면 충분히 보수적이다.
FOOTPRINT_SAMPLES = 8


@dataclass(frozen=True)
class CostmapSnapshot:
    """한 시점의 occupancy grid. 프레임 이름을 함께 들고 다닌다.

    `frame_id` 를 지우면 안 된다 — local costmap 은 odom, global 은 map 으로
    발행된다. 프레임을 맞추지 않고 조회하면 로봇 자기 위치조차 점유로 나온다
    (원본에서 실제로 났던 버그다).
    """

    grid: Sequence[int]
    width: int
    height: int
    resolution: float
    origin_x: float
    origin_y: float
    frame_id: str

    @classmethod
    def from_occupancy_grid(cls, message: object) -> "CostmapSnapshot":
        info = message.info  # type: ignore[attr-defined]
        return cls(
            grid=list(message.data),  # type: ignore[attr-defined]
            width=int(info.width),
            height=int(info.height),
            resolution=float(info.resolution),
            origin_x=float(info.origin.position.x),
            origin_y=float(info.origin.position.y),
            frame_id=str(message.header.frame_id),  # type: ignore[attr-defined]
        )

    @classmethod
    def from_map_yaml(cls, path: object) -> "CostmapSnapshot":
        """Nav2 map_server 의 yaml + 이미지 -> map 프레임 정적 grid (0 / 100 / -1).

        5080 이 승인 전에 벽 쪽 후보를 지우는 데 쓴다. 판정 규칙(occupied_thresh,
        free_thresh, negate)은 map_server 와 같고, 이미지 첫 행이 지도 맨 위라서
        grid 순서(맨 아래 행부터)로 뒤집는다.
        """
        from pathlib import Path

        import yaml
        from PIL import Image

        path = Path(path)
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        image = Image.open(path.parent / spec["image"]).convert("L")
        width, height = image.size
        pixels = image.tobytes()                       # one byte per pixel in mode L
        negate = bool(spec.get("negate", 0))
        grid: list[int] = []
        for row in range(height - 1, -1, -1):
            for value in pixels[row * width:(row + 1) * width]:
                occupied = value / 255.0 if negate else (255 - value) / 255.0
                grid.append(LETHAL if occupied > spec["occupied_thresh"]
                            else 0 if occupied < spec["free_thresh"] else UNKNOWN)
        origin = spec["origin"]
        return cls(grid=grid, width=width, height=height, resolution=float(spec["resolution"]),
                   origin_x=float(origin[0]), origin_y=float(origin[1]), frame_id="map")

    def cell_value(self, x_m: float, y_m: float) -> int | None:
        """이 grid 의 프레임 기준 좌표의 셀 값. 범위 밖이면 `None`.

        `None` 은 "free" 가 아니라 "모른다" 이다. 둘을 섞으면 지도 밖이 안전해진다.
        """
        if self.resolution <= 0.0:
            return None
        column = int((x_m - self.origin_x) / self.resolution)
        row = int((y_m - self.origin_y) / self.resolution)
        if not (0 <= column < self.width and 0 <= row < self.height):
            return None
        index = row * self.width + column
        if index >= len(self.grid):
            return None
        return int(self.grid[index])


class CostmapView:
    """local 우선, 범위 밖이면 global 로 되짚는 조회.

    local 을 먼저 보는 이유는 실시간 LiDAR 가 거기 반영되기 때문이고, 범위 밖에서
    global 로 넘어가는 이유는 local 이 rolling window 라 조금만 멀어도 "모름" 이
    되기 때문이다. 원본에서는 그 때문에 실제로 안전한 목적지가 부당하게 막혔다.
    """

    def __init__(
        self,
        *,
        local: CostmapSnapshot | None = None,
        global_: CostmapSnapshot | None = None,
        map_to_local: Callable[[float, float], tuple[float, float] | None] | None = None,
        keep_out_polygons: Sequence[Sequence[tuple[float, float]]] = (),
    ):
        self.local = local
        self.global_ = global_
        # local costmap 이 map 이 아닌 프레임이면 변환이 필요하다. 변환을 못 얻으면
        # local 을 건너뛴다 — 틀린 좌표로 조회하는 것보다 낫다.
        self.map_to_local = map_to_local
        self.keep_out_polygons = tuple(tuple(polygon) for polygon in keep_out_polygons)

    @property
    def ready(self) -> bool:
        return self.local is not None or self.global_ is not None

    def _value(self, x_m: float, y_m: float) -> int | None:
        if self.local is not None:
            local_xy: tuple[float, float] | None = (x_m, y_m)
            if self.map_to_local is not None:
                local_xy = self.map_to_local(x_m, y_m)
            if local_xy is not None:
                value = self.local.cell_value(*local_xy)
                if value is not None:
                    return value
        if self.global_ is not None:
            return self.global_.cell_value(x_m, y_m)
        return None

    def costmap_free(self, x_m: float, y_m: float) -> bool:
        """이 점이 지금 비어 있는가. costmap 을 아직 못 받았으면 False."""
        if not self.ready:
            return False
        value = self._value(x_m, y_m)
        if value is None or value == UNKNOWN:
            return False
        return value < INSCRIBED_INFLATED

    def footprint_fits(self, x_m: float, y_m: float, yaw_rad: float) -> bool:
        """이 자세에서 몸이 들어가는가. 내접원 둘레를 표본으로 근사한다."""
        if not self.ready:
            return False
        for index in range(FOOTPRINT_SAMPLES):
            angle = 2.0 * math.pi * index / FOOTPRINT_SAMPLES
            sample_x = x_m + FOOTPRINT_INSCRIBED_RADIUS_M * math.cos(angle)
            sample_y = y_m + FOOTPRINT_INSCRIBED_RADIUS_M * math.sin(angle)
            value = self._value(sample_x, sample_y)
            if value is None or value == UNKNOWN or value >= INSCRIBED_INFLATED:
                return False
        return True

    def keepout_violation(self, x_m: float, y_m: float) -> bool:
        """등록된 출입금지 구역 안인가. 구역이 없으면 위반도 없다."""
        return any(
            _point_in_polygon(x_m, y_m, polygon) for polygon in self.keep_out_polygons
        )


def _point_in_polygon(
    x: float, y: float, polygon: Sequence[tuple[float, float]]
) -> bool:
    inside = False
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[index - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside
