"""4060에서 PK02 RTSP를 읽어 FMS에 ArUco 관측만 전달하는 실행기.

관제는 ROS와 cmd_vel을 전혀 발행하지 않는다. FMS가 camera registry로 Pinky를
선택하고 기존 TCP gateway가 onboard ROS 관측으로 바꾼다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time
from urllib.request import Request, urlopen

import cv2
import numpy


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rtsp-url', required=True, help='Pass through the environment; never write it to a log')
    parser.add_argument('--camera-id', default='CAM-PK-02')
    parser.add_argument('--fms-url', default='http://127.0.0.1:8080')
    parser.add_argument('--calibration-file', required=True)
    parser.add_argument('--marker-length-m', required=True, type=float)
    parser.add_argument('--width', type=int, default=1280)
    parser.add_argument('--height', type=int, default=720)
    parser.add_argument('--fps', type=int, default=15)
    parser.add_argument('--ttl-ms', type=int, default=250)
    return parser.parse_args()


def _load_calibration(path: str) -> tuple[numpy.ndarray, numpy.ndarray]:
    with numpy.load(Path(path)) as calibration:
        matrix = numpy.asarray(calibration['camera_matrix'], dtype=float)
        distortion = numpy.asarray(calibration['distortion_coefficients'], dtype=float)
    if matrix.shape != (3, 3) or distortion.size not in (4, 5, 8, 12, 14):
        raise ValueError('invalid OpenCV calibration artifact')
    return matrix, distortion


def _ffmpeg(url: str, width: int, height: int, fps: int) -> subprocess.Popen:
    # URL은 프로세스 인자에만 두며 화면/로그에 출력하지 않는다.
    return subprocess.Popen(
        [
            'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'warning',
            '-rtsp_transport', 'tcp', '-fflags', 'nobuffer', '-flags', 'low_delay',
            '-i', url, '-map', '0:v:0', '-an', '-vf', f'fps={fps},scale={width}:{height}',
            '-pix_fmt', 'bgr24', '-f', 'rawvideo', 'pipe:1',
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def _post(url: str, payload: dict) -> None:
    request = Request(
        url + '/internal/v1/vision/marker-observations',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urlopen(request, timeout=1.0) as response:
        if response.status != 200:
            raise RuntimeError(f'FMS marker delivery returned HTTP {response.status}')


def main() -> None:
    args = _args()
    if args.marker_length_m <= 0 or args.ttl_ms <= 0:
        raise SystemExit('marker-length-m and ttl-ms must be positive')
    matrix, distortion = _load_calibration(args.calibration_file)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_50)
    parameters = cv2.aruco.DetectorParameters_create()
    frame_size = args.width * args.height * 3
    process = _ffmpeg(args.rtsp_url, args.width, args.height, args.fps)
    print(f'READY: {args.camera_id} DICT_5X5_50 -> FMS marker observations', flush=True)
    try:
        while True:
            raw = process.stdout.read(frame_size) if process.stdout else b''
            if len(raw) != frame_size:
                raise RuntimeError('RTSP frame is incomplete or stream ended')
            frame = numpy.frombuffer(raw, dtype=numpy.uint8).reshape(args.height, args.width, 3)
            corners, ids, _ = cv2.aruco.detectMarkers(frame, dictionary, parameters=parameters)
            if ids is None:
                continue
            _, translations, _ = cv2.aruco.estimatePoseSingleMarkers(
                corners, args.marker_length_m, matrix, distortion
            )
            now_ms = int(time.time() * 1000)
            for index, marker_id in enumerate(ids.flatten()):
                x, y, z = (float(value) for value in translations[index][0])
                _post(args.fms_url, {
                    'camera_id': args.camera_id,
                    'marker_family': 'DICT_5X5_50',
                    'marker_id': str(int(marker_id)),
                    'translation_m': {'x': x, 'y': y, 'z': z},
                    'confidence': 1.0,
                    'ttl_ms': args.ttl_ms,
                    'observed_at_ms': now_ms,
                })
    except KeyboardInterrupt:
        pass
    finally:
        process.terminate()
        process.wait(timeout=2)


if __name__ == '__main__':
    main()
