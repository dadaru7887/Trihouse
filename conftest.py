"""저장소 전체를 한 번에 수집할 때 필요한 import 경로 고정.

ROS 패키지는 `<pkg>/<pkg>/` 구조라서 저장소 루트만 `sys.path`에 있으면
바깥 디렉터리가 namespace package로 먼저 잡히고 실제 모듈을 찾지 못한다.
각 ROS 패키지 루트를 저장소 루트보다 앞에 넣어 실제 패키지가 이기게 한다.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

# 안쪽 파이썬 패키지를 담고 있는 ROS 패키지 루트들.
ROS_PACKAGE_ROOTS = (
    "trihouse_rmf_bridge",
    "trihouse_omx_adapter",
)


def _prepend(path: Path) -> None:
    entry = str(path)
    if entry in sys.path:
        sys.path.remove(entry)
    sys.path.insert(0, entry)


# 저장소 루트가 가장 뒤에 남도록 역순으로 넣는다.
_prepend(ROOT)
for _name in ROS_PACKAGE_ROOTS:
    _prepend(ROOT / _name)

# 수집 도중 pytest가 저장소 루트를 다시 앞으로 넣으면 바깥 디렉터리가
# namespace package로 잡힌다. 여기서 미리 한 번 import해 올바른 모듈을
# `sys.modules`에 고정한다.
for _name in ROS_PACKAGE_ROOTS:
    __import__(_name)
