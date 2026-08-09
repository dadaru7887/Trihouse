"""safety test에서도 쓸 수 있도록 ROS와 분리한 작은 geometry 함수."""
from collections.abc import Sequence


def point_in_polygon(x: float, y: float, polygon: Sequence[tuple[float, float]]) -> bool:
    """자기 교차하지 않는 polygon 안에 점이 있으면 true를 반환한다."""
    inside = False
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[index - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside
