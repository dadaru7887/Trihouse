"""policy_runtime.py와 이름이 같은 함수들 — GPU 없는 PC(OMX_01)용 원격 추론 클라이언트.

deliver.py/store.py의 run_item()이 `policy_runtime_module` 인자로 이 모듈을
받으면, `pr.load_policy(...)`/`pr.infer_step(...)` 호출이 로컬 GPU 대신 이
모듈을 거쳐 원격 서버(remote_infer_server.py, 5080에서 실행)로 나간다 —
run_item()/run_order() 본문은 이것 때문에 한 줄도 안 바뀐다.

**카메라·joint state는 이 모듈이 직접 전송한다(RTSP 재사용 아님).** 학습된
체크포인트가 front+wrist 카메라 둘 다 필요한데, QR용 RTSP는 wrist만 4060에
가고 front는 아예 안 가서(그 역할 자체가 미정) 이미지를 RTSP로 재사용할 수
없었다. 대신 6.7초(ACT 청크 100스텝 기준)에 한 번, 그 순간 카메라에서 바로
찍은 스냅샷을 JPEG+base64로 실어 보낸다 — RTSP처럼 계속 흐르는 스트림이
아니라서 자원도 적게 쓰고, "오래된 프레임으로 추론" 위험도 없다(그 순간
`robot.get_observation()`으로 찍으므로 로컬 추론과 신선도가 동일).

**경로는 4060을 거치는 게 맞다(팀원 확인)** — 이 모듈은 `base_url`에
그대로 POST할 뿐이라 그 주소가 5080이든 4060의 중계 지점이든 코드는
안 바뀐다. 4060 쪽 중계 자체는 trihouse_omx 밖의 작업이라 여기서 만들지
않는다 — `--remote-infer-url` 값만 나중에 그 주소로 바꾸면 된다.

실행 전 준비: 이 모듈은 lerobot venv(~/venv/il, Python 3.10)에서 deliver.py/
store.py와 같은 프로세스로 돈다 — 별도 설치 불필요. cv2는 카메라 처리에
이미 쓰는 의존성이라 새로 추가되는 게 아니다. 나머지(json/base64/urllib/uuid/
collections.deque)는 전부 stdlib — control_tower/gateway/fms_client.py와
같은 "표준 라이브러리만" 원칙.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
import uuid
from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np
import torch

try:  # OMX_01(0.31)의 lerobot은 이 PC/5080보다 최신 버전이라 이 심볼이
    # lerobot.datasets.utils -> lerobot.utils.feature_utils로 옮겨졌다
    # (실측 확인, 2026-08-22) — 함수 내용은 동일, 위치만 다르다.
    from lerobot.datasets.utils import build_dataset_frame
except ImportError:
    from lerobot.utils.feature_utils import build_dataset_frame
from lerobot.policies.utils import make_robot_action
from lerobot.robots.omx_follower import OmxFollower
from lerobot.utils.constants import OBS_STR

import policy_runtime

_BASE_URL: str | None = None
_TIMEOUT_S: float = 5.0


class RemoteInferenceError(RuntimeError):
    """이 모듈이 내는 유일한 예외 — 재시도도, 가짜 action도 없다.

    run_item()/run_order() 어디에서도 이 예외를 잡지 않는다(둘 다 넓은
    예외 처리가 없음 — 의도된 fail-closed: 통신 단절 상태에서 동작을
    계속하지 않는다, robot_arm_safety.md).
    """


def configure(*, base_url: str, timeout_s: float = 5.0) -> None:
    """run(args)에서 한 번 호출 — 이후 모든 요청이 이 주소로 나간다."""
    global _BASE_URL, _TIMEOUT_S
    _BASE_URL = base_url.rstrip("/")
    _TIMEOUT_S = timeout_s


def _post(path: str, body: dict) -> dict:
    if _BASE_URL is None:
        raise RemoteInferenceError("remote_policy_runtime.configure()를 먼저 호출해야 함")
    data = json.dumps(body).encode()
    request = urllib.request.Request(
        _BASE_URL + path, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise RemoteInferenceError(f"{path} 요청 실패: {error}") from error


@dataclass
class RemoteLoadedPolicy:
    """policy_runtime.LoadedPolicy와 같은 역할(.reset() 인터페이스)을 하는, 원격판."""

    repo_id: str
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _queue: deque = field(default_factory=deque, repr=False)

    def reset(self) -> None:
        """서버에 /v1/reset — 여기서 서버가 체크포인트를 처음 로드/캐시한다.

        bench.py의 기존 tick("policy_loaded") 표시가 "서버가 준비 완료를
        확인한 시점"으로 자연스럽게 유지된다. 이전 아이템의 ACT 내부 큐
        상태가 새 에피소드로 새지 않도록 로컬 큐도 비운다.
        """
        _post("/v1/reset", {"repo_id": self.repo_id, "session_id": self.session_id})
        self._queue.clear()


def load_policy(repo_id: str, *, device: str | None = None) -> RemoteLoadedPolicy:
    """네트워크 호출 없이 객체만 만든다 — policy_runtime.load_policy()와 동일한 가벼움.

    device는 시그니처 맞춤용으로만 받고 무시한다 — 서버가 자기 GPU를 알아서 쓴다.
    """
    del device
    return RemoteLoadedPolicy(repo_id=repo_id)


def build_dataset_features(robot: OmxFollower) -> dict:
    """순수 CPU 계산(GPU 불필요) — policy_runtime.build_dataset_features()에 그대로 위임."""
    return policy_runtime.build_dataset_features(robot)


def _encode_observation_frame(observation_frame: dict) -> dict:
    """observation_frame(numpy dict)을 JSON에 실을 수 있는 형태로 바꾼다.

    "image" in name인 키는 prepare_observation_for_inference()가 쓰는 것과
    같은 판별 기준 — JPEG로 압축 후 base64. 나머지(관절 상태 등)는 그냥
    리스트로.
    """
    encoded = {}
    for name, array in observation_frame.items():
        if "image" in name:
            ok, buf = cv2.imencode(".jpg", array)
            if not ok:
                raise RemoteInferenceError(f"{name} JPEG 인코딩 실패")
            encoded[name] = {"jpeg_b64": base64.b64encode(buf.tobytes()).decode("ascii")}
        else:
            encoded[name] = {"values": np.asarray(array).tolist()}
    return encoded


def infer_step(
    robot: OmxFollower,
    loaded: RemoteLoadedPolicy,
    dataset_features: dict,
    *,
    task: str,
) -> dict:
    """policy_runtime.infer_step()과 같은 시그니처 — 큐가 비었을 때만 네트워크 호출.

    ACTPolicy.select_action()이 내부적으로 하는 청크 큐잉을 여기서 클라이언트
    쪽에 그대로 흉내낸다: 큐가 비어있을 때만 /v1/infer_chunk를 부르고(여기서만
    RemoteInferenceError가 날 수 있음 — 에피소드 중간), 아니면 로컬 큐에서
    하나 꺼내 쓴다. 그래서 매 스텝(66ms)이 아니라 100스텝(~6.7초)에 한 번만
    네트워크를 탄다.
    """
    obs = robot.get_observation()
    observation_frame = build_dataset_frame(dataset_features, obs, prefix=OBS_STR)

    if not loaded._queue:
        response = _post(
            "/v1/infer_chunk",
            {
                "repo_id": loaded.repo_id,
                "session_id": loaded.session_id,
                "task": task,
                "robot_type": robot.robot_type,
                "observation": _encode_observation_frame(observation_frame),
            },
        )
        actions = response.get("actions")
        if not actions:
            raise RemoteInferenceError("서버가 빈 action 청크를 반환함")
        loaded._queue.extend(actions)

    action_values = np.asarray([loaded._queue.popleft()], dtype=np.float32)
    return make_robot_action(torch.from_numpy(action_values), dataset_features)
