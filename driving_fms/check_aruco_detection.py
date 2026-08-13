#!/usr/bin/env python3
"""아르코 마커가 실제 거리/각도별로 얼마나 잘 인식되는지 확인하는 스크립트. waypoint(Safe Zone/
적재 위치 등) 좌표 찍는 방법 중 하나로 아르코 마커 활용을 검토 중이라(2026-08-12), 그 전에
로봇 카메라로 실제 인식 가능한 거리/각도부터 확인해두려는 목적. Nav2/waypoint 그래프 작업과는
별개.

2026-08-12 개정: robot_frame_server.py(포트 8899, 단발 프레임)를 폴링하던 방식 대신
pinky_camera_server.py(포트 8080, /stream.mjpg)를 cv2.VideoCapture로 직접 구독하도록 변경함
-- 카메라 장치를 pinky_camera_server.py 하나만 물고 있어야 해서(V4L2 특성상 동시에 두 프로세스가
같은 카메라를 열면 충돌), 단발 프레임 서버는 이제 안 씀. 검출 결과는 자체 MJPEG(포트 8900,
orchestrate_live_teleop.py와 같은 패턴)로 오버레이까지 그려서 재송출 -- 브라우저에서 실시간으로
"잡혔다/안 잡혔다"를 바로 볼 수 있고, teleop 조작하면서 동시에 확인 가능. 검출될 때마다 좌표
(픽셀 corner 4점 + 중심 + 픽셀크기)를 CSV로 계속 로그. AMCL이 떠있으면 그 순간의 실제
map 좌표(x,y,yaw)+stddev도 같이 로그(--no-map-pose로 끌 수 있음) -- 병목1/2 등 FeaturePoint
실측 좌표를 채우는 용도(mission_goal_state_machine.py 참고).

**주의**: 카메라 캘리브레이션(초점거리)이 없어서 정확한 거리(m) 계산은 원래 안 됨 -- 기본으로는
검출된 마커의 픽셀 크기(클수록 가까움)만 보여주고, `--marker-size-m`+`--focal-length-px`를
둘 다 주면 핀홀 근사로 대략적인 거리도 추정해주지만 참고용일 뿐임.

opencv 5.0(신버전 API, cv2.aruco.ArucoDetector) 기준 작성 -- 4060에서 실제 버전 확인함
(2026-08-12).

사용법:
    # 어느 dict(마커 종류)인지 모를 때 -- 프레임 1장으로 전체 dict 다 시도
    python3 check_aruco_detection.py --try-all-dicts

    # dict 알면 계속 감시 + 브라우저 실시간 확인(http://<이 스크립트 실행 머신 IP>:8900/)
    python3 check_aruco_detection.py --dict DICT_4X4_50

    # 대략적인 거리 추정까지(캘리브레이션 없이 참고용)
    python3 check_aruco_detection.py --dict DICT_4X4_50 --marker-size-m 0.10 --focal-length-px 600
"""

from __future__ import annotations

import argparse
import csv
import math
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread

import cv2
import numpy as np

STREAM_URL = "http://192.168.129.37:8080/stream.mjpg"
OVERLAY_PORT = 8900
BOUNDARY = "frame"

# 흔히 쓰이는 사전 목록 -- 실제 인쇄한 마커가 어느 dict인지 모르면 이 중 하나씩 시도
DICT_NAMES = [
    "DICT_4X4_50", "DICT_4X4_100", "DICT_4X4_250", "DICT_4X4_1000",
    "DICT_5X5_50", "DICT_5X5_100", "DICT_5X5_250", "DICT_5X5_1000",
    "DICT_6X6_50", "DICT_6X6_100", "DICT_6X6_250", "DICT_6X6_1000",
    "DICT_7X7_50", "DICT_ARUCO_ORIGINAL",
]


def build_detector(dict_name: str) -> "cv2.aruco.ArucoDetector":
    dict_id = getattr(cv2.aruco, dict_name)
    dictionary = cv2.aruco.getPredefinedDictionary(dict_id)
    params = cv2.aruco.DetectorParameters()
    return cv2.aruco.ArucoDetector(dictionary, params)


def marker_pixel_size(corners: np.ndarray) -> float:
    """마커 4개 꼭짓점의 평균 변 길이(픽셀) -- 거리의 대리지표(가까울수록 값이 큼)."""
    pts = corners.reshape(4, 2)
    sides = [np.linalg.norm(pts[i] - pts[(i + 1) % 4]) for i in range(4)]
    return float(np.mean(sides))


