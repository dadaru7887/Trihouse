"""한 번에 멀리 안 가고, nominal waypoint를 순서대로 짧게짧게 이어가며 이동.
각 구간(hop)은 로봇 근처라 local costmap 범위 안에 확실히 들어와서 게이트를
통과하기 쉬움 -- "멀리 가려는 시도가 막히는" 문제를 우회.

전체 다구간 이동 동안 세그멘테이션+궤적은 끊김 없이 하나로 계속 기록하고,
각 hop이 끝날 때마다 buffer에 REJOIN transition을 1개씩 기록(hop = 결정 단위)."""
import sys, math, time, pickle, argparse, csv, json
sys.path.insert(0, ".")
sys.path.insert(0, "/workspace/Trihouse_segmentation/Trihouse")
from train import mixed_augmentation  # noqa: F401
from dataclasses import dataclass, field, asdict
from pathlib import Path

import requests
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from action_msgs.msg import GoalStatus
from ultralytics import YOLO

from vlm_contract_to_rl_state import AUG_WEIGHTS, segment_image
from nav2_costmap_query import CostmapQueryNode
from safe_execute import safety_gate
from nominal_trajectory import NOMINAL_WAYPOINTS, nearest_nominal_waypoint

ROBOT_FRAME_URL = "http://192.168.129.37:8899/frame"
BUFFER_PATH = "./real_recovery_buffer.pkl"
TRAJECTORY_LOG_PATH = "./real_trajectory_log.pkl"
SKILL_NAMES = ["BACKUP", "REROUTE_LEFT", "REROUTE_RIGHT", "WAIT_REOBSERVE", "REJOIN"]
SAMPLE_INTERVAL_SEC = 0.15
SEG_INTERVAL_SEC = 0.2
HOP_TIMEOUT_SEC = 30.0
MATCH_DIST_PX = 90
TRACK_WINDOW = 5
AREA_GROWTH_RATIO = 0.15
GRACE_FRAMES = 10
CONFIRM_FRAMES = 2


class ObjectWatcher:
    """VLM은 안 부르고 trigger 조건 라벨만 남김 (continuous_seg_triggered_rl.py와 동일 로직)."""

    def __init__(self):
        self.tracks = {}
        self.next_id = 0

    def update(self, detections):
        matched_ids = set()
        events = []
        for d in detections:
            cx, cy, bw, bh = d["bbox_xywh"]
            area = bw * bh
            best_id, best_dist = None, MATCH_DIST_PX
            for tid, tr in self.tracks.items():
                if tid in matched_ids:
                    continue
                last = tr["hist"][-1]
                if last["class"] != d["class"]:
                    continue
                dist = math.hypot(cx - last["cx"], cy - last["cy"])
                if dist < best_dist:
                    best_dist, best_id = dist, tid
            is_new = best_id is None
            if is_new:
                tid = self.next_id
                self.next_id += 1
                self.tracks[tid] = {"hist": [], "triggered": False, "missed": 0}
            else:
                tid = best_id
            tr = self.tracks[tid]
            tr["hist"].append({"cx": cx, "cy": cy, "area": area, "class": d["class"]})
            tr["hist"] = tr["hist"][-TRACK_WINDOW:]
            tr["missed"] = 0
            matched_ids.add(tid)
            if not tr["triggered"] and len(tr["hist"]) >= CONFIRM_FRAMES:
                reason = None
                if len(tr["hist"]) == CONFIRM_FRAMES:
                    reason = f"신규_출현_확정({d['class']},conf={d['confidence']:.2f})"
                elif d["confidence"] >= 0.5 and d["position"].split("-")[0] in ("MIDDLE", "BOTTOM"):
                    reason = f"경로상_물체({d['class']},{d['position']},conf={d['confidence']:.2f})"
                else:
                    a0, a1 = tr["hist"][0]["area"], tr["hist"][-1]["area"]
                    if a1 > a0 * (1 + AREA_GROWTH_RATIO):
                        reason = f"접근중({d['class']},면적 {a0:.0f}->{a1:.0f})"
                if reason:
                    events.append((tid, reason))
        for tid in list(self.tracks):
            if tid not in matched_ids:
                self.tracks[tid]["missed"] += 1
                if self.tracks[tid]["missed"] > GRACE_FRAMES:
                    del self.tracks[tid]
        return events

    def mark_triggered(self, tid):
        if tid in self.tracks:
            self.tracks[tid]["triggered"] = True


@dataclass
class Transition:
    state: list
    skill: int
    coord: list
    reward: float
    next_state: list
    done: bool
    meta: dict = field(default_factory=dict)


@dataclass
class TrajectoryRecord:
    poses: list
    start_time: float
    end_time: float
    total_path_length: float
    net_displacement: float
    meta: dict = field(default_factory=dict)


