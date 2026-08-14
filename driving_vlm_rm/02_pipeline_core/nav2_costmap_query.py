"""recovery_filters.py의 FilterContext stub 콜백(query_costmap_free 등)을 실제
Nav2 costmap/planner 조회로 채우는 모듈.

지금 지도(final_map_06)가 실제 배치와 다를 수 있어서, "정적 지도 기반" global_costmap보다
"실시간 LiDAR 기반" local_costmap을 우선으로 쓴다 (사용자와 논의해서 결정한 방향).

Nav2가 /local_costmap/costmap, /global_costmap/costmap에 발행하는 OccupancyGrid를 그대로
구독한다 (nav2_costmap_2d 관례: -1=unknown, 0=free, 1~98=inflated cost, 99=inscribed
(footprint 반경 기준 충돌 확정), 100=lethal). 별도 costmap을 새로 만들지 않고 Nav2가 이미
돌리고 있는 걸 그대로 재사용.

이 모듈은 조회만 한다 -- 로봇을 움직이는 어떤 명령도 보내지 않음(compute_path_to_pose도
planning-only 액션이라 실제 이동 없음).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import rclpy
import tf2_ros
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import ComputePathToPose
from nav_msgs.msg import OccupancyGrid
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from rclpy.time import Time

# nav2_costmap_2d -> OccupancyGrid 변환 관례
UNKNOWN = -1
INSCRIBED_INFLATED = 99   # 이 이상이면 footprint(반경 근사) 기준 충돌 확정
LETHAL = 100

# §7 R4-01 등에서 쓸 기본 footprint 반경 근사 (nav2_params.yaml 확인된 footprint 12x12cm ->
# 안쪽에 꽉 차는 원의 반지름 = 0.06m. 대각선까지 감싸는 원이 아니라 안쪽 원 기준으로 보수적으로 잡음)
FOOTPRINT_INSCRIBED_RADIUS_M = 0.06


@dataclass
class CostmapSnapshot:
    grid: list[int]
    width: int
    height: int
    resolution: float
    origin_x: float
    origin_y: float
    stamp_sec: float


class CostmapQueryNode(Node):
    def __init__(self) -> None:
        super().__init__("costmap_query_node")

        # costmap 토픽은 보통 transient_local(latched)로 나옴 -- QoS 맞춰줘야 마지막 값을 바로 받음
        qos = QoSProfile(depth=1)
        qos.reliability = QoSReliabilityPolicy.RELIABLE
        qos.durability = QoSDurabilityPolicy.TRANSIENT_LOCAL

        self._local: CostmapSnapshot | None = None
        self._global: CostmapSnapshot | None = None

        self.create_subscription(OccupancyGrid, "/local_costmap/costmap",
                                  self._on_local, qos)
        self.create_subscription(OccupancyGrid, "/global_costmap/costmap",
                                  self._on_global, qos)

        self.plan_client = ActionClient(self, ComputePathToPose, "compute_path_to_pose")

        # 2026-08-11 버그 수정: local_costmap은 frame_id=odom, global_costmap은
        # frame_id=map으로 발행되는데(실측 확인), 이 모듈에 넘어오는 후보 좌표(x,y)는
        # AMCL/VLM 기준 map 프레임이었음. 좌표계 안 맞춘 채로 local costmap을 조회해서
        # 로봇 자기 자신 위치조차 "점유됨"으로 잘못 나오는 버그가 있었음(6C-Lite 실데이터
        # 검증 중 발견). map->odom TF로 변환해서 local costmap 조회에 씀.
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        self.get_logger().info("costmap_query_node 기동 -- local/global costmap 구독 시작")

    def _on_local(self, msg: OccupancyGrid) -> None:
        self._local = self._to_snapshot(msg)

    def _on_global(self, msg: OccupancyGrid) -> None:
        self._global = self._to_snapshot(msg)

    @staticmethod
    def _to_snapshot(msg: OccupancyGrid) -> CostmapSnapshot:
        return CostmapSnapshot(
            grid=msg.data,
            width=msg.info.width,
            height=msg.info.height,
            resolution=msg.info.resolution,
            origin_x=msg.info.origin.position.x,
            origin_y=msg.info.origin.position.y,
            stamp_sec=msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9,
        )

    def _cell_value(self, snap: CostmapSnapshot, x: float, y: float) -> int | None:
        gx = int((x - snap.origin_x) / snap.resolution)
        gy = int((y - snap.origin_y) / snap.resolution)
        if not (0 <= gx < snap.width and 0 <= gy < snap.height):
            return None  # costmap 범위 밖 -- 모른다는 뜻이지 free라는 뜻이 아님
        idx = gy * snap.width + gx
        if idx >= len(snap.grid):
            return None
        return snap.grid[idx]

    # ------------------------------------------------------------------
    # recovery_filters.FilterContext에 바인딩할 콜백들
    # ------------------------------------------------------------------

    def _map_to_odom(self, x: float, y: float) -> tuple[float, float] | None:
        """map 프레임 (x,y) -> odom 프레임으로 변환 (local_costmap이 odom 프레임이라 필요).
        TF를 아직 못 받았으면 None -- 호출부가 이 경우 local costmap 건너뛰고 global로만
        판단하게 함(잘못된 좌표로 조회하는 것보다 안전)."""
        try:
            tf = self.tf_buffer.lookup_transform("odom", "map", Time())
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException,
                tf2_ros.ExtrapolationException):
            return None
        t = tf.transform.translation
        q = tf.transform.rotation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        ox = t.x + x * math.cos(yaw) - y * math.sin(yaw)
        oy = t.y + x * math.sin(yaw) + y * math.cos(yaw)
        return ox, oy

    def _cell_value_local_then_global(self, x: float, y: float) -> int | None:
        """local_costmap(실시간 LiDAR) 우선이지만, 그 지점이 local의 조회 범위
        자체를 벗어나면(로봇에서 멀어서 rolling window 밖) None 대신 global_costmap도
        확인함 -- 예전엔 local이 있으면 무조건 local만 쓰고 범위 밖이면 그냥 "모름"
        처리해서, 로봇에서 좀 먼 목적지가 실제로는 안전한데도 부당하게 막히는 버그가
        있었음 (R4-01 실제 Nav2 계획은 OK인데 이 체크만 막았던 사례로 확인됨).

        입력 (x,y)는 map 프레임 기준. local_costmap은 odom 프레임이라 조회 전 변환 필요
        (2026-08-11 버그 수정 -- 이전엔 변환 없이 그대로 써서 로봇 자기 위치도 점유로
        잘못 판정되는 문제가 있었음)."""
        if self._local is not None:
            odom_xy = self._map_to_odom(x, y)
            if odom_xy is not None:
                val = self._cell_value(self._local, odom_xy[0], odom_xy[1])
                if val is not None:
                    return val
        if self._global is not None:
            return self._cell_value(self._global, x, y)
        return None

    def query_costmap_free(self, x: float, y: float) -> bool:
        """R2-02 COST_FREE. local_costmap(실시간 LiDAR) 우선, 범위 밖이면 global로 대체."""
        if self._local is None and self._global is None:
            self.get_logger().warn("costmap 아직 안 받음 -- 안전하게 False 반환")
            return False
        val = self._cell_value_local_then_global(x, y)
        if val is None or val == UNKNOWN:
            return False  # 모르는 영역은 free로 치지 않음 (R3-06 원칙과 동일)
        return val < INSCRIBED_INFLATED

    def query_footprint_fits(self, x: float, y: float, yaw: float) -> bool:
        """R2-03 FOOTPRINT_FITS. 간이 버전: inscribed radius만큼 원 둘레 샘플링해서
        전부 확인 (실제 사각 footprint 정밀 스윕이 아니라 근사 -- 지금 12x12cm처럼
        거의 정사각형/작은 로봇에는 충분히 보수적임). local 범위 밖이면 global로 대체."""
        if self._local is None and self._global is None:
            return False
        n_samples = 8
        for i in range(n_samples):
            ang = 2 * math.pi * i / n_samples
            sx = x + FOOTPRINT_INSCRIBED_RADIUS_M * math.cos(ang)
            sy = y + FOOTPRINT_INSCRIBED_RADIUS_M * math.sin(ang)
            val = self._cell_value_local_then_global(sx, sy)
            if val is None or val == UNKNOWN or val >= INSCRIBED_INFLATED:
                return False
        return True

    def query_nav2_path_feasible(self, x: float, y: float, yaw: float,
                                  timeout_sec: float = 5.0) -> bool:
        """R4-01 PLAN_EXISTS. compute_path_to_pose는 planning-only 액션이라
        실제로 로봇을 움직이지 않음 -- 경로가 나오는지만 확인.
        하위호환용 bool 버전 -- 상세 에러코드가 필요하면 query_nav2_path_feasible_detailed 사용."""
        ok, _ = self.query_nav2_path_feasible_detailed(x, y, yaw, timeout_sec)
        return ok

    def query_nav2_path_feasible_detailed(self, x: float, y: float, yaw: float,
                                           timeout_sec: float = 5.0) -> tuple[bool, int | None]:
        """R4-01 PLAN_EXISTS + 실패 시 nav2_msgs 에러코드도 같이 반환.
        (ok: bool, error_code: int|None -- planner_error_code, 성공 시 None)"""
        if not self.plan_client.wait_for_server(timeout_sec=3.0):
            self.get_logger().warn("compute_path_to_pose 서버 없음")
            return False, None

        goal = ComputePathToPose.Goal()
        pose = PoseStamped()
        pose.header.frame_id = "map"
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.position.x = float(x)
        pose.pose.position.y = float(y)
        pose.pose.orientation.z = math.sin(yaw / 2.0)
        pose.pose.orientation.w = math.cos(yaw / 2.0)
        goal.goal = pose
        goal.use_start = False  # 현재 로봇 위치를 시작점으로 사용

        send_future = self.plan_client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, send_future, timeout_sec=timeout_sec)
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            return False, None

        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future, timeout_sec=timeout_sec)
        result = result_future.result()
        if result is None:
            return False, None
        ok = (result.status == GoalStatus.STATUS_SUCCEEDED
              and len(result.result.path.poses) > 0)
        error_code = None if ok else result.result.error_code
        return ok, error_code


# 2026-08-11 신규: R2-04 KEEPOUT 체크의 실제 구현. 예전엔 FilterContext 기본값
# lambda x,y: False로 항상 통과 처리되던 자리(구현 자체가 없었음, DB Reference Node의
# 출입금지구역 데이터도 아직 없음). map 프레임 (x,y) 폴리곤 리스트로 "출입금지 구역"을
# 정의하고 point-in-polygon으로 체크하는 실제 동작하는 틀만 먼저 만들어둠 -- 지금은 이
# 방/지도에 대해 실측으로 정의된 구역이 없어서 빈 리스트. 실제 구역(사람 전용 통로, 계단
# 등)이 정해지면 여기에 폴리곤만 추가하면 됨.
KEEPOUT_ZONES: list[list[tuple[float, float]]] = []
# 예시(주석 처리): 사각형 구역 하나 추가하려면
# KEEPOUT_ZONES.append([(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5)])


def _point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    """레이캐스팅 알고리즘 (표준 point-in-polygon). polygon은 (x,y) 꼭짓점 리스트,
    시계/반시계 방향 상관없음, 최소 3개 점 필요."""
    n = len(polygon)
    inside = False
    px, py = polygon[-1]
    for qx, qy in polygon:
        if ((qy > y) != (py > y)) and (x < (px - qx) * (y - qy) / (py - qy + 1e-12) + qx):
            inside = not inside
        px, py = qx, qy
    return inside


def query_keepout_violation(x: float, y: float) -> bool:
    """R2-04 KEEPOUT. KEEPOUT_ZONES에 등록된 폴리곤 중 하나에라도 (x,y)가 들어가면 True.
    costmap과 무관한 순수 정적 규칙 체크라 ROS 노드 없이도 동작함(테스트 쉬움)."""
    return any(_point_in_polygon(x, y, zone) for zone in KEEPOUT_ZONES)


def build_filter_context_queries(node: CostmapQueryNode) -> dict:
    """recovery_filters.FilterContext(...) 생성 시 그대로 풀어넣을 수 있는 dict.
    사용 예:
        node = CostmapQueryNode()
        ctx = FilterContext(..., **build_filter_context_queries(node))
    """
    return {
        "query_costmap_free": node.query_costmap_free,
        "query_footprint_fits": node.query_footprint_fits,
        "query_nav2_path_feasible": node.query_nav2_path_feasible,
        "query_keepout_violation": query_keepout_violation,
    }


if __name__ == "__main__":
    """단독 실행 시: costmap 수신 대기 후 로봇 현재 위치 근처 몇 지점 조회 테스트.
    로봇을 움직이지 않음 -- 순수 조회만."""
    rclpy.init()
    node = CostmapQueryNode()

    print("costmap 수신 대기 중...")
    for _ in range(40):
        rclpy.spin_once(node, timeout_sec=0.5)
        if node._local is not None:
            break

    if node._local is None:
        print("!! local_costmap을 못 받았습니다. Nav2가 떠있는지 확인하세요.")
    else:
        snap = node._local
        print(f"local_costmap 수신됨: {snap.width}x{snap.height}, "
              f"resolution={snap.resolution}, origin=({snap.origin_x:.2f},{snap.origin_y:.2f})")

        # 로봇 현재 위치(0,0 근방, map 원점 기준 로봇 시작 위치)와 그 주변 테스트
        test_points = [(0.0, 0.0), (0.3, 0.0), (-0.3, 0.0), (0.0, 0.3)]
        for x, y in test_points:
            free = node.query_costmap_free(x, y)
            fits = node.query_footprint_fits(x, y, 0.0)
            print(f"  ({x:+.1f}, {y:+.1f}): costmap_free={free}, footprint_fits={fits}")

        print("\ncompute_path_to_pose 테스트 (경로 계획만, 이동 없음)...")
        path_ok = node.query_nav2_path_feasible(0.3, 0.0, 0.0)
        print(f"  (0.3, 0.0)까지 경로 존재: {path_ok}")

    node.destroy_node()
    rclpy.shutdown()
