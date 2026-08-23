"""teleop 주행 중 실시간 통합 검증용 오케스트레이션 스크립트.

watch_seg_buffer_trajectory.py(세그멘테이션+buffer+trajectory)를 베이스로,
- 4060 자체 화면에 실시간 세그멘테이션 결과를 cv2 창으로 띄우고
- ObjectWatcher가 트리거를 잡으면 그 프레임만 VLM(Qwen2.5-VL-3B-Instruct, 4bit)을 호출해서
  원본 문장(raw) + risk JSON을 화면/콘솔에 같이 보여준다.
VLM은 트리거가 났을 때만 호출한다 (매 프레임 호출 아님 -- 지금 목적은 오케스트레이션 배선
확인이고 실제 학습용 데이터/최종 모델 품질 검증은 5080에서 별도로 함, 그래서 여기서는
가벼운 3B를 씀).

실행은 4060 자체 터미널(로컬 디스플레이 있는 세션)에서:
    cd ~/vlm_rl_backup/Trihouse_segmentation_latest_from_5080
    source ~/.bashrc   # ROS_DOMAIN_ID=52, FASTRTPS_DEFAULT_PROFILES_FILE 반영
    ~/vlm_rl_backup/venv/bin/python3 orchestrate_live_teleop.py --sec 120
SSH 원격 세션에서 실행하면 cv2 창이 안 뜬다 (DISPLAY 없음).
"""
from __future__ import annotations

import csv
import json
import math
import pickle
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np
import requests
import rclpy
import tf2_ros
import torch
from PIL import Image
from rclpy.node import Node
from rclpy.time import Time
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from transformers import AutoProcessor, BitsAndBytesConfig, Qwen2_5_VLForConditionalGeneration
from ultralytics import YOLO

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "Trihouse"))
from train import mixed_augmentation  # noqa: F401  (체크포인트 unpickle용)
from vlm_contract_to_rl_state import (
    build_detections_text, call_vlm_contract, segment_image, vlm_json_to_state,
)
from nominal_trajectory import next_nominal_waypoint  # DB Reference Node 없을 때 goal_pos 대체
from tgrpo_sac_hierarchical_v2 import HighLevelPolicy, LowLevelPolicy
from rl_candidate_group import sample_candidate_group
from geometric_6c_lite import Candidate as GeoCandidate, estimate_candidate_reward, geometric_rollout_check
from nav2_costmap_query import CostmapQueryNode, query_keepout_violation
from nav_recovery_executor import NavRecoveryExecutor, execute_and_observe_real
from recovery_data_collector import compute_real_reward
from rclpy.executors import SingleThreadedExecutor
from battery_watcher import (
    BatteryWatcher, CRITICAL_BATTERY_THRESHOLD, LOW_BATTERY_THRESHOLD, handle_low_battery,
)

RL_CHECKPOINT_PATH = str(HERE / "sim_recovery_policy_checkpoint.pt")
CANDIDATE_K = 3  # TGRPO가 뽑는 skill 수
CANDIDATE_M = 2  # skill마다 SAC가 뽑는 좌표 수 (K*M = 6개 후보/트리거)

CANDIDATE_RADIUS_M = 1.0  # VLM의 robot_candidate_sectors(각도)를 실제 좌표로 펼칠 반경.
                          # db_team_requests.md의 Recovery Envelope(~1.5m)보다 보수적으로 시작.

KST = ZoneInfo("Asia/Seoul")


def get_map_pose(costmap_node: CostmapQueryNode) -> tuple[float, float, float] | None:
    """map 프레임 기준 로봇 pose(x,y,yaw). Watcher.pose()는 /odom(odom 프레임)이라
    RL 후보 생성/geometric_rollout_check/goal 거리 계산처럼 "map 프레임 좌표"를 가정하는
    곳에는 그대로 쓰면 안 됨(2026-08-11 발견 -- 라이브 검증 중 survivor가 거의 0으로
    나온 진짜 원인이었음: odom 좌표를 map 좌표인 것처럼 candidate 생성에 썼고, 그 위에
    nav2_costmap_query.py가 map->odom 변환을 한 번 더 해서 이중으로 어긋났었음).
    costmap_node가 이미 갖고 있는 tf_buffer(map->base_footprint)로 진짜 map 좌표를 구함."""
    try:
        tf = costmap_node.tf_buffer.lookup_transform("map", "base_footprint", Time())
    except (tf2_ros.LookupException, tf2_ros.ConnectivityException, tf2_ros.ExtrapolationException):
        return None
    t = tf.transform.translation
    q = tf.transform.rotation
    yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
    return (t.x, t.y, yaw)


def kst_run_id() -> str:
    """실행 폴더명용 KST 타임스탬프. 시스템 시간대 설정과 무관하게 항상 서울시각 사용,
    마이크로초까지 넣어서 같은 초에 여러 번 실행돼도 폴더가 안 겹치게 함."""
    return datetime.now(KST).strftime("%Y%m%d_%H%M%S_%f")

ROBOT_FRAME_URL = "http://192.168.129.23:8899/frame"
AUG_WEIGHTS = str(HERE / "weights" / "aug_best.pt")
VLM_MODEL_ID = "Qwen/Qwen2.5-VL-3B-Instruct"  # 오케스트레이션 테스트용 경량 모델 (최종 학습은 5080에서 7B로)
BUFFER_PATH = "./real_recovery_buffer.pkl"
TRAJECTORY_LOG_PATH = "./real_trajectory_log.pkl"
RUN_OUTPUT_ROOT = HERE / "runs"  # 실행마다 타임스탬프 서브폴더 하나씩 (영상 + 트리거 프레임)
SKILL_NAMES = ["BACKUP", "REROUTE_LEFT", "REROUTE_RIGHT", "WAIT_REOBSERVE", "REJOIN"]
SAMPLE_INTERVAL_SEC = 0.15
SEG_INTERVAL_SEC = 0.2
MATCH_DIST_PX = 90
TRACK_WINDOW = 5
AREA_GROWTH_RATIO = 0.15
GRACE_FRAMES = 10
CONFIRM_FRAMES = 3  # 2026-08-11 튜닝: 2는 confidence 0.25대 노이즈가 우연히 2프레임 겹치면
                    # 바로 트리거됨(실측 확인). 3으로 올려서(0.2s 간격이면 0.6초 지속) 노이즈
                    # 필터링, 블러로 confidence만 낮은 진짜 물체는 지속되니까 안 걸러짐
