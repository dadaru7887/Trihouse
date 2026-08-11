"""Pinky에서 실행 -- pinkylib.Camera로 프레임을 뽑아 MJPEG(HTTP)로 스트리밍.

PC 쪽은 그냥 URL만 받는 구조라 inference_stream.py는 코드 수정이 필요 없음:
    python3 inference_stream.py --source http://<이 Pinky IP>:8080/stream.mjpg

나중에 MediaMTX/RTSP 중계로 옮길 때도 PC 쪽은 --source를 rtsp://... URL로
바꾸기만 하면 되고, inference_stream.py 자체는 안 건드려도 됨
(cv2.VideoCapture가 http/rtsp 둘 다 동일하게 받아들이기 때문).

의존성: pinkylib, opencv-python (Pinky 이미지에 이미 있음, 추가 설치 불필요)
"""


import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
from pinkylib import Camera

BOUNDARY = "frame"


class MJPEGHandler(BaseHTTPRequestHandler):
    camera: Camera  # main()에서 클래스 속성으로 주입
    swap_rgb: bool = False

    def do_GET(self) -> None:
        if self.path != "/stream.mjpg":
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
                frame = self.camera.get_frame()
                if self.swap_rgb:
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                ok, jpg = cv2.imencode(".jpg", frame)
                if not ok:
                    continue
                data = jpg.tobytes()
                self.wfile.write(f"--{BOUNDARY}\r\n".encode())
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(data)}\r\n\r\n".encode())
                self.wfile.write(data)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass  # PC 쪽이 끊음 -- 정상 종료, 에러 아님

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # 프레임마다 access log 안 찍게 (콘솔 도배 방지)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pinky 카메라 MJPEG 스트리밍 서버")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--swap-rgb", action="store_true",
                   help="화면 색이 이상하게(빨강/파랑 반전) 나오면 이 옵션 켜보기")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    cam = Camera()
    cam.start()
    MJPEGHandler.camera = cam
    MJPEGHandler.swap_rgb = args.swap_rgb

    server = ThreadingHTTPServer(("0.0.0.0", args.port), MJPEGHandler)
    print(f"스트리밍 시작 -- PC에서 http://<이 Pinky IP>:{args.port}/stream.mjpg 로 접속")
    print("종료: Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        cam.close()


if __name__ == "__main__":
    main()
