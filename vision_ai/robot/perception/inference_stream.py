"""로컬 학습 모델로 영상 스트림 추론.

vision-streaming-architecture-draft.html §8(스트림 단절 정의와 대응) 기준 반영:
  - 상태: HEALTHY / DEGRADED / DISCONNECTED / RECOVERING (§8.2 표 그대로)
  - 단절된 카메라의 마지막 프레임을 반복해 모델에 넣지 않음
  - DISCONNECTED -> action queue·authorization 즉시 폐기, 안전 정지
  - 재접속은 로컬 녹화 대신 backoff, 재연결 후에도 재인증 전엔 재개 안 함

지금은 RTX5080이 아니라 이 PC(CPU)에서 로컬 학습 모델(smoke_test_local-3)로
파이프라인만 먼저 검증하는 용도. --source로 웹캠/영상파일/RTSP 다 받을 수 있음.
"""


import argparse
import enum
import time
from dataclasses import dataclass, field

import cv2

DEFAULT_MODEL = "runs/segment/smoke_test_local-3/weights/best.pt"


def mixed_augmentation(image, **kwargs):
    """체크포인트 unpickle용 자리표시자.

    학습 때(train_yolo_local.ipynb/train.py) 쓴 실제 augmentation 함수가 체크포인트의
    train_args에 pickle로 같이 저장돼 있어서, 같은 이름이 이 모듈(__main__)에 없으면
    torch.load 단계에서 AttributeError가 남. 추론 시점엔 이 함수가 실제로 호출되지
    않으므로(augmentation은 학습 전용) 내용은 의미 없음.
    """
    return image

# ── §8.2 상태 판정 기준 ──────────────────────────────────────
DEGRADED_SILENCE_SEC = 1.0
DISCONNECTED_SILENCE_SEC = 3.0
HEALTHY_MIN_DURATION_SEC = 5.0
HEALTHY_FPS_RATIO = 0.9
DEGRADED_FPS_RATIO = 0.5

RECONNECT_BACKOFF_START = 0.5
RECONNECT_BACKOFF_MAX = 8.0