PATH_CONFIRM_FRAMES = 2  # 2026-08-11 추가: "경로상_물체"가 예전엔 조건 맞는 프레임 1개만
                         # 봐도 즉시 발동했음(버그 수정 전엔 실전 검증 자체가 안 됐던 부분).
                         # 신규출현과 같은 이유로 1프레임 노이즈에 안 걸리게 연속 프레임 요구.

LIDAR_TRIGGER_DISTANCE_M = 0.15  # 2026-08-11 밤: 0.35m->0.25m도 여전히 멀다고 판단됨.
                                 # 0.1m까지 고려했으나 TERMINAL_CRITICAL_DIST_M(0.085m, 이미
                                 # 충돌급)이랑 0.015m밖에 안 남아서 트리거->VLM->RL->실행
                                 # 파이프라인(수 초 소요) 반응 여유가 없어질 위험이 있어 0.15m로
                                 # 절충. 충돌 방지용 제동거리 계산이 아니라 "recovery 판단을
                                 # 시작할 인지 임계값" -- 세그멘테이션이 놓치거나 오분류해도
                                 # 순수 거리만으로 걸리는 최후 안전판.

VLM_COOLDOWN_SEC = 8.0  # 2026-08-11 실측 발견: 같은 물체에 계속 접근하는 "하나의 연속
                        # 상황"인데 "접근중"과 "거리_위험"처럼 서로 다른 조건 종류가
                        # 각각 따로 발동해서 7.6초 간격으로 VLM이 두 번 불린 사례 확인됨.
                        # VLM 호출 직후 이 시간 동안은 새 트리거가 나도 VLM 재호출 안 하고
                        # 대기(트리거 자체는 로그에 계속 남김) -- 같은 상황 중복 판단 방지.

WATCH_SEC = 120.0


# ---------------------------------------------------------------------------
# ObjectWatcher: watch_seg_buffer_trajectory.py와 동일 로직 재사용
# ---------------------------------------------------------------------------
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
                # 버그 수정(2026-08-11): 예전엔 triggered: bool 하나라 "신규출현"이 뜨자마자
                # 트랙 전체가 영구 잠겨서 "경로상_물체"/"접근중"이 같은 트랙에서 절대 못
                # 떴음(elif 체인이라 사실상 죽은 코드였음). 조건별로 따로 "한 번씩만" 뜨게
                # set으로 관리.
                self.tracks[tid] = {"hist": [], "triggered_kinds": set(), "missed": 0, "path_streak": 0}
            else:
                tid = best_id
            tr = self.tracks[tid]
            tr["hist"].append({"cx": cx, "cy": cy, "area": area, "class": d["class"]})
            tr["hist"] = tr["hist"][-TRACK_WINDOW:]
            tr["missed"] = 0
            matched_ids.add(tid)

            # 2026-08-11 밤: --execute 모드로 실제 recovery 실행해보니, 이 조건이 지속 프레임
            # 수만 보고 거리/크기는 전혀 안 봐서 화면 위쪽에 작게(멀리) 스쳐가는 물체까지
            # recovery를 발동시키는 게 확인됨(사용자 지적 + 트리거 프레임 이미지로 실측 확인 --
            # TOP 위치+작은 bbox인데도 트리거됨). "경로상_물체"처럼 TOP 제외(MIDDLE/BOTTOM만
            # 인정)해서 실제로 가까운 것만 신규출현으로 잡게 함.
            # close_enough 게이트를 추가하면서 ==를 >=로 바꿈: 원래 ==였던 건 "정확히
            # CONFIRM_FRAMES번째 프레임"이라는 단 한 번의 기회뿐이라, 그 순간 마침 TOP(멀음)
            # 이면 나중에 가까워져도(MIDDLE/BOTTOM) 영영 트리거 못 하는 사각지대가 생김.
            # triggered_kinds가 이미 중복 발동을 막아주므로 >=로 바꿔도 여러 번 안 뜸.
            close_enough = d["position"].split("-")[0] in ("MIDDLE", "BOTTOM")
            if (len(tr["hist"]) >= CONFIRM_FRAMES and close_enough
                    and "new" not in tr["triggered_kinds"]):
                tr["triggered_kinds"].add("new")
                events.append((tid, f"신규_출현_확정({d['class']},conf={d['confidence']:.2f})"))

            path_condition_met = (d["confidence"] >= 0.5
                                   and d["position"].split("-")[0] in ("MIDDLE", "BOTTOM"))
            tr["path_streak"] = tr["path_streak"] + 1 if path_condition_met else 0
            if ("path" not in tr["triggered_kinds"] and tr["path_streak"] >= PATH_CONFIRM_FRAMES):
                tr["triggered_kinds"].add("path")
                events.append((tid, f"경로상_물체({d['class']},{d['position']},"
                                     f"conf={d['confidence']:.2f})"))

            if "approach" not in tr["triggered_kinds"] and len(tr["hist"]) >= 2:
                a0, a1 = tr["hist"][0]["area"], tr["hist"][-1]["area"]
                if a1 > a0 * (1 + AREA_GROWTH_RATIO):
                    tr["triggered_kinds"].add("approach")
                    events.append((tid, f"접근중({d['class']},면적 {a0:.0f}->{a1:.0f})"))
        for tid in list(self.tracks):
            if tid not in matched_ids:
                self.tracks[tid]["missed"] += 1
                if self.tracks[tid]["missed"] > GRACE_FRAMES:
                    del self.tracks[tid]
        return events


@dataclass
class Transition:
    state: list
    skill: int
    coord: list
    reward: float
    next_state: list
    done: bool
    candidates: list = field(default_factory=list)  # [{"x","y","angle_deg","preference"}, ...] 전체 후보
    meta: dict = field(default_factory=dict)


