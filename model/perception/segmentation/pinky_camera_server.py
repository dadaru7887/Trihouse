"""오프라인 랩 폴백 -- pinkylib.Camera 프레임을 MJPEG(HTTP)로 내보낸다.

    ※ 여기서 나온 프레임은 학습 세트에 넣지 않는다. ※

이 파일은 더 이상 기본 경로가 아니다. 학습과 운영 추론은 둘 다 PC1 MediaMTX 의
RTSP(`rtsp://<PC1>:8554/pinky/CAM-PK-01`)를 쓴다. 학습에 필요한 것은 실시간
스트림이 아니라 운영이 보는 것과 같은 픽셀인데, 이 경로의 픽셀은 운영과 다르기
때문이다.

    코덱      JPEG 프레임 독립        ↔ H.264 baseline, --intra 15
    화질      cv2.imencode 기본(95)   ↔ 2000 kbps
    프레임률  서버 루프대로 무제한     ↔ 15 fps
    해상도    미지정(pinklib 반환값)   ↔ 1280x720

세그멘테이션은 경계에 민감하고, H.264 baseline 2 Mbps 는 deblocking 과 저비트레이트
블록 아티팩트로 바로 그 경계를 뭉갠다. MJPEG 은 그 열화를 만들지 않으므로, 이
프레임으로 학습하면 배치 후에야 처음 보는 열화를 만나게 된다. 학습 프레임은
MediaMTX 녹화본(`/recordings/pinky/CAM-PK-01/`)에서 뽑는다. 그 녹화본은 운영과
같은 인코딩 사슬을 이미 지난 것이다.

남겨 두는 이유는 하나다. PC1 에 닿을 수 없는 자리에서 카메라 자체가 살아 있는지
눈으로 확인할 때가 있다. 그 용도로만 쓴다. 자동으로 이 파일을 띄우는 곳은 없고,
그대로 두는 것이 맞다.

배경과 절차: model/perception/segmentation/PINKY_SEGMENTATION_PIPELINE.md §1, §5.

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