class StreamState(enum.Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"
    RECOVERING = "RECOVERING"


@dataclass
class StreamMonitor:
    """프레임 수신 이력만 보고 §8.2 표대로 상태를 판정.

    freeze(연결은 유지되지만 frame이 그대로인 상태, §8.1-6)를 잡기 위해
    프레임 내용 자체가 바뀌었는지(해시)까지 같이 본다 -- read()가 성공해도
    같은 프레임이 반복되면 "새 프레임 없음"과 동일하게 취급.
    """

    target_fps: float
    last_frame_ts: float | None = None
    last_frame_digest: bytes | None = None
    is_new_frame: bool = False
    state: StreamState = StreamState.DISCONNECTED
    _healthy_since: float | None = None
    _intervals: list[float] = field(default_factory=list)

    def on_frame(self, frame) -> StreamState:
        now = time.monotonic()
        digest = frame.tobytes()[:4096]  # 저비용 freeze 감지 (전체 해시는 불필요)
        self.is_new_frame = digest != self.last_frame_digest
        if self.is_new_frame:
            if self.last_frame_ts is not None:
                self._intervals.append(now - self.last_frame_ts)
                self._intervals = self._intervals[-30:]
            self.last_frame_ts = now
            self.last_frame_digest = digest
        return self._evaluate(now)

    def on_no_frame(self) -> StreamState:
        return self._evaluate(time.monotonic())

    def _evaluate(self, now: float) -> StreamState:
        if self.last_frame_ts is None:
            return self._set(StreamState.DISCONNECTED)

        silence = now - self.last_frame_ts
        if silence >= DISCONNECTED_SILENCE_SEC:
            return self._set(StreamState.DISCONNECTED)

        fps = self._recent_fps()
        below_degraded_fps = fps is not None and fps < self.target_fps * DEGRADED_FPS_RATIO
        if silence >= DEGRADED_SILENCE_SEC or below_degraded_fps:
            was_disconnected = self.state == StreamState.DISCONNECTED
            return self._set(StreamState.RECOVERING if was_disconnected else StreamState.DEGRADED)

        healthy_fps = fps is not None and fps >= self.target_fps * HEALTHY_FPS_RATIO
        if not healthy_fps:
            self._healthy_since = None
            was_disconnected = self.state == StreamState.DISCONNECTED
            return self._set(StreamState.RECOVERING if was_disconnected else StreamState.DEGRADED)

        if self._healthy_since is None:
            self._healthy_since = now
        if now - self._healthy_since >= HEALTHY_MIN_DURATION_SEC:
            return self._set(StreamState.HEALTHY)
        return self._set(StreamState.RECOVERING)

    def _recent_fps(self) -> float | None:
        if len(self._intervals) < 3:
            return None
        avg = sum(self._intervals) / len(self._intervals)
        return 1.0 / avg if avg > 0 else None

    def _set(self, state: StreamState) -> StreamState:
        if state != StreamState.HEALTHY:
            self._healthy_since = None
        self.state = state
        return state


class ReconnectingCapture:
    """cv2.VideoCapture 래퍼. 끊기면 버퍼 버리고 backoff 후 재접속만 함
    (§8.2: "송신 장치는 로컬 녹화로 전환하지 않고 RAM 버퍼를 폐기한 뒤
    제한된 backoff로 재접속" -- 이건 수신측 코드지만 같은 원칙 적용)."""

    def __init__(self, source: str | int):
        self.source = source
        self.cap: cv2.VideoCapture | None = None
        self.backoff = RECONNECT_BACKOFF_START
        self._open()

    def _open(self) -> None:
        self.cap = cv2.VideoCapture(self.source)

    def read(self):
        if self.cap is None or not self.cap.isOpened():
            return None
        ok, frame = self.cap.read()
        return frame if ok else None

    def reconnect(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        time.sleep(self.backoff)
        self.backoff = min(self.backoff * 2, RECONNECT_BACKOFF_MAX)
        self._open()

    def on_recovered(self) -> None:
        self.backoff = RECONNECT_BACKOFF_START


class InferenceSession:
    """§8의 상태 전이를 그대로 따르는 추론 루프.

    authorize_fn: 재연결/최초 HEALTHY 전환 시 호출되는 재인증 훅.
    None이면 인증 단계 없이 바로 통과 (실제 배치 전엔 QR/ArUco/DB 검증으로 교체).
    결과는 on_result(result, frame)로 콜백.
    """

    def __init__(self, model_path: str, source: str | int, target_fps: float = 15.0,
                 authorize_fn=None, on_result=None, show: bool = True):
        from ultralytics import YOLOE  # 무거운 임포트는 실제 사용 시점에

        self.model = YOLOE(model_path)
        self.stream = ReconnectingCapture(source)
        self.monitor = StreamMonitor(target_fps=target_fps)
        self.authorize_fn = authorize_fn
        self.show = show
        self.on_result = on_result or self._default_on_result
        self.authorized = False
        self.action_queue: list = []
        self._prev_state: StreamState | None = None
        self._quit = False
        self._frame_interval = 1.0 / target_fps if target_fps > 0 else 0.0

    def run(self, max_frames: int | None = None) -> None:
        n = 0
        while (max_frames is None or n < max_frames) and not self._quit:
            step_start = time.monotonic()
            frame = self.stream.read()
            state = self.monitor.on_frame(frame) if frame is not None else self.monitor.on_no_frame()
            if state != self._prev_state:
                print(f"[상태] {self._prev_state} -> {state}")
                self._prev_state = state

            if state == StreamState.DISCONNECTED:
                self._discard_and_stop("스트림 단절")
                self.stream.reconnect()
                continue

            # DEGRADED/RECOVERING이어도 새 프레임이면 추론은 계속 --
            # 단, freeze(같은 프레임 반복)면 절대 다시 넣지 않음
            if frame is None or not self.monitor.is_new_frame:
                continue

            if state == StreamState.HEALTHY and not self.authorized:
                self.authorized = self._reauthorize()
                self.stream.on_recovered()
                if not self.authorized:
                    continue

            if not self.authorized:
                # 아직 재인증 안 끝났으면 추론 결과를 액션으로 못 씀 --
                # 여기서는 학습 결과 확인용으로 추론 자체는 계속 보여주기만 함
                pass

            result = self.model.predict(frame, verbose=False)[0]
            self.on_result(result, frame)
            n += 1

            if self.show:
                self._pace(step_start)
        if self.show:
            cv2.destroyAllWindows()

    def _pace(self, step_start: float) -> None:
        """영상 파일은 디코딩이 실시간보다 훨씬 빨라서, 화면으로 눈으로 보려면
        target_fps에 맞춰 살짝 쉬어줘야 자연스러운 재생처럼 보임
        (웹캠/RTSP는 원래 실시간이라 이 대기가 사실상 0에 가까움)."""
        if self._frame_interval <= 0:
            return
        elapsed = time.monotonic() - step_start
        remaining = self._frame_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _discard_and_stop(self, reason: str) -> None:
        if self.action_queue:
            print(f"[안전정지] {reason} -- action queue {len(self.action_queue)}건 폐기")
        self.action_queue.clear()
        self.authorized = False

    def _reauthorize(self) -> bool:
        if self.authorize_fn is None:
            return True
        ok = self.authorize_fn()
        print("[재인증]", "성공" if ok else "실패 -- HEALTHY 유지되는 동안 재시도")
        return ok

    def _default_on_result(self, result, frame) -> None:
        n_det = 0 if result.masks is None else len(result.masks)
        print(f"[추론] 객체 {n_det}개 감지")
        if self.show:
            annotated = result.plot()  # BGR, 마스크/박스/라벨 다 그려서 반환
            cv2.imshow("Trihouse segmentation inference (q 또는 ESC로 종료)", annotated)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):  # 27 = ESC
                self._quit = True


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="스트림 단절 대응 로직 포함 로컬 추론 테스트")
    p.add_argument("--model", type=str, default=DEFAULT_MODEL)
    p.add_argument("--source", type=str, default="0",
                   help="웹캠 인덱스(예: 0), 영상 파일 경로, 또는 RTSP/SRT URL")
    p.add_argument("--target-fps", type=float, default=15.0)
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--no-show", action="store_true", help="화면 창 없이 콘솔 로그만 (헤드리스 환경용)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    source: str | int = int(args.source) if args.source.isdigit() else args.source

    session = InferenceSession(model_path=args.model, source=source, target_fps=args.target_fps,
                                show=not args.no_show)
    try:
        session.run(max_frames=args.max_frames)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