def sectors_to_candidates(vlm_json: dict, robot_pose: tuple[float, float, float],
                           radius_m: float = CANDIDATE_RADIUS_M) -> list[dict]:
    """VLM JSON의 robot_candidate_sectors(현재 heading 기준 상대각도+선호도)를 map frame
    (x,y) 후보 좌표로 변환. §6 "후보 생성"의 첫 소스 -- recovery_filters.py의 Candidate와
    같은 목적(x,y,yaw 튜플들)이지만, 여기선 VLM 원본 sector 정보(angle_deg, preference)도
    같이 남겨서 나중에 필터/디버깅에 쓸 수 있게 함. 선호도(preference) 내림차순 정렬."""
    rx, ry, ryaw = robot_pose
    sectors = vlm_json.get("robot_candidate_sectors", [])
    candidates = []
    for s in sectors:
        angle_deg = float(s.get("angle_deg", 0.0))
        preference = float(s.get("preference", 0.0))
        global_angle = ryaw + math.radians(angle_deg)  # angle_deg는 현재 heading 기준 상대각(0=전방)
        cx = rx + radius_m * math.cos(global_angle)
        cy = ry + radius_m * math.sin(global_angle)
        candidates.append({"x": cx, "y": cy, "angle_deg": angle_deg, "preference": preference})
    candidates.sort(key=lambda c: c["preference"], reverse=True)
    return candidates


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


# ---------------------------------------------------------------------------
# 브라우저로 보는 실시간 세그멘테이션 스트림 (pinky_camera_server.py와 같은 MJPEG 패턴,
# 원본 카메라 대신 세그멘테이션+트리거+VLM 문장이 그려진 결과 프레임을 내보냄)
# ---------------------------------------------------------------------------
STREAM_PORT = 8900
_latest_jpeg: bytes | None = None
_latest_jpeg_lock = threading.Lock()
BOUNDARY = "frame"


def set_latest_frame(bgr_img) -> None:
    global _latest_jpeg
    ok, jpg = cv2.imencode(".jpg", bgr_img)
    if ok:
        with _latest_jpeg_lock:
            _latest_jpeg = jpg.tobytes()


class MJPEGViewHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/", "/stream.mjpg"):
            self.send_response(404)
            self.end_headers()
            return
        if self.path == "/":
            body = b"<html><body style='margin:0;background:#111'><img src='/stream.mjpg'></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
        self.end_headers()
        try:
            while True:
                with _latest_jpeg_lock:
                    data = _latest_jpeg
                if data is None:
                    time.sleep(0.05)
                    continue
                self.wfile.write(f"--{BOUNDARY}\r\n".encode())
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(data)}\r\n\r\n".encode())
                self.wfile.write(data)
                self.wfile.write(b"\r\n")
                time.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass


def start_stream_server(port: int = STREAM_PORT) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), MJPEGViewHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"실시간 세그멘테이션 뷰: http://<이 4060 IP>:{port}/ 에서 브라우저로 열기")


class Watcher(Node):
    def __init__(self):
        super().__init__("orchestrate_live_teleop")
        self.odom = None
        self.scan = None
        self.create_subscription(Odometry, "/odom", self._cb, 10)
        self.create_subscription(LaserScan, "/scan", self._scan_cb, 10)

    def _cb(self, msg):
        self.odom = msg

    def _scan_cb(self, msg):
        self.scan = msg

    def pose(self):
        if self.odom is None:
            return None
        p = self.odom.pose.pose.position
        q = self.odom.pose.pose.orientation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        return (p.x, p.y, yaw)

    def min_range_forward(self, cone_deg: float = 75.0) -> float | None:
        """LiDAR 기준 정면 +-cone_deg 범위 안의 최소 거리(m). 트리거 임계값을 bbox 크기
        추측이 아니라 실제 거리로 캘리브레이션하기 위한 것 -- angle=0이 정면이라는 가정은
        미검증(로봇을 정면 장애물에 접근시키면서 이 값이 실제로 줄어드는지로 검증됨).

        2026-08-11 30도->75도로 넓힘: 실측에서 화면 가장자리(카메라 시야각 안, LiDAR 정면
        좁은 콘 밖)에 있던 물체(레고, 파란 기둥)가 눈으로는 가까운데 LiDAR는 먼 거리로
        나오는 불일치 발견 -- 카메라 시야각이 30도보다 넓어서 생긴 문제로 추정, 카메라
        FOV에 맞춰 코너까지 커버하도록 확장. 스캔 없으면 None."""
        if self.scan is None:
            return None
        cone_rad = math.radians(cone_deg)
        best = None
        for i, r in enumerate(self.scan.ranges):
            ang = self.scan.angle_min + i * self.scan.angle_increment
            if -cone_rad <= ang <= cone_rad:
                if (r == r and r != float("inf")  # NaN/inf 제외 (r==r은 NaN이면 False)
                        and self.scan.range_min <= r <= self.scan.range_max):
                    if best is None or r < best:
                        best = r
        return best


def fetch_frame(session, frame_idx):
    resp = session.get(ROBOT_FRAME_URL, timeout=5)
    frame_path = f"./watch_frame_{frame_idx}.jpg"
    with open(frame_path, "wb") as f:
        f.write(resp.content)
    return frame_path


