"""물품이 바뀔 때마다 ACT 정책만 교체해서 추론한다.

로봇/카메라 연결은 robot_session이 프로세스 수명 동안 한 번만 담당하고, 이
모듈은 그 위에서 (1) 체크포인트에서 정책+전/후처리기를 로드하고 (2) 관측 1개당
액션 1개를 뽑는 것만 책임진다. LeRobotDataset을 실제로 만들거나 내려받지 않고,
robot.observation_features/action_features만으로 같은 모양의 features 스키마를
로컬에서 재현한다 — record.py가 dataset.features를 만드는 방식과 동일하다.

실행 전 준비: source ~/venv/il/bin/activate (Python 3.10, lerobot 0.4.4 editable
설치, ~/il_ws/src/lerobot). lerobot.rollout 패키지는 이 버전에 없으므로 쓰지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from lerobot.configs.policies import PreTrainedConfig
from lerobot.datasets.pipeline_features import (
    aggregate_pipeline_dataset_features,
    create_initial_features,
)
from lerobot.datasets.utils import build_dataset_frame, combine_feature_dicts
from lerobot.policies.factory import get_policy_class, make_pre_post_processors
from lerobot.policies.pretrained import PreTrainedPolicy
from lerobot.policies.utils import make_robot_action
from lerobot.processor import make_default_processors
from lerobot.robots.omx_follower import OmxFollower
from lerobot.utils.constants import OBS_STR
from lerobot.utils.control_utils import predict_action
from lerobot.utils.utils import get_safe_torch_device


def build_dataset_features(robot: OmxFollower) -> dict:
    """robot의 관측/액션 스펙만으로 LeRobotDataset과 동일한 features 딕셔너리를 만든다.

    실제 데이터셋을 만들거나 HF에서 내려받지 않는다 — record.py의
    dataset_features 구성 로직(같은 함수 조합)을 그대로 재사용했을 뿐이다.
    """
    teleop_action_processor, _, robot_observation_processor = make_default_processors()
    return combine_feature_dicts(
        aggregate_pipeline_dataset_features(
            pipeline=teleop_action_processor,
            initial_features=create_initial_features(action=robot.action_features),
            use_videos=True,
        ),
        aggregate_pipeline_dataset_features(
            pipeline=robot_observation_processor,
            initial_features=create_initial_features(observation=robot.observation_features),
            use_videos=True,
        ),
    )


@dataclass
class LoadedPolicy:
    repo_id: str
    policy: PreTrainedPolicy
    preprocessor: object
    postprocessor: object

    def reset(self) -> None:
        self.policy.reset()
        self.preprocessor.reset()
        self.postprocessor.reset()


def load_policy(repo_id: str, *, device: str | None = None) -> LoadedPolicy:
    """체크포인트에서 정책과 전/후처리기를 직접 로드한다.

    make_policy()와 달리 dataset metadata가 필요 없다 — repo_id의 config.json이
    이미 입출력 feature shape을 갖고 있어서 곧바로 로드된다. 매 주문마다 이
    함수만 다시 부르면 "정책 교체"가 끝난다 (로봇/카메라는 안 건드림).
    """
    policy_cfg = PreTrainedConfig.from_pretrained(repo_id)
    if device is not None:
        policy_cfg.device = device
    policy_cls = get_policy_class(policy_cfg.type)
    policy = policy_cls.from_pretrained(repo_id, config=policy_cfg)
    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg=policy_cfg,
        pretrained_path=repo_id,
    )
    return LoadedPolicy(repo_id, policy, preprocessor, postprocessor)


def infer_step(
    robot: OmxFollower,
    loaded: LoadedPolicy,
    dataset_features: dict,
    *,
    task: str,
) -> dict:
    """관측 1개 -> 정책 추론 -> robot.send_action()에 바로 넘길 수 있는 action dict."""
    obs = robot.get_observation()
    observation_frame = build_dataset_frame(dataset_features, obs, prefix=OBS_STR)
    action_values = predict_action(
        observation=observation_frame,
        policy=loaded.policy,
        device=get_safe_torch_device(loaded.policy.config.device),
        preprocessor=loaded.preprocessor,
        postprocessor=loaded.postprocessor,
        use_amp=loaded.policy.config.use_amp,
        task=task,
        robot_type=robot.robot_type,
    )
    return make_robot_action(action_values, dataset_features)
