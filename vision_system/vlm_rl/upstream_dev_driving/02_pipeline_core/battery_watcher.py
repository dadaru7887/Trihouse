#!/usr/bin/env python3
"""배터리 비상 return 트리거. VLM/RL 파이프라인과 완전히 분리된 결정론적(deterministic) 모듈
-- 학습 중인(아직 거의 미학습인) 정책에 배터리 같은 안전-필수 판단을 맡기지 않기로 한 결정
(2026-08-12, "배터리는 따로 할 거 같아서" 확인).

로봇 자체 ROS2에 이미 배터리 토픽이 있는 걸 확인함 -- DB/Gateway API 완성 여부와 무관하게 로컬
구독만으로 동작 가능. DB의 `battery_pct`(0~100 스케일, database_guide_vlm_rl_extract.md)는
히스토리 기록/DB 스키마용이고, 실시간 비상 트리거는 이 로컬 토픽을 직접 씀.

**2026-08-12 실측 확정**: `battery_publihser`는 토픽명이 아니라 **노드명**이었음(오타 그대로).
실제 토픽은 `/battery/percent`(+`/battery/voltage`), 타입은 `sensor_msgs/BatteryState`가 아니라
**`std_msgs/msg/Float32`** 단일 값. 스케일(0~100 vs 0.0~1.0)은 아직 실측 못 함(로봇 배터리가
낮아서 echo가 값을 못 받아옴) -- `_on_battery()`에서 자동 판별하도록 처리(1.0보다 크면 0~100
스케일로 보고 100으로 나눔).

트리거되면 하는 일: waypoint 그래프에서 제일 가까운 safe_zone을 찾아 이동(§ "battery는 VLM/RL
안 거치고 그래프+Nav2로 결정론적 처리" 설계, 2026-08-12). **safe_zone 좌표는 아직 미입력**
(사진 속 Safe Zone/적재 위치를 map 좌표로 옮기는 작업이 남아있음) -- SAFE_ZONE_WAYPOINTS가
비어있으면 트리거만 로그로 남기고 실제 이동은 안 함(R0-06/R5와 같은 fail-closed 원칙).
"""

from __future__ import annotations

import json
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32

LOW_BATTERY_THRESHOLD = 0.20  # percentage 0.0~1.0 기준 -- 실측 방전 곡선 보고 재조정 필요
CRITICAL_BATTERY_THRESHOLD = 0.10  # 이 밑이면 즉시(최우선) 복귀

FMS_FEATURE_POINTS_PATH = Path(__file__).parent / "fms_feature_points.jsonl"


def _load_safe_zone_waypoints() -> list[dict]:
    """2026-08-12: fms_feature_points.jsonl에 저장해둔 safe_zone 체크포인트에서 로드.
    여러 개 저장돼있으면(나중에 safe_zone 2개 이상 될 수도 있음) label로 전부 모음.
    파일이 없거나 safe_zone이 하나도 없으면 빈 리스트(fail-closed 유지)."""
    if not FMS_FEATURE_POINTS_PATH.exists():
        return []
    waypoints = []
    with FMS_FEATURE_POINTS_PATH.open() as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("label", "").startswith("safe_zone"):
                waypoints.append({"id": entry["label"], "x": entry["map_x"], "y": entry["map_y"]})
    return waypoints


SAFE_ZONE_WAYPOINTS: list[dict] = _load_safe_zone_waypoints()


class BatteryWatcher(Node):
    """VLM/RL과 완전히 독립적으로 도는 배터리 감시 노드 -- 학습된 정책 개입 전혀 없이
    임계값만으로 결정론적으로 트리거함."""

    def __init__(self, on_low_battery=None, on_critical_battery=None) -> None:
        super().__init__("battery_watcher")
        self.percentage: float | None = None
        self.voltage: float | None = None
        self._low_triggered = False
        self._critical_triggered = False
        self._on_low = on_low_battery
        self._on_critical = on_critical_battery
        self.create_subscription(Float32, "/battery/percent", self._on_battery, 10)
        # 2026-08-13 저녁 추가: DB 담당자 확인 결과 전류(전류량)를 계속 push해달라는
        # 요청이 있었는데, 로봇에 전류 토픽이 없음(battery_publihser 노드가 percent/voltage
        # 딱 둘만 발행, ros2 node info로 실측 확인). 전류 센서 자체가 없는 것으로 보여서
        # 전압으로 대체하기로 함(사용자 결정, "전류 없으면 전압이라도"). 전류 자체가 필요하면
        # 나중에 하드웨어 레벨(전류 센서 추가)에서 해결해야 할 문제.
        self.create_subscription(Float32, "/battery/voltage", self._on_voltage, 10)
        self.get_logger().info(
            f"배터리 감시 시작 (low={LOW_BATTERY_THRESHOLD*100:.0f}%, "
            f"critical={CRITICAL_BATTERY_THRESHOLD*100:.0f}%)")

    def _on_voltage(self, msg: Float32) -> None:
        self.voltage = msg.data

    def _on_battery(self, msg: Float32) -> None:
        # 0~100 스케일로 오면(예: 15.0) 0.0~1.0로 정규화, 이미 0.0~1.0이면 그대로
        self.percentage = msg.data / 100.0 if msg.data > 1.0 else msg.data
        if self.percentage <= CRITICAL_BATTERY_THRESHOLD and not self._critical_triggered:
            self._critical_triggered = True
            self.get_logger().warn(f"배터리 CRITICAL: {self.percentage*100:.1f}%")
            if self._on_critical:
                self._on_critical(self.percentage)
        elif self.percentage <= LOW_BATTERY_THRESHOLD and not self._low_triggered:
            self._low_triggered = True
            self.get_logger().warn(f"배터리 LOW: {self.percentage*100:.1f}%")
            if self._on_low:
                self._on_low(self.percentage)
        elif self.percentage > LOW_BATTERY_THRESHOLD:
            # 충전 등으로 회복되면 다시 트리거될 수 있게 리셋
            self._low_triggered = False
            self._critical_triggered = False