def draw_overlay(frame_path, detections, trigger_reasons, vlm_text=None, winner_text=None,
                  battery_text=None, battery_level=None):
    """battery_level: None(정상) / "low" / "critical". 2026-08-12: 텍스트만으론 LOW/CRITICAL
    구분이 잘 안 된다는 피드백 -- 색+깜빡임 속도를 다르게 해서 텍스트 안 읽어도 직관적으로
    구분되게 함(흔한 경고등 관례: 노랑=주의/느림, 빨강=위급/빠름)."""
    img = cv2.imread(frame_path)
    if battery_level == "low":
        color, hz = (0, 165, 255), 1.0  # 주황, 1초 간격(느림)
    elif battery_level == "critical":
        color, hz = (0, 0, 255), 4.0  # 빨강, 0.25초 간격(빠름)
    else:
        color, hz = None, None
    if color is not None:
        # 시간 기반 토글이라 별도 상태 안 들고 다녀도 됨(무조건 wall clock으로 on/off 판정).
        if int(time.time() * hz) % 2 == 0:
            h, w = img.shape[:2]
            cv2.rectangle(img, (0, 0), (w - 1, h - 1), color, 12)
    for d in detections:
        cx, cy, bw, bh = d["bbox_xywh"]
        x0, y0 = int(cx - bw / 2), int(cy - bh / 2)
        x1, y1 = int(cx + bw / 2), int(cy + bh / 2)
        color = (0, 0, 255) if trigger_reasons else (0, 200, 0)
        cv2.rectangle(img, (x0, y0), (x1, y1), color, 2)
        label = f"{d['class']} {d['confidence']:.2f} {d['position']}"
        cv2.putText(img, label, (x0, max(0, y0 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    y = 20
    for r in trigger_reasons:
        cv2.putText(img, f"TRIGGER: {r}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
        y += 22
    if winner_text:  # 참고 표시용 -- 이거 보고 따라 운전하지 말고 자유롭게 주행할 것
        cv2.putText(img, f"WINNER: {winner_text}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
    if vlm_text:
        # 문장이 길 수 있어 창 하단에 여러 줄로 wrap
        h, w = img.shape[:2]
        y2 = h - 10
        wrapped = [vlm_text[i:i + 60] for i in range(0, len(vlm_text), 60)][-4:]
        for line in reversed(wrapped):
            cv2.putText(img, line, (10, y2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 0), 1)
            y2 -= 18
    if battery_text:
        # VLM 트리거 여부와 무관하게 항상 보여야 하는 상태라 다른 오버레이 다 그린 뒤 맨
        # 위(우상단)에 그려서 안 가려지게 함. 빨간색 굵게 -- 눈에 잘 띄어야 하는 안전 정보.
        h, w = img.shape[:2]
        (tw, _), _ = cv2.getTextSize(battery_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.putText(img, battery_text, (w - tw - 10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 0, 255), 2)
    return img


def simple_obstacle_trigger(detections):
    """트리거 fallback: ObjectWatcher의 신규출현/경로상/접근중 휴리스틱이 잘 안 잡히면,
    'obstacle 클래스가 감지되면 무조건 트리거'로 단순화해서 오케스트레이션(VLM 호출 ->
    buffer/궤적 기록)이 배선상 제대로 도는지부터 확인하는 용도. 트리거 조건 자체의 정교함은
    나중에 별도로 다듬는다."""
    return [f"obstacle_detected({d['class']},conf={d['confidence']:.2f})"
            for d in detections if d["class"] == "obstacle"]


def main(watch_sec=WATCH_SEC, simple_trigger=False, use_vlm=True, execute_recovery=False,
         force_critical_battery_after=None):
    run_dir = RUN_OUTPUT_ROOT / kst_run_id()
    trigger_frames_dir = run_dir / "trigger_frames"
    trigger_frames_dir.mkdir(parents=True, exist_ok=True)
    video_path = run_dir / "run_video.mp4"
    video_writer = None  # 첫 프레임 크기 확인 후 초기화 (아래 루프에서)
    video_fps = 1.0 / SEG_INTERVAL_SEC
    print(f"이번 실행 결과 폴더: {run_dir}")

    rclpy.init()
    node = Watcher()
    # 2026-08-12: costmap_node/nav_executor를 use_vlm/execute_recovery 여부와 무관하게 항상
    # 생성하도록 변경 -- 배터리 비상복귀는 VLM/RL 실행 여부와 완전히 독립적으로 항상 동작해야
    # 하는데(§ 결정론적 모듈 설계), 이전엔 --no-vlm(관찰 전용) 모드에서 nav_executor 자체가
    # 없어서 배터리 CRITICAL이 떠도 실제 복귀를 못 하는 문제가 있었음. RL 후보 실행 경로는
    # 여전히 execute_recovery 플래그로만 게이팅되므로(707번째 줄 부근) 이 변경으로 다른 동작은
    # 안 바뀜.
    costmap_node = CostmapQueryNode()
    nav_executor = NavRecoveryExecutor()

    # 2026-08-12: LOW(20%)는 화면 경고만, CRITICAL(10%)만 실제 복귀 이동 + 관찰 루프 중단.
    # 배터리 감시는 VLM/트리거 여부와 완전히 무관하게 항상 켜둠(세그멘테이션만 도는 상태여도
    # 배터리는 계속 봐야 하니까).
    battery_critical_flag = {"triggered": False}

    def _on_battery_low(pct: float) -> None:
        print(f"    ⚠️ 배터리 LOW({pct*100:.0f}%) -- 화면 경고만, 계속 관찰 진행")

    def _on_battery_critical(pct: float) -> None:
        print(f"    !!! 배터리 CRITICAL({pct*100:.0f}%) -- 관찰 루프 중단하고 Safe Zone으로 복귀 !!!")
        battery_critical_flag["triggered"] = True

    battery_watcher = BatteryWatcher(on_low_battery=_on_battery_low,
                                      on_critical_battery=_on_battery_critical)

    # 2026-08-11: costmap_node/nav_executor 둘 다 자기 TF listener를 갖고 있어서, 노드별로
    # rclpy.spin_once()를 따로따로 부르면 map(TF)를 안정적으로 못 받는 문제를 smoke_test_full_
    # cycle.py에서 발견함 -- 하나의 SingleThreadedExecutor에 다 등록해서 같이 spin하면 해결됨.
    ros_exec = SingleThreadedExecutor()
    ros_exec.add_node(node)
    ros_exec.add_node(battery_watcher)
    if costmap_node is not None:
        ros_exec.add_node(costmap_node)
    if nav_executor is not None:
        ros_exec.add_node(nav_executor)

    print("odom 대기...")
    for _ in range(60):
        ros_exec.spin_once(timeout_sec=0.3)
        if node.odom is not None:
            break
    p0 = node.pose()
    print(f"시작 위치: {p0}")

    print("세그멘테이션 모델 로딩...")
    seg_model = YOLO(AUG_WEIGHTS)

    vlm_model = vlm_processor = None
    if use_vlm:
        print(f"VLM 로딩... ({VLM_MODEL_ID})")
        quant_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                           bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
        vlm_processor = AutoProcessor.from_pretrained(VLM_MODEL_ID)
        vlm_model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            VLM_MODEL_ID, quantization_config=quant_config, device_map="cuda")
        vlm_model.eval()
        print("VLM 로딩 완료.")

        print(f"RL 정책 로딩... ({RL_CHECKPOINT_PATH})")
        rl_ckpt = torch.load(RL_CHECKPOINT_PATH, map_location="cuda", weights_only=False)
        high_policy = HighLevelPolicy().to("cuda")
        low_policy = LowLevelPolicy().to("cuda")
        high_policy.load_state_dict(rl_ckpt["high_policy"])
        low_policy.load_state_dict(rl_ckpt["low_policy"])
        print("RL 정책 로딩 완료 (2026-08-11 기준: sim 8-transition짜리 거의 미학습 상태, "
              "후보 품질은 낮을 수 있음 -- 배선 검증이 목적)")
    else:
        high_policy = low_policy = None
        print("--no-vlm: VLM/RL 안 씀 -- 세그멘테이션+트리거 관찰만 (트리거 튜닝용, buffer도 안 쌓임)")

    session = requests.Session()
    watcher = ObjectWatcher()
    buf = PklLog(BUFFER_PATH)  # 트리거마다 바로 추가+저장 (세션 끝까지 안 기다림)

    start_stream_server()
    if simple_trigger:
        print("⚠️  단순 트리거 모드: obstacle 감지되면 무조건 트리거 (오케스트레이션 배선 확인용)")

    print(f"\n{watch_sec}초 동안 teleop 주행하면서 관찰... (조종은 네가 직접, 별도 teleop 창에서)")
    poses = []
    seg_log = []
    # 2026-08-11 밤: 예전엔 CSV를 루프 끝난 뒤 한 번에 썼는데, Ctrl+C가 KeyboardInterrupt로
    # 안 잡히고 더 거칠게(터미널 강제종료 등) 끊긴 경우 통째로 유실됨(실제로 한 번 겪음).
    # 매 프레임마다 즉시 append하는 방식으로 변경 -- buf.save()가 트리거마다 즉시 저장하는
    # 것과 같은 원칙.
    seg_csv_path = Path("./watch_seg_log.csv")
    with open(seg_csv_path, "w", newline="") as f_init:
        csv.writer(f_init).writerow(["frame_idx", "t_rel_s", "n_det", "detections_json", "robot_x",
                                      "robot_y", "robot_yaw", "lidar_range_m", "trigger_reasons", "vlm_raw"])
    frame_idx = 0
    n_trigger_labels = 0
    n_vlm_calls = 0
    t0 = time.time()
    last_traj = 0.0
    last_seg = 0.0
    lidar_in_danger_zone = False  # LIDAR_TRIGGER_DISTANCE_M 진입 "순간"에만 발동시키기 위한
                                   # 상태 -- 계속 가까이 붙어있는 동안 매 프레임 VLM 스팸 안 되게
    last_vlm_call_time = None  # VLM_COOLDOWN_SEC 판단용
    last_vlm_n_det = None      # 쿨다운 중이어도 감지 개수가 바뀌면(=다른 상황일 가능성)
                                # 예외적으로 다시 호출하기 위한 비교값
    last_winner_text = None    # 화면 참고 표시용(따라 운전하지 말 것) -- 다음 트리거 전까지 유지
    try:
        while time.time() - t0 < watch_sec and not battery_critical_flag["triggered"]:
            ros_exec.spin_once(timeout_sec=0.03)
            now = time.time()
            if (force_critical_battery_after is not None
                    and now - t0 >= force_critical_battery_after
                    and not battery_critical_flag["triggered"]):
                print(f"    !!! (테스트) {force_critical_battery_after:.0f}초 경과 -- CRITICAL "
                      f"배터리 강제 시뮬레이션, 실제 배터리 값과 무관 !!!")
                battery_critical_flag["triggered"] = True
            if now - last_traj >= SAMPLE_INTERVAL_SEC:
                p = node.pose()
                if p is not None:
                    poses.append((now, p[0], p[1], p[2]))
                last_traj = now
            if now - last_seg >= SEG_INTERVAL_SEC:
                try:
                    frame_path = fetch_frame(session, frame_idx)
                    detections, (w, h) = segment_image(seg_model, frame_path)
                    cur_pose = node.pose()
                    if simple_trigger:
                        trigger_reasons = simple_obstacle_trigger(detections)
                    else:
                        events = watcher.update(detections)  # 트랙별 트리거 종류 기록은 update() 내부에서 처리
                        trigger_reasons = [r for _, r in events]

                    # LiDAR 거리 기반 트리거 -- 세그멘테이션 결과와 무관한 별도 안전판.
                    # danger zone에 "막 진입한 순간"에만 발동(계속 붙어있어도 매 프레임 재발동 안 함).
                    lidar_range = node.min_range_forward()
                    lidar_danger_now = lidar_range is not None and lidar_range < LIDAR_TRIGGER_DISTANCE_M
                    if lidar_danger_now and not lidar_in_danger_zone:
                        trigger_reasons = trigger_reasons + [f"거리_위험(lidar={lidar_range:.2f}m)"]
                    lidar_in_danger_zone = lidar_danger_now

                    vlm_raw = None
                    vlm_json = None
                    if trigger_reasons:
                        n_trigger_labels += 1
                    if trigger_reasons and not use_vlm:
                        print(f"\n>>> 트리거 발생: {trigger_reasons} (--no-vlm: VLM 호출 생략)")

                    # 쿨다운 판단: 마지막 VLM 호출 후 VLM_COOLDOWN_SEC 안 지났고, 감지 개수도
                    # 그때와 같으면(=같은 상황이 계속되는 중일 가능성) 재호출 생략. 감지 개수가
                    # 달라지면(새 물체 등장/기존 물체 소실 등) 쿨다운 중이어도 예외적으로 호출.
                    n_det_now = len(detections)
                    in_cooldown = (
                        last_vlm_call_time is not None
                        and (now - last_vlm_call_time) < VLM_COOLDOWN_SEC
                        and n_det_now == last_vlm_n_det
                    )
                    if trigger_reasons and use_vlm and in_cooldown:
                        print(f"\n>>> 트리거 발생: {trigger_reasons} -- 쿨다운 중"
                              f"(마지막 호출 {now - last_vlm_call_time:.1f}s 전, det수 동일={n_det_now}) "
                              f"-- VLM 재호출 생략")
                    if trigger_reasons and use_vlm and not in_cooldown:
                        print(f"\n>>> 트리거 발생: {trigger_reasons} -- VLM 호출 중...")
                        t_vlm = time.time()
                        image = Image.open(frame_path).convert("RGB")
                        vlm_json, vlm_raw = call_vlm_contract(vlm_model, vlm_processor, image, detections)
                        n_vlm_calls += 1
                        last_vlm_call_time = now
                        last_vlm_n_det = n_det_now
                        print(f"    VLM 응답({time.time()-t_vlm:.1f}s): {vlm_raw}")

                        map_pose = get_map_pose(costmap_node) if costmap_node is not None else None
                        if vlm_json is not None and map_pose is not None:
                            print(f"    파싱된 JSON: {json.dumps(vlm_json, ensure_ascii=False)}")

                            goal_wp = next_nominal_waypoint(map_pose[0], map_pose[1])
                            state = vlm_json_to_state(
                                vlm_json, robot_pos=(map_pose[0], map_pose[1]), robot_yaw=map_pose[2],
                                goal_pos=(goal_wp["x"], goal_wp["y"]), img_wh=(w, h))

                            # 2026-08-11: VLM의 robot_candidate_sectors 대신 RL(TGRPO-SAC)
                            # 정책이 state 보고 K*M개 후보를 샘플링(§6.1) -> 6C-Lite 필터링(2멤버
                            # 앙상블: (a) geometric_rollout_check -- local_costmap(실시간 LiDAR)
                            # 우선 + 직선 보간, (b) query_nav2_path_feasible -- Nav2 planner_server의
                            # 실제 경로 탐색(global_costmap 기반). 둘 다 완전 독립은 아니지만(결국
                            # Nav2 costmap 계열 데이터) 데이터 소스(실시간 vs 정적)와 경로 가정
                            # (직선 근사 vs 실제 탐색)이 달라 의미 있는 disagreement가 남. 둘 다
                            # 통과해야 survivor -- risk_upper_bound/std는 아직 이진 판정이라 못 쓰고,
                            # 살아남은 것 중 목표에 가까운 순으로 우승 선정(§8.1 사전식 정렬의 축소판).
                            rl_candidates = sample_candidate_group(
                                high_policy, low_policy, state, map_pose,
                                k=CANDIDATE_K, m=CANDIDATE_M)

                            survivors = []
                            n_disagree = 0
                            candidate_reward_estimates = []  # 2026-08-12: TGRPO live-rollout 대체용
                            # 1단계 로그 -- 학습엔 아직 안 씀, 실제 reward와 상관관계 검증 전까지 관찰 전용
                            for i, rc in enumerate(rl_candidates):
                                geo_cand = GeoCandidate(
                                    candidate_id=f"{rc.skill_name}_{i}", x=rc.map_x, y=rc.map_y,
                                    yaw=rc.map_yaw, map_frame="map", map_revision="rev1",
                                    footprint_class="pinky_default", source_episode_id=None,
                                    source_policy_bundle="sim_recovery_policy_checkpoint",
                                    policy_epoch=1, is_stable_bundle=True, timestamp=time.time())
                                geo_check = geometric_rollout_check(
                                    geo_cand, robot_x=map_pose[0], robot_y=map_pose[1],
                                    robot_yaw=map_pose[2],
                                    query_costmap_free=costmap_node.query_costmap_free,
                                    query_footprint_fits=costmap_node.query_footprint_fits,
                                    query_keepout_violation=query_keepout_violation)
                                nav2_ok = costmap_node.query_nav2_path_feasible(
                                    rc.map_x, rc.map_y, rc.map_yaw, timeout_sec=1.5)
                                if geo_check.passed != nav2_ok:
                                    n_disagree += 1
                                if geo_check.passed and nav2_ok:
                                    d_to_goal = math.hypot(rc.map_x - goal_wp["x"], rc.map_y - goal_wp["y"])
                                    survivors.append((rc, d_to_goal))

                                reward_est = estimate_candidate_reward(
                                    geo_cand, robot_x=map_pose[0], robot_y=map_pose[1],
                                    robot_yaw=map_pose[2],
                                    query_costmap_free=costmap_node.query_costmap_free,
                                    query_footprint_fits=costmap_node.query_footprint_fits,
                                    query_keepout_violation=query_keepout_violation,
                                    goal_x=goal_wp["x"], goal_y=goal_wp["y"])
                                candidate_reward_estimates.append({
                                    "skill_name": rc.skill_name, "x": rc.map_x, "y": rc.map_y,
                                    **reward_est,
                                })

                            if n_disagree:
                                print(f"    6C-Lite 앙상블 disagreement: {n_disagree}/{len(rl_candidates)}개 "
                                      f"(geometric != nav2_planner)")

                            if survivors:
                                survivors.sort(key=lambda pair: pair[1])  # 목표에 가까운 순
                                winner, winner_dist = survivors[0]
                                skill, coord = winner.skill, [winner.map_x, winner.map_y, winner.map_yaw]
                                # 2026-08-11 밤 버그 발견+수정: nav_recovery_executor.py의
                                # 모든 skill(BACKUP/REROUTE_LEFT/REROUTE_RIGHT/WAIT_REOBSERVE/
                                # REJOIN)이 coord를 "로봇 기준 상대 offset"으로 해석하는데(예:
                                # BACKUP은 hypot(coord[0],coord[1])을 후진거리로 씀), 여기서
                                # 절대 map 좌표를 그대로 넘기고 있었음 -- envelope 0.25m인데
                                # 실제로는 map 좌표값(최대 ~2m)만큼 움직이려 드는 심각한
                                # 버그였음("recovery가 너무 많이 간다"는 실측 증상으로 발견).
                                # (원래 REJOIN만 NavigateToPose(절대좌표)를 썼었는데, 그것도
                                # 15초씩 걸리고 실패하는 문제가 있어서 REROUTE와 같은 Spin+
                                # DriveOnHeading 방식으로 통일함 -- 이제 전부 상대 offset.)
                                exec_coord = list(winner.offset)
                                print(f"    6C-Lite: {len(rl_candidates)}개 중 {len(survivors)}개 통과, "
                                      f"우승={winner.skill_name}(목표거리 {winner_dist:.2f}m)")
                                last_winner_text = (f"{winner.skill_name} "
                                                     f"({winner.map_x:.2f},{winner.map_y:.2f},{winner.map_yaw:.2f}) "
                                                     f"[{len(survivors)}/{len(rl_candidates)} 통과, 참고용-미학습]")
                            else:
                                skill, coord = -1, [map_pose[0], map_pose[1], map_pose[2]]
                                exec_coord = coord  # skill=-1이라 실제로 안 쓰임(방어적 정의)
                                print(f"    ⚠️ 6C-Lite: {len(rl_candidates)}개 후보 전부 탈락 -- "
                                      f"안전한 후보 없음(§13 대로면 STOP 유지 상황)")
                                last_winner_text = f"NONE (0/{len(rl_candidates)} 통과)"

                            # 2026-08-11: execute_recovery=True면 우승 후보를 실제로 Nav2에
                            # 실행시키고 real reward/next_state까지 계산 (Task #2/#3). 기본값
                            # False면 지금까지처럼 관찰 스냅샷만 기록(reward=0, next_state=state
                            # placeholder) -- teleop 운전을 실제로 끊는 게 아니라서 안전.
                            reward = 0.0
                            next_state_vec = state
                            done = False
                            is_execution = False
                            exec_meta = {}
                            if execute_recovery and nav_executor is not None and skill >= 0:
                                print(f"\n    >>> {winner.skill_name} 실행 준비 -- teleop에서 손 떼고 "
                                      f"Enter (Ctrl+C면 이번 실행 취소하고 관찰만 기록)...")
                                try:
                                    input()
                                except KeyboardInterrupt:
                                    print("    실행 취소됨 -- 관찰 스냅샷만 기록.")
                                else:
                                    pre_min_range = node.min_range_forward()
                                    pre_state = {
                                        "dist_to_goal": math.hypot(map_pose[0] - goal_wp["x"],
                                                                    map_pose[1] - goal_wp["y"]),
                                        "dist_to_obstacle": pre_min_range if pre_min_range is not None else float("inf"),
                                    }
                                    post_state, terminal_critical = execute_and_observe_real(
                                        nav_executor, skill, exec_coord, pre_state)
                                    reward, reward_components = compute_real_reward(
                                        pre_state, post_state, terminal_critical)
                                    print(f"    실행 완료: reward={reward:.3f} {reward_components}")

                                    # next_state는 포지션만 patch하면 안 되고(§4.1 state의
                                    # obs_x/obs_y/obs_conf/uncertainty는 "지금 보이는 것" 기준이라
                                    # 움직인 뒤 실제로 다시 관측해야 함) -- 프레임+VLM 재호출.
                                    try:
                                        post_frame_path = fetch_frame(session, f"{frame_idx}_post")
                                        post_detections, (pw, ph) = segment_image(seg_model, post_frame_path)
                                        post_image = Image.open(post_frame_path).convert("RGB")
                                        post_vlm_json, post_vlm_raw = call_vlm_contract(
                                            vlm_model, vlm_processor, post_image, post_detections)
                                        post_map_pose = get_map_pose(costmap_node) or map_pose
                                        post_goal_wp = next_nominal_waypoint(post_map_pose[0], post_map_pose[1])
                                        if post_vlm_json is not None:
                                            next_state_vec = vlm_json_to_state(
                                                post_vlm_json, robot_pos=(post_map_pose[0], post_map_pose[1]),
                                                robot_yaw=post_map_pose[2],
                                                goal_pos=(post_goal_wp["x"], post_goal_wp["y"]), img_wh=(pw, ph))
                                        else:
                                            print("    ⚠️ next_state 재관측 VLM 파싱 실패 -- state로 대체(placeholder)")
                                    except Exception as e:
                                        print(f"    ⚠️ next_state 재관측 실패(계속): {e}")

                                    done = bool(terminal_critical)
                                    is_execution = True
                                    exec_meta = {"pre_state": pre_state, "post_state": post_state,
                                                  "terminal_critical": terminal_critical,
                                                  "reward_components": reward_components}
                                    # 2026-08-11: 쿨다운이 실행 시작 "전" 시점부터 카운트되고
                                    # 있어서, 실행+재관측(수 초)이 쿨다운을 거의 다 먹어버려
                                    # 같은 장애물이 실행 직후 바로 재트리거되는 문제 발견
                                    # (사용자가 "너무 민감하다"고 지적) -- 실행 완료 시점으로
                                    # 쿨다운 타이머를 다시 시작하게 리셋.
                                    last_vlm_call_time = time.time()
                                    print("    >>> teleop 운전 재개해도 됨.\n")

                            buf.add(Transition(
                                state=state.tolist(), skill=skill, coord=coord,
                                reward=reward, next_state=next_state_vec.tolist(), done=done,
                                candidates=[{"skill_name": rc.skill_name, "x": rc.map_x, "y": rc.map_y,
                                             "yaw": rc.map_yaw} for rc in rl_candidates],
                                meta={"source": "orchestrate_live_teleop", "trigger_reasons": trigger_reasons,
                                      "is_execution": is_execution,
                                      "note": ("실제 Nav2 실행 결과 -- RL(K*M 그룹)+6C-Lite(geometric+"
                                                "nav2_planner 2멤버 앙상블)로 우승 후보 선정 후 "
                                                "nav_recovery_executor로 실제 실행, real reward 계산됨"
                                                if is_execution else
                                                "teleop 관찰 스냅샷 -- recovery action 미실행, "
                                                "RL(K*M 그룹)+6C-Lite(geometric+nav2_planner 2멤버 "
                                                "앙상블)로 우승 후보 선정 기록(체크포인트 거의 미학습, "
                                                "배선 검증 목적)"),
                                      "goal_waypoint": goal_wp["id"], "vlm_raw": vlm_raw,
                                      "n_candidates": len(rl_candidates), "n_survivors": len(survivors),
                                      "n_disagree": n_disagree,
                                      # 2026-08-12: TGRPO live-rollout 대체 1단계 -- K*M 후보
                                      # 전부의 추정 reward(geometric_6c_lite.estimate_candidate_
                                      # reward). 아직 학습엔 안 씀, 나중에 실제 reward(위
                                      # exec_meta의 'reward_components')와 상관관계 확인용.
                                      "candidate_reward_estimates": candidate_reward_estimates,
                                      "timestamp": time.time(), **exec_meta},
                            ))
                            buf.save()
                            print(f"    buffer 추가: skill={SKILL_NAMES[skill] if skill >= 0 else 'NONE'}, "
                                  f"coord={coord} -> 총 {len(buf.items)}개")
                        else:
                            print("    ⚠️ JSON 파싱 실패 또는 pose 없음 (raw 텍스트만 로그에 남김)")

                    seg_log.append({"t": now, "n_det": len(detections), "detections": detections,
                                     "robot_pose": cur_pose, "trigger_reasons": trigger_reasons,
                                     "vlm_raw": vlm_raw, "vlm_json": vlm_json, "lidar_range_m": lidar_range})
                    with open(seg_csv_path, "a", newline="") as f_csv:
                        rp = cur_pose or (None, None, None)
                        csv.writer(f_csv).writerow([
                            frame_idx, round(now - t0, 3), len(detections),
                            json.dumps(detections, ensure_ascii=False), rp[0], rp[1], rp[2],
                            round(lidar_range, 3) if lidar_range is not None else "",
                            "; ".join(trigger_reasons), vlm_raw or ""])

                    lidar_str = f", lidar={lidar_range:.2f}m" if lidar_range is not None else ""
                    trig_str = f" | 트리거: {', '.join(trigger_reasons)}" if trigger_reasons else ""
                    print(f"  [{now - t0:5.1f}s] seg: det={len(detections)}개, pos={cur_pose}{lidar_str}{trig_str}")

                    battery_text = None
                    battery_level = None
                    if battery_watcher.percentage is not None:
                        pct = battery_watcher.percentage * 100
                        if battery_watcher.percentage <= CRITICAL_BATTERY_THRESHOLD:
                            state = "복귀 필요" if battery_watcher._critical_triggered else ""
                            battery_text = f"BATTERY CRITICAL {pct:.0f}% {state}".strip()
                            battery_level = "critical"
                        elif battery_watcher.percentage <= LOW_BATTERY_THRESHOLD:
                            state = "복귀 필요" if battery_watcher._low_triggered else ""
                            battery_text = f"BATTERY LOW {pct:.0f}% {state}".strip()
                            battery_level = "low"

                    overlay = draw_overlay(frame_path, detections, trigger_reasons, vlm_raw,
                                            winner_text=last_winner_text, battery_text=battery_text,
                                            battery_level=battery_level)
                    set_latest_frame(overlay)

                    if video_writer is None:
                        h_v, w_v = overlay.shape[:2]
                        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                        video_writer = cv2.VideoWriter(str(video_path), fourcc, video_fps, (w_v, h_v))
                    video_writer.write(overlay)

                    if trigger_reasons:
                        trig_frame_path = trigger_frames_dir / f"frame_{frame_idx:05d}_t{now - t0:06.1f}s.jpg"
                        cv2.imwrite(str(trig_frame_path), overlay)

                    frame_idx += 1
                except Exception as e:
                    print(f"  프레임 처리 실패(계속): {e}")
                last_seg = now
    except KeyboardInterrupt:
        print("\n사용자 중단(Ctrl+C).")

    if video_writer is not None:
        video_writer.release()
        print(f"영상 저장: {video_path}")
    print(f"트리거 프레임: {trigger_frames_dir} (총 {len(list(trigger_frames_dir.glob('*.jpg')))}장)")

    pf = node.pose()
    if pf and p0:
        total_moved = math.hypot(pf[0] - p0[0], pf[1] - p0[1])
        print(f"\n관찰 종료. 시작 {p0} -> 끝 {pf}, 이동거리={total_moved:.3f}m")
    else:
        total_moved = 0.0

    if len(poses) >= 2:
        path_length = sum(math.hypot(poses[i][1]-poses[i-1][1], poses[i][2]-poses[i-1][2])
                           for i in range(1, len(poses)))
        net = math.hypot(poses[-1][1]-poses[0][1], poses[-1][2]-poses[0][2])
        traj_log = PklLog(TRAJECTORY_LOG_PATH)
        traj_log.add(TrajectoryRecord(
            poses=poses, start_time=poses[0][0], end_time=poses[-1][0],
            total_path_length=path_length, net_displacement=net,
            meta={"source": "orchestrate_live_teleop", "n_samples": len(poses)},
        ))
        traj_log.save()
        print(f"궤적 저장: {len(poses)}개 샘플, 누적경로={path_length:.3f}m, 직선거리={net:.3f}m "
              f"-> {TRAJECTORY_LOG_PATH}")

        with open("./watch_trajectory.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["idx", "t_rel_s", "x", "y", "yaw"])
            for i, (tt, x, y, yaw) in enumerate(poses):
                w.writerow([i, round(tt - poses[0][0], 3), round(x, 4), round(y, 4), round(yaw, 4)])
        print("궤적 CSV: ./watch_trajectory.csv")

    # (watch_seg_log.csv는 이제 루프 안에서 매 프레임 즉시 append됨 -- 여기선 요약만 출력)
    print(f"세그멘테이션 CSV: {seg_csv_path} ({len(seg_log)}행, 트리거 {n_trigger_labels}개, "
          f"VLM 호출 {n_vlm_calls}회)")

    print(f"buffer 최종: 총 {len(buf.items)}개 transition (트리거별로 실시간 저장됨) -> {BUFFER_PATH}")

    if battery_critical_flag["triggered"]:
        print("\n배터리 CRITICAL로 관찰 루프 중단됨 -- Safe Zone 복귀 실행:")
        pct = battery_watcher.percentage if battery_watcher.percentage is not None else 0.0
        try:
            handle_low_battery(nav_executor, costmap_node, pct)
        except KeyboardInterrupt:
            # nav_recovery_executor._send_and_wait가 이미 goal 취소+정지까지 마친 뒤
            # 재전파한 것 -- 여기서는 트레이스백 없이 깔끔하게만 종료.
            print("\n사용자 중단(Ctrl+C) -- Safe Zone 복귀 중단됨, goal 취소/정지 완료.")

    node.destroy_node()
    if costmap_node is not None:
        costmap_node.destroy_node()
    if nav_executor is not None:
        nav_executor.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sec", type=float, default=WATCH_SEC)
    parser.add_argument("--simple-trigger", action="store_true",
                         help="ObjectWatcher 휴리스틱 대신 'obstacle 감지=즉시 트리거'로 단순화 "
                              "(트리거 로직이 잘 안 잡힐 때 오케스트레이션 배선만 먼저 확인)")
    parser.add_argument("--no-vlm", action="store_true",
                         help="VLM 안 띄움 -- 세그멘테이션+트리거 관찰만 할 때 (트리거 튜닝용). "
                              "buffer에 transition도 안 쌓임(VLM 후보가 있어야 만들어지므로)")
    parser.add_argument("--execute", action="store_true",
                         help="우승 후보를 nav_recovery_executor로 실제 Nav2 실행 + real reward/"
                              "next_state 계산 (Task #2/#3). 트리거마다 실행 직전 Enter 확인 필요 "
                              "(teleop 손 떼고). 기본값(꺼짐)은 지금까지처럼 관찰만.")
    parser.add_argument("--force-critical-battery-after", type=float, default=None,
                         help="실제 배터리가 10%% 밑으로 안 내려가도, 이 시간(초)이 지나면 "
                              "CRITICAL 상황을 강제로 흉내내서 화면 빨간 깜빡임 + Safe Zone "
                              "NavigateToPose를 테스트할 수 있게 함 (테스트용, 실전 배터리 값과 무관)")
    args = parser.parse_args()
    main(args.sec, simple_trigger=args.simple_trigger, use_vlm=not args.no_vlm,
         execute_recovery=args.execute,
         force_critical_battery_after=args.force_critical_battery_after)