def estimate_distance_m(pixel_size: float, marker_size_m: float, focal_length_px: float) -> float:
    """핀홀 근사: distance = (실제 크기 * 초점거리) / 픽셀 크기. focal_length_px가 실제
    캘리브레이션값이 아니면(대충 짐작값이면) 오차 큼 -- 상대 비교 참고용으로만 쓸 것."""
    if pixel_size <= 0:
        return float("inf")
    return (marker_size_m * focal_length_px) / pixel_size


class LatestFrame:
    """오버레이 MJPEG 재송출용 -- 최신 annotated 프레임만 락으로 보호해서 공유."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._jpg: bytes | None = None

    def set(self, frame: np.ndarray) -> None:
        ok, jpg = cv2.imencode(".jpg", frame)
        if ok:
            with self._lock:
                self._jpg = jpg.tobytes()

    def get(self) -> bytes | None:
        with self._lock:
            return self._jpg


class OverlayHandler(BaseHTTPRequestHandler):
    latest: LatestFrame  # main()에서 주입

    def do_GET(self) -> None:
        if self.path not in ("/", "/stream.mjpg"):
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
        self.end_headers()
        try:
            while True:
                data = self.latest.get()
                if data is None:
                    time.sleep(0.05)
                    continue
                self.wfile.write(f"--{BOUNDARY}\r\n".encode())
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(data)}\r\n\r\n".encode())
                self.wfile.write(data)
                self.wfile.write(b"\r\n")
                time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass


def start_overlay_server(latest: LatestFrame, port: int) -> None:
    OverlayHandler.latest = latest
    server = ThreadingHTTPServer(("0.0.0.0", port), OverlayHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    print(f"실시간 확인: http://<이 기기 IP>:{port}/ (브라우저로 열기)")


def main() -> None:
    parser = argparse.ArgumentParser(description="ArUco 마커 인식 거리/각도 테스트")
    parser.add_argument("--dict", default="DICT_4X4_50", choices=DICT_NAMES,
                         help="아르코 사전 종류 (실제 인쇄한 마커와 맞아야 인식됨)")
    parser.add_argument("--try-all-dicts", action="store_true",
                         help="어느 사전인지 모를 때 -- 프레임 한 장으로 전체 사전 다 시도해서 뭐가 맞는지 찾아줌")
    parser.add_argument("--marker-size-m", type=float, default=None, help="마커 한 변의 실제 길이(m)")
    parser.add_argument("--focal-length-px", type=float, default=None,
                         help="카메라 초점거리(픽셀 단위, 캘리브레이션값). 없으면 거리 추정 생략, 픽셀크기만 표시")
    parser.add_argument("--stream-url", default=STREAM_URL, help="pinky_camera_server.py MJPEG URL")
    parser.add_argument("--overlay-port", type=int, default=OVERLAY_PORT)
    parser.add_argument("--log-csv", default=None,
                         help="검출 좌표 CSV 로그 경로 (안 주면 aruco_detections_<timestamp>.csv 자동 생성)")
    parser.add_argument("--no-map-pose", action="store_true",
                         help="AMCL map 좌표 로그 끄기 (Nav2 안 떠있을 때 등)")
    parser.add_argument("--save-dir", default=None,
                         help="검출 이벤트(새로 잡힌 순간)마다 annotated 프레임 1장씩 저장할 폴더 "
                              "(안 주면 aruco_frames_<timestamp>/ 자동 생성). 매 프레임이 아니라 "
                              "새로 검출될 때만 저장 -- 계속 잡혀있는 동안은 추가 저장 안 함")
    args = parser.parse_args()

    amcl_node = None
    if not args.no_map_pose:
        import rclpy
        from amcl_localization_utils import AmclCovarianceListener
        rclpy.init()
        amcl_node = AmclCovarianceListener()

        def _spin_amcl() -> None:
            while rclpy.ok():
                rclpy.spin_once(amcl_node, timeout_sec=0.2)

        Thread(target=_spin_amcl, daemon=True).start()
        print("AMCL map 좌표 로깅 켬 (--no-map-pose로 끌 수 있음)")

    cap = cv2.VideoCapture(args.stream_url)
    if not cap.isOpened():
        print(f"!! 스트림을 열 수 없음: {args.stream_url} (pinky_camera_server.py 켜져있는지 확인)")
        return

    if args.try_all_dicts:
        print("프레임 1장으로 전체 dict 시도 중...")
        ok, frame = cap.read()
        if not ok:
            print("!! 프레임을 못 읽음")
            return
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found_any = False
        for name in DICT_NAMES:
            detector = build_detector(name)
            corners, ids, _ = detector.detectMarkers(gray)
            if ids is not None and len(ids) > 0:
                found_any = True
                print(f"  {name}: 마커 {len(ids)}개 검출됨, id={ids.flatten().tolist()}")
        if not found_any:
            print("  (아무 dict로도 안 뜸 -- 마커가 카메라에 안 보이거나 너무 멀리/각도가 안 좋을 수 있음, "
                  "마커를 카메라 정면 가까이 대고 재시도해볼 것)")
        cap.release()
        return

    log_path = Path(args.log_csv) if args.log_csv else Path(
        f"aruco_detections_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    log_file = log_path.open("w", newline="")
    writer = csv.writer(log_file)
    writer.writerow(["timestamp", "marker_id", "pixel_size", "est_distance_m",
                      "center_x", "center_y", "corners", "map_x", "map_y", "map_yaw", "amcl_xy_stddev_m"])
    log_file.flush()
    print(f"검출 좌표 로그: {log_path}")

    save_dir = Path(args.save_dir) if args.save_dir else Path(
        f"aruco_frames_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    save_dir.mkdir(parents=True, exist_ok=True)
    print(f"검출 이벤트 프레임 저장 폴더: {save_dir}")

    detector = build_detector(args.dict)
    latest = LatestFrame()
    start_overlay_server(latest, args.overlay_port)

    print(f"dict={args.dict}, 실시간 감시 시작... (Ctrl+C로 종료)")
    was_detected = False
    frame_idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("프레임 읽기 실패, 재시도...")
                time.sleep(0.2)
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            corners, ids, _ = detector.detectMarkers(gray)
            now_detected = ids is not None and len(ids) > 0
            annotated = frame.copy()

            is_new_detection = now_detected and not was_detected
            if now_detected:
                cv2.aruco.drawDetectedMarkers(annotated, corners, ids)
                if is_new_detection:
                    print(f"\n### 잡힘! (frame {frame_idx}) id={ids.flatten().tolist()} ###\n")
                map_pose = amcl_node.pose if amcl_node is not None else None
                map_stddev = amcl_node.xy_stddev_m if amcl_node is not None else None
                map_str = ""
                if map_pose is not None:
                    map_str = (f", map=({map_pose[0]:.3f},{map_pose[1]:.3f},"
                               f"yaw={math.degrees(map_pose[2]):.0f}도) stddev={map_stddev*100:.0f}cm")
                for mid, c in zip(ids.flatten(), corners):
                    px = marker_pixel_size(c)
                    center = c.reshape(4, 2).mean(axis=0)
                    dist_str = ""
                    est_dist = None
                    if args.marker_size_m and args.focal_length_px:
                        est_dist = estimate_distance_m(px, args.marker_size_m, args.focal_length_px)
                        dist_str = f", 추정거리~={est_dist:.2f}m"
                    print(f"[{frame_idx}] id={mid}: 픽셀크기={px:.1f}px, "
                          f"center=({center[0]:.0f},{center[1]:.0f}){dist_str}{map_str}")
                    writer.writerow([datetime.now().isoformat(), int(mid), f"{px:.1f}",
                                      f"{est_dist:.3f}" if est_dist is not None else "",
                                      f"{center[0]:.1f}", f"{center[1]:.1f}",
                                      c.reshape(4, 2).tolist(),
                                      f"{map_pose[0]:.3f}" if map_pose else "",
                                      f"{map_pose[1]:.3f}" if map_pose else "",
                                      f"{map_pose[2]:.3f}" if map_pose else "",
                                      f"{map_stddev:.3f}" if map_stddev is not None else ""])
                    log_file.flush()
                    cv2.putText(annotated, f"id={mid} {px:.0f}px", (int(center[0]), int(center[1])),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                cv2.putText(annotated, "DETECTED", (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                            1.0, (0, 255, 0), 2)
                if is_new_detection:
                    snap_name = (f"{datetime.now().strftime('%H%M%S')}_"
                                 f"ids{'-'.join(map(str, ids.flatten().tolist()))}.jpg")
                    cv2.imwrite(str(save_dir / snap_name), annotated)
            else:
                if was_detected:
                    print(f"[{frame_idx}] 마커 놓침")
                cv2.putText(annotated, "no marker", (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                            1.0, (0, 0, 255), 2)

            was_detected = now_detected
            latest.set(annotated)
            frame_idx += 1
    except KeyboardInterrupt:
        print("\n종료.")
    finally:
        cap.release()
        log_file.close()
        if amcl_node is not None:
            import rclpy
            amcl_node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()
