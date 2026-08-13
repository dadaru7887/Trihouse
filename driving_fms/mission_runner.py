#!/usr/bin/env python3
"""FMS 자동주행(1단계) 실행 스크립트. mission_goal_state_machine.py에 만든 규칙 전부
(병목/적재구역/middle_goal 혼잡 대기, 배터리 CRITICAL override+우선권, safe_zone
operator_release 게이트, ArUco 도착 게이트)를 실제로 불러써서 한 사이클(start_zone ->
적재구역(들) -> middle_goal -> end_zone)을 자동 주행한다.

**스코프: VLM/RL과 아직 연결 안 함(2026-08-13, 사용자 결정).** orchestrate_live_teleop.py의
세그멘테이션/VLM/recovery 로직은 완전히 별개 -- 이 스크립트는 순수 FMS 계층(어디로 갈지,
언제 대기할지)만 검증한다. 나중에 합칠 때는 이 파일의 MissionRunner를
orchestrate_live_teleop.py의 관찰 루프 안에서 같이 돌리는 방식이 될 것.

**DB 연동 자리(occupied_end_slots/occupied_bottlenecks/occupied_loading_zones/critical_claims)
는 전부 None으로 시작한다** -- Gateway API가 아직 없어서(db_team_requests.md 9개 후속질문
미전달) 실제 점유 신호가 없음. 대신 Trihouse repo(`db/schema_mysql.sql`)의 `reservations`
테이블이 정확히 이 용도로 이미 설계돼있는 걸 확인함(2026-08-13):
  reservation_mode='bottleneck_lock' (map_feature_id 대상) -> occupied_bottlenecks
  reservation_mode='exclusive_lock'  (location_id 대상)     -> occupied_end_slots/
                                                                occupied_loading_zones
  state IN ('reserved','in_use')가 "지금 점유 중"에 해당.
나중에 Gateway API가 이 테이블 조회 엔드포인트를 열면, MissionRunner._refresh_occupancy()에
그 쿼리 결과만 채워넣으면 됨(구조는 이미 준비됨, TODO 표시).

ArUco 카메라 연동도 아직 없음(check_aruco_detection.py를 라이브로 붙이는 건 별도 작업) --
지금은 NavigateToPose 도착 = sub_sub_midgoal_N 방문 완료로 단순화함(confirm_arrival_by_aruco를
인자 없이 id만으로 호출, 하위호환 경로).

사용법:
    python3 mission_runner.py --loading-targets 3 --zone-slot 1
    python3 mission_runner.py --loading-targets 1,2 --zone-slot 1 --speed 0.1
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node

from battery_watcher import BatteryWatcher, CRITICAL_BATTERY_THRESHOLD
from mission_goal_state_machine import MissionGoalStateMachine, Stage
from nav_recovery_executor import NavRecoveryExecutor

# 2026-08-13 새벽: trihouse_interfaces 패키지(4060 ~/Trihouse 체크아웃, git pull 후
# `colcon build --packages-select trihouse_interfaces`로 재빌드 필요 -- 8/7 이후 오래
# 안 받아서 RobotStatus/TaskEvent 메시지가 없었음)를 source해야 import 가능. 실행 전에
# `source ~/Trihouse/install/setup.bash`를 ROS2 setup.bash 다음에 추가로 source할 것.
from trihouse_interfaces.msg import (
    RobotStatus, TaskContext, TaskEvent, NavigationState,
)
# 2026-08-13 저녁: 전류(전류량) 토픽이 로봇에 없어서(battery_publihser 노드가 percent/
# voltage 둘만 발행, 실측 확인) 전압으로 대체 -- sensor_msgs/BatteryState가 percentage/
# voltage 둘 다 갖고 있는 표준 메시지라 이걸로 같이 실어 보냄. battery_policy_node.py가
# 이 타입을 `/trihouse/battery`에서 구독하는 걸 확인해서 같은 토픽/타입으로 맞춤.
from sensor_msgs.msg import BatteryState, Imu
# 2026-08-13 밤: 라이다/IMU 요약값 + 배터리 이력 리스트 -- trihouse_interfaces에 대응하는
# 필드/메시지가 없어서(§ 플랜 imu-enchanted-harbor.md) 표준 std_msgs로 잠정 발행.
from std_msgs.msg import Float32, String

DEFAULT_LINEAR_VEL = 0.15  # 2026-08-13 배터리 override 라이브 테스트에서 검증된 값 재사용
NAV_TIMEOUT_SEC = 60.0
CONGESTION_POLL_SEC = 2.0  # 병목/적재구역 대기 중 재확인 주기
POLL_INTERVAL_SEC = 0.2
# 2026-08-13 새벽: Trihouse repo의 battery_policy.py에서 CHARGE_WAIT/재진입 임계값(30%)
# 개념을 확인함 -- 복귀 임계값(10%)이랑 재진입 임계값을 다르게 둬서 배터리가 11%->9%
# 사이를 왔다갔다하며 계속 복귀/재배치를 반복하는 진동(oscillation)을 막는 히스테리시스
# 설계. 저쪽처럼 별도 상태(enum)로 안 만들고, 가장 간단하게 "출발(START) 전에 한 번만
# 체크"하는 걸로 단순화함(사용자 결정) -- 별도 CHARGE_WAIT 상태/타이머 없이 START 단계
# 진입 시점 배터리만 확인.
REENTRY_THRESHOLD = 0.30
# 2026-08-13 밤: 작업 단위 배터리 이력 리스트 상한 -- 정상 작업 소요 시간 내에서는 거의
# 도달 안 할 값이지만, 혹시 한 작업이 비정상적으로 길어져도 메모리가 무한정 안 늘어나게
# fail-safe로 상한을 둠(넘으면 가장 오래된 항목부터 버림).
BATTERY_JOB_LOG_MAX = 500


def set_speed(linear_vel: float) -> None:
    """ros2 param set을 서브프로세스로 호출 -- 오늘 하루 종일 수동으로 검증한 것과
    동일한 방식(rclpy 파라미터 클라이언트 직접 구현보다 간단하고 신뢰도 높음)."""
    subprocess.run(
        ["ros2", "param", "set", "/controller_server",
         "FollowPath.desired_linear_vel", str(linear_vel)],
        check=True, capture_output=True, text=True,
    )
    print(f"주행 속도: {linear_vel} m/s로 설정")


class StatusPublisher(Node):
    """RobotStatus/TaskEvent를 발행하는 전용 노드. **정직성 원칙**: 우리가 실제로 알고
    있는 필드(pose/battery_percentage/task_context/navigation_state)만 채우고, 모르는
    필드(cargo/safety/battery_policy 분류)는 손대지 않은 채(모두 기본값 0, 즉
    STATE_UNKNOWN/STATE_CLEAR 등)로 남김 -- **`ready`/`dispatchable`는 항상 False로
    고정**해서, 이 토픽을 보는 누구도 우리를 진짜 fleet에 배차 가능한 로봇으로 오인하지
    않게 함(2026-08-13 사용자 설계 원칙: 모르는 걸 아는 척 채우지 않는다). 실제 fleet
    편입 시점엔 safety_supervisor_node/battery_condition_node 등 진짜 소스로 이 필드들을
    채우도록 갱신해야 함(§ 모듈 docstring, project_vlm_rl_fms_db_schema_mapping.md 참고)."""

    def __init__(self, robot_id: str) -> None:
        super().__init__("mission_runner_status_publisher")
        self.robot_id = robot_id
        self.status_pub = self.create_publisher(RobotStatus, "/trihouse/robot_status", 10)
        self.event_pub = self.create_publisher(TaskEvent, "/trihouse/task_events", 10)
        self.battery_pub = self.create_publisher(BatteryState, "/trihouse/battery", 10)
        # 2026-08-13 밤: 라이다/IMU 요약값 -- trihouse_interfaces 어떤 메시지에도 대응
        # 필드가 없어서(§ 플랜 조사) 잠정 토픽명으로 std_msgs/Float32 발행. DB팀이 정식
        # 필드/토픽명 주면 이름만 바꾸면 됨.
        self.min_scan_range_pub = self.create_publisher(
            Float32, "/trihouse/sensor_summary/min_scan_range_m", 10)
        self.imu_accel_pub = self.create_publisher(
            Float32, "/trihouse/sensor_summary/imu_accel_magnitude", 10)
        # IMU는 기존 구독이 없어서 새로 추가 -- linear_acceleration 3축을 magnitude
        # 스칼라 하나로 압축(safety_supervisor_node가 라이다를 min() 하나로 줄인 것과
        # 같은 원칙).
        self.create_subscription(Imu, "/imu_raw", self._on_imu, 10)
        self._last_imu_accel_magnitude: float | None = None
        # 2026-08-13 밤: 작업(job) 단위 배터리 전압/퍼센트 이력. "감소량 계산은 저쪽 몫,
        # 원본 시계열을 모아서 통째로 넘기는 건 우리 몫" 확인(§ 플랜 Context) -- 작업
        # 할당~도착까지만 모으고 도착 시 한 번에 publish 후 리셋. 확립된 스키마가 없어서
        # JSON 문자열로 std_msgs/String에 잠정 발행.
        self.battery_job_history_pub = self.create_publisher(
            String, "/trihouse/battery/job_history", 10)
        self._battery_job_log: list[dict] = []

    def _on_imu(self, msg: Imu) -> None:
        a = msg.linear_acceleration
        self._last_imu_accel_magnitude = (a.x ** 2 + a.y ** 2 + a.z ** 2) ** 0.5

    def publish_sensor_summary(self, min_scan_range: float | None) -> None:
        """라이다 min거리(호출부가 NavRecoveryExecutor._last_scan_min_range를 넘겨줌)와
        가장 최근 IMU accel magnitude(구독으로 자체 보관 중인 값)를 요약값으로 발행.
        값을 모르면(inf/None) 발행하지 않음(모르는 값 0.0으로 채우기 금지 원칙)."""
        if min_scan_range is not None and min_scan_range != float("inf"):
            msg = Float32()
            msg.data = min_scan_range
            self.min_scan_range_pub.publish(msg)
        if self._last_imu_accel_magnitude is not None:
            msg = Float32()
            msg.data = self._last_imu_accel_magnitude
            self.imu_accel_pub.publish(msg)

    def start_battery_job_log(self) -> None:
        """새 작업 할당 시점(목적지로 이동 시작)에 호출 -- 이전 작업 이력을 비우고 새로
        쌓기 시작."""
        self._battery_job_log = []

    def record_battery_sample(self, percentage: float | None, voltage: float | None) -> None:
        """이동 중 매 주기 호출. percentage/voltage 둘 다 모르면 샘플 자체를 건너뜀."""
        if percentage is None and voltage is None:
            return
        self._battery_job_log.append({
            "t": self.get_clock().now().nanoseconds / 1e9,
            "percentage": percentage,
            "voltage": voltage,
        })
        if len(self._battery_job_log) > BATTERY_JOB_LOG_MAX:
            self._battery_job_log = self._battery_job_log[-BATTERY_JOB_LOG_MAX:]

    def publish_battery_job_log(self) -> None:
        """목적지 도착 확정 시점에 호출 -- 쌓인 이력을 한 번에 publish하고 리셋. 이력이
        비어있으면(배터리 값을 한 번도 못 읽은 경우 등) 발행 자체를 생략."""
        if not self._battery_job_log:
            return
        msg = String()
        msg.data = json.dumps(self._battery_job_log)
        self.battery_job_history_pub.publish(msg)
        self._battery_job_log = []

    def publish_battery(self, percentage: float | None, voltage: float | None) -> None:
        """전류 대신 전압으로 대체(§ 모듈 상단 주석). percentage/voltage 둘 다 모르면
        아예 발행 안 함(모르는 값을 0.0으로 채워서 "충전 0%"처럼 오독되는 걸 방지)."""
        if percentage is None and voltage is None:
            return
        msg = BatteryState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.percentage = percentage if percentage is not None else float("nan")
        msg.voltage = voltage if voltage is not None else float("nan")
        msg.current = float("nan")  # 전류 센서 없음 -- NaN으로 명시(0.0이 아님, "모름" 표시)
        msg.present = True
        self.battery_pub.publish(msg)

    def publish_status(self, x: float, y: float, battery_pct: float | None,
                        nav_state: int, fsm: MissionGoalStateMachine) -> None:
        msg = RobotStatus()
        msg.stamp = self.get_clock().now().to_msg()
        msg.robot_id = self.robot_id
        msg.software_version = "vlm_rl_mission_runner_prototype"
        msg.pose.pose.position.x = x
        msg.pose.pose.position.y = y
        msg.battery_percentage = battery_pct if battery_pct is not None else -1.0
        # battery_policy/cargo/safety: 우리가 분류/추적 안 하는 필드라 기본값(0) 유지 --
        # 아래 errors에 그 사실을 명시해서 "0이 곧 정상"으로 오독되지 않게 함.
        msg.task_context = TaskContext()  # active=False, id들 전부 0/빈값(job/dispatch 시스템 미연동)
        msg.navigation_state = nav_state
        msg.telemetry_valid = battery_pct is not None
        msg.execution_ready = False
        msg.dispatchable = False  # 진짜 fleet에 배차 가능한 로봇 아님 -- 항상 False
        msg.ready = False
        msg.errors = [
            "prototype: cargo/safety/battery_policy fields not wired to real sources",
            "prototype: not integrated with fleet job dispatch (task_context is a stub)",
        ]
        self.status_pub.publish(msg)

    def publish_task_event(self, event_type: int, target_id: str, detail: str = "") -> None:
        msg = TaskEvent()
        msg.stamp = self.get_clock().now().to_msg()
        msg.robot_id = self.robot_id
        msg.event_type = event_type
        msg.detail = f"{target_id}: {detail}" if detail else target_id
        self.event_pub.publish(msg)


class MissionRunner:
    """MissionGoalStateMachine + NavRecoveryExecutor + BatteryWatcher를 엮어서 실제로
    한 사이클을 돈다. occupied_*/critical_claims는 전부 DB Gateway API 연동 전까진 None
    (§ 모듈 docstring 매핑 참고)."""

    def __init__(self, fsm: MissionGoalStateMachine, executor: NavRecoveryExecutor,
                 battery: BatteryWatcher, ros_exec: SingleThreadedExecutor,
                 status: StatusPublisher) -> None:
        self.fsm = fsm
        self.executor = executor
        self.battery = battery
        self.ros_exec = ros_exec
        self.status = status
        # DB 연동 자리 -- TODO: Gateway API 붙으면 reservations 테이블 조회 결과로 갱신
        self.occupied_end_slots: set[int] | None = None
        self.occupied_bottlenecks: set[int] | None = None
        self.occupied_loading_zones: set[int] | None = None
        self.critical_claims: set[int] | None = None

    def _battery_critical(self) -> bool:
        return (self.battery.percentage is not None
                and self.battery.percentage <= CRITICAL_BATTERY_THRESHOLD)

    def _spin(self, seconds: float) -> None:
        t0 = time.time()
        while time.time() - t0 < seconds:
            self.ros_exec.spin_once(timeout_sec=POLL_INTERVAL_SEC)

    def _wait_out_congestion(self, target_id: str) -> None:
        """이동 전에 병목/적재구역 혼잡 체크, 풀릴 때까지 폴링. 배터리 CRITICAL이면
        둘 다 즉시 통과(우선권 점유, § mission_goal_state_machine.py 정정 이력 9/10번)."""
        while True:
            self._spin(POLL_INTERVAL_SEC)
            x, y = self.executor._get_pos()
            critical = self._battery_critical()

            bz = self.fsm.bottleneck_should_wait(x, y, self.occupied_bottlenecks, critical)
            if bz is not None:
                print(f"    병목 {bz.id} 대기 중...")
                self._spin(CONGESTION_POLL_SEC)
                continue

            if target_id.startswith("sub_sub_midgoal_"):
                n = int(target_id.rsplit("_", 1)[-1])
                if self.fsm.loading_zone_should_wait(n, self.occupied_loading_zones, critical):
                    print(f"    적재구역 {n} 혼잡 대기 중...")
                    self._spin(CONGESTION_POLL_SEC)
                    continue
            break

    def _handle_battery_override_arrival(self) -> None:
        """safe_zone(RECOVERY_RETURN, 사람 확인 필요) vs start_zone(충전소, 자동재개)에
        따라 다르게 처리 -- § mission_goal_state_machine.py 정정 이력 7번."""
        if self.fsm._battery_override_requires_operator:
            print("  safe_zone(RECOVERY_RETURN) 도착 -- 사람 확인 필요.")
            input("  점검 완료 후 Enter를 눌러 재개 (operator_release)...")
        else:
            print("  start_zone(충전소) 도착 -- 배터리 문제일 뿐이라 자동재개.")
        self.fsm.operator_release()  # resume_stage 기본값 START -- 처음부터 다시 시작

    def run_one_cycle(self) -> bool:
        """START -> LOADING(들) -> DELIVERING -> END 한 바퀴. 실패하면 그 자리에서 즉시
        중단(fail-closed). 반환값: 전체 사이클 성공 여부."""
        total_loading = len(self.fsm._loading_targets)
        visited_loading = 0

        while self.fsm.stage != Stage.END:
            self._spin(POLL_INTERVAL_SEC)
            x, y = self.executor._get_pos()
            self.status.publish_status(x, y, self.battery.percentage,
                                        NavigationState.STATE_ACTIVE, self.fsm)
            self.status.publish_battery(self.battery.percentage, self.battery.voltage)
            self.status.publish_sensor_summary(self.executor._last_scan_min_range)
            self.status.record_battery_sample(self.battery.percentage, self.battery.voltage)
            critical = self._battery_critical()
            if critical and self.fsm.stage != Stage.BATTERY_OVERRIDE:
                print(f"  !!! 배터리 CRITICAL({self.battery.percentage * 100:.0f}%) -- override 시작")

            if self.fsm.stage == Stage.START and self.battery.percentage is not None:
                if self.battery.percentage < REENTRY_THRESHOLD:
                    print(f"  배터리 재진입 임계값 미달({self.battery.percentage * 100:.0f}% "
                          f"< {REENTRY_THRESHOLD * 100:.0f}%) -- 출발 보류, 대기")
                    self._spin(CONGESTION_POLL_SEC)
                    continue

            target = self.fsm.current_target(
                x, y, battery_low=critical, occupied_end_slots=self.occupied_end_slots)
            if not target.ready:
                print(f"  !! '{target.id}' 좌표 미확정 -- 중단 (fail-closed)")
                return False

            if target.id == "middle_goal_wait_in_place":
                print("  middle_goal 1/2 둘 다 혼잡 -- 제자리 대기 후 재확인")
                self._spin(CONGESTION_POLL_SEC)
                continue

            self._wait_out_congestion(target.id)

            print(f"  [{self.fsm.stage.name}] 현재({x:.2f},{y:.2f}) -> {target.id}"
                  f"({target.x:.2f},{target.y:.2f})")
            self.status.publish_task_event(TaskEvent.EVENT_STARTED, target.id)
            self.status.start_battery_job_log()  # 새 작업(이동 구간) 시작 -- 이력 리셋
            reached = self.executor._call_navigate_to_pose(
                target.x, target.y, target.yaw or 0.0, timeout_sec=NAV_TIMEOUT_SEC)
            if not reached:
                print(f"  !! '{target.id}' 도착 실패 -- 중단")
                self.status.publish_task_event(TaskEvent.EVENT_FAILED, target.id, "navigate_to_pose_failed")
                self.status.publish_status(*self.executor._get_pos(), self.battery.percentage,
                                            NavigationState.STATE_FAILED, self.fsm)
                return False
            print(f"  '{target.id}' 도착 확인")
            self.status.publish_task_event(TaskEvent.EVENT_ARRIVED, target.id)
            self.status.publish_battery_job_log()  # 도착 확정 -- 이번 구간 배터리 이력 통째로 발행

            if self.fsm.stage == Stage.BATTERY_OVERRIDE:
                self._handle_battery_override_arrival()
                print("  배터리 override 처리 완료 -- 새 미션 배정 대기 상태로 종료")
                return False  # 새 loading_targets는 외부(다음 실행)에서 배정

            if self.fsm.stage == Stage.LOADING:
                # ArUco 카메라 미연동 -- 도착=방문 완료로 단순화(§ 모듈 docstring 참고)
                n = self.fsm._loading_targets[self.fsm._loading_idx]
                advanced = self.fsm.confirm_arrival_by_aruco(target.aruco_id)
                if not advanced:
                    print(f"  !! sub_sub_midgoal_{n} 진행 처리 실패 -- 중단")
                    return False
                visited_loading += 1
                print(f"  적재구역 {visited_loading}/{total_loading} 완료")
            elif self.fsm.stage == Stage.DELIVERING:
                self.fsm.mark_delivery_done()

        print(f"  [{self.fsm.stage.name}] 사이클 완료")
        x, y = self.executor._get_pos()
        self.status.publish_status(x, y, self.battery.percentage,
                                    NavigationState.STATE_SUCCEEDED, self.fsm)
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="FMS 1단계 자동주행 실행 스크립트")
    parser.add_argument("--loading-targets", default="3",
                         help="쉼표로 구분한 적재구역 번호(상온=1/냉장=2/냉동=3), 예: 1,3")
    parser.add_argument("--zone-slot", type=int, default=1, choices=(1, 2),
                         help="사용할 start_zone/end_zone 슬롯")
    parser.add_argument("--speed", type=float, default=DEFAULT_LINEAR_VEL,
                         help=f"주행 속도(m/s), 기본 {DEFAULT_LINEAR_VEL} (검증된 안전값)")
    parser.add_argument("--robot-id", default="PK_23",
                         help="RobotStatus/TaskEvent에 실릴 robot_id (예: PK_23, PK_37)")
    args = parser.parse_args()
    loading_targets = [int(t) for t in args.loading_targets.split(",") if t.strip()]

    set_speed(args.speed)

    rclpy.init()
    executor_node = NavRecoveryExecutor()
    battery = BatteryWatcher()
    status = StatusPublisher(args.robot_id)
    ros_exec = SingleThreadedExecutor()
    ros_exec.add_node(executor_node)
    ros_exec.add_node(battery)
    ros_exec.add_node(status)

    print("현재 위치(TF) 대기 중...")
    t0 = time.time()
    while time.time() - t0 < 15:
        ros_exec.spin_once(timeout_sec=POLL_INTERVAL_SEC)
        if executor_node._get_pos() != (0.0, 0.0):
            break
    x, y = executor_node._get_pos()
    print(f"시작 위치: ({x:.2f}, {y:.2f})")

    fsm = MissionGoalStateMachine(loading_targets=loading_targets, zone_slot=args.zone_slot)
    runner = MissionRunner(fsm, executor_node, battery, ros_exec, status)
    print(f"미션 시작: zone_slot={args.zone_slot}, loading_targets={loading_targets}, "
          f"robot_id={args.robot_id}")

    # NavRecoveryExecutor의 blocking spin(_send_and_wait 내부 rclpy.spin_until_future_complete)이
    # 이 노드 자체를 spin하므로 ros_exec는 위치/배터리 갱신용으로만 필요 -- Ctrl+C 시엔
    # nav_recovery_executor.py에 있는 안전 패치(goal 취소 후 재전파)가 그대로 적용됨.
    try:
        success = runner.run_one_cycle()
        print(f"\n미션 {'성공' if success else '중단됨'}")
    except KeyboardInterrupt:
        print("\n사용자 중단(Ctrl+C) -- goal 취소/정지 완료.")
        status.publish_task_event(TaskEvent.EVENT_CANCELED, fsm.current_target(
            *executor_node._get_pos()).id, "user_ctrl_c")

    executor_node.destroy_node()
    battery.destroy_node()
    status.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
