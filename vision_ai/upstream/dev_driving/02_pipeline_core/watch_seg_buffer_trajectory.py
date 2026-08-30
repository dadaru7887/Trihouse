"""목표를 이 스크립트가 보내지 않고, 다현님이 RViz에서 "2D Goal Pose"로 직접
보내시는 동안 옆에서 관찰만 함: 연속 세그멘테이션(+trigger 라벨) + 연속 궤적 +
끝나면 buffer에 REJOIN transition 1개 기록. watch_and_buffer.py(세션 초반)의
확장판 -- 세그멘테이션/CSV export까지 다 포함."""
import sys, math, time, pickle, csv, json
sys.path.insert(0, ".")
sys.path.insert(0, "/workspace/Trihouse_segmentation/Trihouse")
from train import mixed_augmentation  # noqa: F401
from dataclasses import dataclass, field, asdict
from pathlib import Path

import requests
import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from ultralytics import YOLO

from vlm_contract_to_rl_state import AUG_WEIGHTS, segment_image

ROBOT_FRAME_URL = "http://192.168.129.37:8899/frame"
BUFFER_PATH = "./real_recovery_buffer.pkl"
TRAJECTORY_LOG_PATH = "./real_trajectory_log.pkl"
SKILL_NAMES = ["BACKUP", "REROUTE_LEFT", "REROUTE_RIGHT", "WAIT_REOBSERVE", "REJOIN"]
SAMPLE_INTERVAL_SEC = 0.15
SEG_INTERVAL_SEC = 0.2
MATCH_DIST_PX = 90
TRACK_WINDOW = 5
AREA_GROWTH_RATIO = 0.15
GRACE_FRAMES = 10
CONFIRM_FRAMES = 2
WATCH_SEC = 40.0


class ObjectWatcher:
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


class Watcher(Node):
    def __init__(self):
        super().__init__("watch_seg_buffer_trajectory")
        self.odom = None
        self.create_subscription(Odometry, "/odom", self._cb, 10)

    def _cb(self, msg):
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
    frame_path = f"./watch_frame_{frame_idx}.jpg"
    with open(frame_path, "wb") as f:
        f.write(resp.content)
    fetch_time = time.time() - t0
    t1 = time.time()
    detections, (w, h) = segment_image(seg_model, frame_path)
    infer_time = time.time() - t1
    return fetch_time, infer_time, detections


def main(watch_sec=WATCH_SEC):
    rclpy.init()
    node = Watcher()

    print("odom 대기...")
    for _ in range(30):
        rclpy.spin_once(node, timeout_sec=0.3)
        if node.odom is not None:
            break
    p0 = node.pose()
    print(f"시작 위치: {p0}")

    print("세그멘테이션 모델 로딩...")
    seg_model = YOLO(AUG_WEIGHTS)
    session = requests.Session()
    watcher = ObjectWatcher()

    print(f"\n{watch_sec}초 동안 관찰만 함 (다현님이 RViz에서 목표 보내주세요)...")
    poses = []
    seg_log = []
    frame_idx = 0
    n_trigger_labels = 0
    t0 = time.time()
    last_traj = 0.0
    last_seg = 0.0
    while time.time() - t0 < watch_sec:
        rclpy.spin_once(node, timeout_sec=0.03)
        now = time.time()
        if now - last_traj >= SAMPLE_INTERVAL_SEC:
            p = node.pose()
            if p is not None:
                poses.append((now, p[0], p[1], p[2]))
            last_traj = now
        if now - last_seg >= SEG_INTERVAL_SEC:
            try:
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
                print(f"  [{now - t0:5.1f}s] seg: det={len(detections)}개, pos={cur_pose}{trig_str}")
                frame_idx += 1
            except Exception as e:
                print(f"  세그멘테이션 실패(계속): {e}")
            last_seg = now

    pf = node.pose()
    total_moved = math.hypot(pf[0] - p0[0], pf[1] - p0[1])
    print(f"\n관찰 종료. 시작 {p0} -> 끝 {pf}, 이동거리={total_moved:.3f}m")

    if len(poses) >= 2:
        path_length = sum(math.hypot(poses[i][1]-poses[i-1][1], poses[i][2]-poses[i-1][2])
                           for i in range(1, len(poses)))
        net = math.hypot(poses[-1][1]-poses[0][1], poses[-1][2]-poses[0][2])
        traj_log = PklLog(TRAJECTORY_LOG_PATH)
        traj_log.add(TrajectoryRecord(
            poses=poses, start_time=poses[0][0], end_time=poses[-1][0],
            total_path_length=path_length, net_displacement=net,
            meta={"source": "watch_seg_buffer_trajectory(manual_rviz)", "n_samples": len(poses)},
        ))
        traj_log.save()
        print(f"궤적 저장: {len(poses)}개 샘플, 누적경로={path_length:.3f}m, 직선거리={net:.3f}m")

        with open("./watch_trajectory.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["idx", "t_rel_s", "x", "y", "yaw"])
            for i, (tt, x, y, yaw) in enumerate(poses):
                w.writerow([i, round(tt - poses[0][0], 3), round(x, 4), round(y, 4), round(yaw, 4)])
        print("궤적 CSV: ./watch_trajectory.csv")

    with open("./watch_seg_log.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame_idx", "t_rel_s", "fetch_ms", "infer_ms", "n_det", "detections_json",
                    "robot_x", "robot_y", "robot_yaw", "trigger_reasons"])
        for i, s in enumerate(seg_log):
            rp = s["robot_pose"] or (None, None, None)
            w.writerow([i, round(s["t"] - t0, 3), round(s["fetch_ms"], 1), round(s["infer_ms"], 1),
                        s["n_det"], json.dumps(s["detections"], ensure_ascii=False), rp[0], rp[1], rp[2],
                        "; ".join(s["trigger_reasons"])])
    print(f"세그멘테이션 CSV: ./watch_seg_log.csv ({len(seg_log)}행, 트리거라벨 {n_trigger_labels}개)")

    if total_moved > 0.05:
        buf = PklLog(BUFFER_PATH)
        coord = [pf[0], pf[1], 0.0]
        state = [p0[0], p0[1], p0[2], pf[0], pf[1], 0.5, 0.5, 0.5, 0.5]
        next_state = [pf[0], pf[1], pf[2], pf[0], pf[1], 0.5, 0.5, 0.5, 0.5]
        buf.add(Transition(
            state=state, skill=SKILL_NAMES.index("REJOIN"), coord=coord,
            reward=total_moved, next_state=next_state, done=True,
            meta={"source": "watch_seg_buffer_trajectory(manual_rviz)", "start_pos": p0, "end_pos": pf,
                  "total_moved": total_moved, "n_seg_frames": len(seg_log), "timestamp": time.time()},
        ))
        buf.save()
        print(f"buffer 저장 완료. 총 {len(buf.items)}개")
    else:
        print("이동 거의 없어서 buffer 저장 안 함 (0.05m 미만)")

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sec", type=float, default=WATCH_SEC)
    args = parser.parse_args()
    main(args.sec)