class PklLog:
    def __init__(self, path):
        self.path = Path(path)
        self.items = []
        if self.path.exists():
            with open(self.path, "rb") as f:
                self.items = pickle.load(f)

    def add(self, r):
        self.items.append(asdict(r))

    def save(self):
        with open(self.path, "wb") as f:
            pickle.dump(self.items, f)


class DriveNode(Node):
    def __init__(self):
        super().__init__("chained_waypoint_drive")
        self.odom = None
        self.create_subscription(Odometry, "/odom", self._odom_cb, 10)
        self.nav_client = ActionClient(self, NavigateToPose, "navigate_to_pose")

    def _odom_cb(self, msg):
        self.odom = msg

    def pose(self):
        if self.odom is None:
            return None
        p = self.odom.pose.pose.position
        q = self.odom.pose.pose.orientation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        return (p.x, p.y, yaw)


def fetch_and_segment(seg_model, session, frame_idx):
    t0 = time.time()
    resp = session.get(ROBOT_FRAME_URL, timeout=5)
    frame_path = f"./chain_frame_{frame_idx}.jpg"
    with open(frame_path, "wb") as f:
        f.write(resp.content)
    fetch_time = time.time() - t0
    t1 = time.time()
    detections, (w, h) = segment_image(seg_model, frame_path)
    infer_time = time.time() - t1
    return fetch_time, infer_time, detections


def build_hop_sequence(start_x, start_y, target_wp_id):
    """현재 위치에서 가장 가까운 waypoint부터 target_wp_id까지, NOMINAL_WAYPOINTS
    리스트 순서대로 hop 목록을 만듦 (역방향도 지원)."""
    ids = [wp["id"] for wp in NOMINAL_WAYPOINTS]
    nearest = nearest_nominal_waypoint(start_x, start_y)
    start_idx = ids.index(nearest["id"])
    target_idx = ids.index(target_wp_id)
    if target_idx >= start_idx:
        seq_idx = list(range(start_idx, target_idx + 1))
    else:
        seq_idx = list(range(start_idx, target_idx - 1, -1))
    return [NOMINAL_WAYPOINTS[i] for i in seq_idx]


