"""DB의 진짜 Reference Node/Edge가 아직 없어서, final_map_06.pgm의 실제 free space를
직접 스캔해서 만든 임시 nominal trajectory. §6 "Reference 후보"의 stand-in 역할.

각 waypoint는 실제로 map pixel 값(254=free)을 margin=1(로봇 몸체 여유)까지 확인해서
뽑은 것 -- 눈대중이 아니라 실제 occupancy 검증됨.

DB 붙으면 이 파일은 삭제하고 nav2_costmap_query.py의 build_filter_context_queries에
Reference Node/Edge 조회로 교체하면 됨. 그 전까지 R1-04(SOURCE_TRACE)/§6 "Reference 후보"
자리를 채우는 용도.
"""

NOMINAL_WAYPOINTS = [
    {"id": "nom_0", "x": 0.636, "y": 0.977},
    {"id": "nom_1", "x": 0.736, "y": 0.577},
    {"id": "nom_2", "x": 0.636, "y": 0.177},
    {"id": "nom_3", "x": 0.636, "y": -0.223},
    {"id": "nom_4", "x": 0.636, "y": -0.623},
    {"id": "nom_5", "x": 0.636, "y": -1.023},
    {"id": "nom_6", "x": 0.636, "y": -1.223},
]


def nearest_nominal_waypoint(x: float, y: float) -> dict:
    """현재 위치에서 제일 가까운 nominal waypoint 반환 (Reference 후보 대체용)."""
    best = min(NOMINAL_WAYPOINTS, key=lambda wp: (wp["x"] - x) ** 2 + (wp["y"] - y) ** 2)
    return best


def reference_candidates_near(x: float, y: float, radius_m: float = 1.5) -> list[dict]:
    """§6 "Reference 후보": 반경 안의 nominal waypoint 전부 (진짜 DB 쿼리 나오면 이 함수만 교체).
    반경 안에 하나도 없으면(로봇이 경로에서 멀리 떨어져 있으면) 그래도 가장 가까운 것
    1개는 넣어줌 -- 그래야 "전진(REJOIN) 후보가 아예 없어서 BACKUP만 남는" 상황을 줄임."""
    near = [wp for wp in NOMINAL_WAYPOINTS
            if (wp["x"] - x) ** 2 + (wp["y"] - y) ** 2 <= radius_m ** 2]
    if near:
        return near
    return [nearest_nominal_waypoint(x, y)]


def next_nominal_waypoint(x: float, y: float) -> dict:
    """state의 goal_pos 자리에 꽂을 값 -- 현재 위치에서 제일 가까운 waypoint의 "다음"
    순서 waypoint를 반환 (경로를 따라 앞으로 나아가는 목표점). 지금까지는
    goal_pos=(robot_x+2.0, robot_y) 같은 가짜값을 썼는데, 그건 방 크기(~2.6m)보다도
    커서 의미 없는 목표였음 -- 실제 free space 경로 상의 다음 지점으로 대체.
    마지막 waypoint 근처면 그 자리에서 안 넘어가고 유지(경로 끝)."""
    nearest = nearest_nominal_waypoint(x, y)
    idx = NOMINAL_WAYPOINTS.index(nearest)
    next_idx = min(idx + 1, len(NOMINAL_WAYPOINTS) - 1)
    return NOMINAL_WAYPOINTS[next_idx]


if __name__ == "__main__":
    print(f"nominal waypoint {len(NOMINAL_WAYPOINTS)}개 (final_map_06 실제 free space 검증됨):")
    for wp in NOMINAL_WAYPOINTS:
        print(f"  {wp['id']}: ({wp['x']}, {wp['y']})")

    test_pos = (0.6, 0.0)
    print(f"\n{test_pos} 근처 Reference 후보:")
    for wp in reference_candidates_near(*test_pos):
        print(f"  {wp}")