def nearest_safe_zone(x: float, y: float) -> dict | None:
    """VLM/RL 완전히 안 거침 -- 순수 거리 계산만 하는 결정론적 함수."""
    if not SAFE_ZONE_WAYPOINTS:
        return None
    return min(SAFE_ZONE_WAYPOINTS, key=lambda wp: (wp["x"] - x) ** 2 + (wp["y"] - y) ** 2)


def handle_low_battery(executor, costmap_node, percentage: float) -> bool:
    """트리거 콜백 -- 실제 복귀 실행. VLM/RL의 skill/coord 선택 로직은 전혀 안 씀, 순수
    NavigateToPose 한 번뿐. executor는 nav_recovery_executor.NavRecoveryExecutor,
    costmap_node는 nav2_costmap_query.CostmapQueryNode 인스턴스.

    반환값: 실제로 복귀 이동을 시도했는지(성공 여부 아님) -- 호출부(orchestrate_live_teleop.py)가
    이 값으로 "제자리에서 대기만 했는지 vs 진짜 이동 시도했는지"를 구분해 로그를 남길 수 있게.

    2026-08-12: safe_zone 좌표가 채워져서(fms_feature_points.jsonl) 실제 NavigateToPose 실행까지
    연결함. **주의**: chained_waypoint_drive.py의 waypoint 체이닝(병목 경유)은 아직 미연결 --
    지금은 safe_zone까지 직선 NavigateToPose 한 번만 시도(Nav2 planner가 알아서 장애물은
    피하지만, 병목을 반드시 통과해야 하는 경로면 실패할 수 있음, 추후 개선 과제)."""
    # 2026-08-12: 어디서 멈추는지 안 보이는 문제가 실측으로 확인돼서(ROS logger 출력이 왜인지
    # 하나도 안 남음) 매 단계 plain print()로 즉시 flush되는 진행 로그 추가함 -- 다음에 또
    # 멈추면 정확히 어느 줄에서 멈췄는지 바로 알 수 있게.
    print("  [handle_low_battery] 시작 -- get_map_pose 호출 중...", flush=True)
    from orchestrate_live_teleop import get_map_pose
    pose = get_map_pose(costmap_node)
    print(f"  [handle_low_battery] get_map_pose 반환: {pose}", flush=True)
    if pose is None:
        print("  [handle_low_battery] 실패: map pose 못 얻음", flush=True)
        return False
    x, y, _ = pose
    target = nearest_safe_zone(x, y)
    print(f"  [handle_low_battery] target 계산됨: {target}", flush=True)
    if target is None:
        print(
            "  [handle_low_battery] 실패: SAFE_ZONE_WAYPOINTS가 비어있어서 이동 안 함 -- "
            "fms_feature_points.jsonl에 safe_zone 저장부터 할 것 (fail-closed)", flush=True)
        return False
    print(f"  [handle_low_battery] NavigateToPose 호출 시작: 현재({x:.2f},{y:.2f}) -> "
          f"{target['id']}({target['x']:.2f},{target['y']:.2f}), battery={percentage*100:.1f}%",
          flush=True)
    reached = executor._call_navigate_to_pose(target["x"], target["y"], 0.0, timeout_sec=60.0)
    print(f"  [handle_low_battery] NavigateToPose 반환: reached={reached}", flush=True)
    if reached:
        print(f"  [handle_low_battery] 복귀 완료: {target['id']} 도착.", flush=True)
    else:
        print(f"  [handle_low_battery] 복귀 실패/타임아웃: {target['id']} 못 감. "
              "publish_zero_velocity로 정지는 됐을 것.", flush=True)
    return True


if __name__ == "__main__":
    # 단독 테스트용 -- 로봇 연결되면 우선 이것부터: 토픽이 실제로 오는지, percentage 필드가
    # 맞는지 눈으로 확인. Nav2/executor 없이 구독만 테스트.
    rclpy.init()
    watcher = BatteryWatcher(
        on_low_battery=lambda pct: print(f"[테스트] LOW 트리거: {pct*100:.1f}%"),
        on_critical_battery=lambda pct: print(f"[테스트] CRITICAL 트리거: {pct*100:.1f}%"),
    )
    print("배터리 토픽(/battery_publihser) 구독 중... (Ctrl+C로 종료)")
    try:
        rclpy.spin(watcher)
    except KeyboardInterrupt:
        pass
    watcher.destroy_node()
    rclpy.shutdown()