def main(target_wp_id, timeout_sec=HOP_TIMEOUT_SEC):
    rclpy.init()
    node = DriveNode()
    cm_node = CostmapQueryNode()

    print("odom+costmap 대기...")
    for _ in range(30):
        rclpy.spin_once(node, timeout_sec=0.2)
        rclpy.spin_once(cm_node, timeout_sec=0.2)
        if node.odom is not None and cm_node._local is not None:
            break
    p0 = node.pose()
    print(f"시작 위치: {p0}")

    hops = build_hop_sequence(p0[0], p0[1], target_wp_id)
    print(f"hop 순서: {[h['id'] for h in hops]}")

    if not node.nav_client.wait_for_server(timeout_sec=5.0):
        print("!! navigate_to_pose 액션 서버 없음")
        node.destroy_node(); cm_node.destroy_node(); rclpy.shutdown()
        return

    print("세그멘테이션 모델 로딩...")
    seg_model = YOLO(AUG_WEIGHTS)
    session = requests.Session()

    all_poses = []
    seg_log = []
    watcher = ObjectWatcher()
    frame_idx = 0
    n_trigger_labels = 0
    rejoin_id = SKILL_NAMES.index("REJOIN")
    buf = PklLog(BUFFER_PATH)
    t_global0 = time.time()

    def continuous_tick(deadline):
        nonlocal frame_idx
        last_traj = 0.0
        last_seg = 0.0
        while time.time() < deadline[0]:
            rclpy.spin_once(node, timeout_sec=0.03)
            now = time.time()
            if now - last_traj >= SAMPLE_INTERVAL_SEC:
                p = node.pose()
                if p is not None:
                    all_poses.append((now, p[0], p[1], p[2]))
                last_traj = now
            if now - last_seg >= SEG_INTERVAL_SEC:
                try:
                    nonlocal n_trigger_labels
                    fetch_t, infer_t, detections = fetch_and_segment(seg_model, session, frame_idx)
                    cur_pose = node.pose()
                    events = watcher.update(detections)
                    for tid, _ in events:
                        watcher.mark_triggered(tid)
                    trigger_reasons = [r for _, r in events]
                    if trigger_reasons:
                        n_trigger_labels += 1
                    seg_log.append({"t": now, "fetch_ms": fetch_t * 1000, "infer_ms": infer_t * 1000,
                                     "n_det": len(detections), "detections": detections,
                                     "robot_pose": cur_pose, "trigger_reasons": trigger_reasons})
                    trig_str = f" | 트리거라벨: {', '.join(trigger_reasons)}" if trigger_reasons else ""
                    print(f"    [{now - t_global0:5.1f}s] seg: det={len(detections)}개, pos={cur_pose}{trig_str}")
                    frame_idx += 1
                except Exception as e:
                    print(f"    세그멘테이션 실패(계속): {e}")
                last_seg = now
            if deadline[1]():
                break

    for hi, wp in enumerate(hops):
        p_now = node.pose()
        print(f"\n--- hop {hi+1}/{len(hops)}: {wp['id']} ({wp['x']}, {wp['y']}) ---")

        gate = safety_gate(cm_node, rejoin_id, [wp["x"], wp["y"], p_now[2]], p_now[0], p_now[1], p_now[2])
        print(gate.summary())
        if not gate.passed:
            print(f"  게이트 막힘 -- 이 hop 스킵하고 중단")
            break

        goal = NavigateToPose.Goal()
        pose = PoseStamped()
        pose.header.frame_id = "map"
        pose.header.stamp = node.get_clock().now().to_msg()
        pose.pose.position.x = float(wp["x"])
        pose.pose.position.y = float(wp["y"])
        pose.pose.orientation.w = 1.0
        goal.pose = pose

        send_future = node.nav_client.send_goal_async(goal)
        rclpy.spin_until_future_complete(node, send_future, timeout_sec=5.0)
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            print("  목표 거부됨 -- 중단")
            break

        result_future = goal_handle.get_result_async()
        t_hop0 = time.time()
        deadline = [t_hop0 + timeout_sec, lambda: result_future.done()]
        continuous_tick(deadline)

        result = result_future.result() if result_future.done() else None
        status = result.status if result else None
        pf = node.pose()
        success = (status == GoalStatus.STATUS_SUCCEEDED)
        moved = math.hypot(pf[0]-p_now[0], pf[1]-p_now[1])
        reward = (moved if success else -1.0) - 0.1
        print(f"  hop 결과: success={success}, {p_now[:2]}->{pf[:2]}, moved={moved:.3f}m")

        state = [p_now[0], p_now[1], p_now[2], wp["x"], wp["y"], 0.5, 0.5, 0.5, 0.5]
        next_state = [pf[0], pf[1], pf[2], wp["x"], wp["y"], 0.5, 0.5, 0.5, 0.5]
        buf.add(Transition(state=state, skill=rejoin_id, coord=[wp["x"], wp["y"], p_now[2]],
                            reward=float(reward), next_state=next_state, done=True,
                            meta={"source": "chained_waypoint_drive", "hop": hi, "wp_id": wp["id"],
                                  "success": success, "nav2_status": status, "timestamp": time.time()}))
        buf.save()
        print(f"  buffer 저장: 총 {len(buf.items)}개")

        if not success:
            print("  hop 실패 -- 체인 중단")
            break

    pf_final = node.pose()
    print(f"\n=== 체인 종료. 최종 위치: {pf_final} ===")

    if len(all_poses) >= 2:
        path_length = sum(math.hypot(all_poses[i][1]-all_poses[i-1][1], all_poses[i][2]-all_poses[i-1][2])
                           for i in range(1, len(all_poses)))
        net = math.hypot(all_poses[-1][1]-all_poses[0][1], all_poses[-1][2]-all_poses[0][2])
        traj_log = PklLog(TRAJECTORY_LOG_PATH)
        traj_log.add(TrajectoryRecord(
            poses=all_poses, start_time=all_poses[0][0], end_time=all_poses[-1][0],
            total_path_length=path_length, net_displacement=net,
            meta={"source": "chained_waypoint_drive", "hops": [h["id"] for h in hops],
                  "n_samples": len(all_poses), "seg_log_len": len(seg_log)},
        ))
        traj_log.save()
        print(f"궤적 저장: {len(all_poses)}개 샘플, 누적경로={path_length:.3f}m, 직선거리={net:.3f}m")

        with open("./chain_trajectory.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["idx", "t_rel_s", "x", "y", "yaw"])
            for i, (tt, x, y, yaw) in enumerate(all_poses):
                w.writerow([i, round(tt - all_poses[0][0], 3), round(x, 4), round(y, 4), round(yaw, 4)])
        print("궤적 CSV: ./chain_trajectory.csv")

    with open("./chain_seg_log.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame_idx", "t_rel_s", "fetch_ms", "infer_ms", "n_det", "detections_json",
                    "robot_x", "robot_y", "robot_yaw", "trigger_reasons"])
        for i, s in enumerate(seg_log):
            rp = s["robot_pose"] or (None, None, None)
            w.writerow([i, round(s["t"] - t_global0, 3), round(s["fetch_ms"], 1), round(s["infer_ms"], 1),
                        s["n_det"], json.dumps(s["detections"], ensure_ascii=False), rp[0], rp[1], rp[2],
                        "; ".join(s["trigger_reasons"])])
    print(f"세그멘테이션 CSV: ./chain_seg_log.csv ({len(seg_log)}행, 트리거라벨 {n_trigger_labels}개)")

    node.destroy_node()
    cm_node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("target_wp_id", type=str, help="예: nom_2")
    parser.add_argument("--timeout", type=float, default=HOP_TIMEOUT_SEC)
    args = parser.parse_args()
    main(args.target_wp_id, args.timeout)
