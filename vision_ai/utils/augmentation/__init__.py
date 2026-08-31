"""환경 열화 증강 — 난수 관리와 원시 연산.

시나리오 조합(S1~S5)과 학습 연결은
`vision_ai/models/perception/trainer/augmentation_recipes.py` 가 맡는다.
여기에는 어느 시나리오에도 매이지 않은 재사용 가능한 조각만 둔다.
"""

from .rng import (  # noqa: F401
    DEFAULT_AUGMENTATION_SEED,
    augmentation_rng,
    configure_augmentation_seed,
    isolated_augmentation_random_state,
)
