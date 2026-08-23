#!/usr/bin/env python3
"""실기 Pinky 용 Nav2 파라미터를 벤더 원본에서 파생한다. 원본은 읽기만 한다.

실기 nav2 는 벤더 `pinky_navigation/launch/bringup_launch.xml` 이고 그것은 params 를
`<param from>` 으로 그대로 넘긴다. 시뮬의 `nav2_bringup` 이 해 주던
`RewrittenYaml(root_key=namespace)` 가 없으므로, 벤더 params 의 맨 키(`amcl:`,
`controller_server:` …)가 `/pinky_01/amcl` 노드와 매칭되지 않아 파라미터가 한 개도
적용되지 않는다. 이 도구가 문서 전체를 namespace 아래로 감싸 그 간극을 메운다.

시뮬 번들을 만드는 `control_tower.bringup.p0_runtime_assets` 의 CLI 는 발행된 지도와
`world.sdf` 까지 요구하지만 실기에는 그 둘이 필요 없다. 이 도구는 params 하나만
만든다.

    scripts/derive_hardware_nav2_params.py \\
      --source pinky_pro/pinky_navigation/params/nav2_params.yaml \\
      --namespace pinky_01 \\
      --output .trihouse/p0/nav2/hardware_pinky_01.yaml

`namespace` 없이(분기 B) 단일 로봇을 띄운다면 nav2 노드가 루트에 있어 벤더 params 의
맨 키가 그대로 맞는다. 그때는 이 도구를 쓰지 않고 벤더 기본 params 를 그대로 쓴다.

`pinky_pro` 는 읽기·실행만 허용된 보호 경로다. 이 도구는 그 아래를 수정하지 않는다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from control_tower.bringup.p0_runtime_assets import derive_nav2_params


# Pinky_01 실측에서 controller_server bond 연결 뒤 follow_path Action 발견까지
# 벤더 기본 1000 ms를 넘겼다. 실기 파생본만 10초로 늘리고 시뮬 파생본은 건드리지 않는다.
PHYSICAL_BT_ACTION_DISCOVERY_TIMEOUT_MS = 10_000


def _initial_pose(value: str) -> tuple[float, float, float]:
    """`x,y,yaw` 를 읽는다. 형식이 어긋나면 조용히 넘기지 않는다.

    초기 pose 를 무시하면 AMCL 이 지도 전체에 입자를 흩뿌린 채 시작하고, 그 실패는
    로봇이 움직이기 시작한 뒤에야 보인다.
    """
    parts = value.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            f"--initial-pose 는 x,y,yaw 형식입니다: {value!r}"
        )
    try:
        x, y, yaw = (float(part) for part in parts)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"--initial-pose 의 값이 숫자가 아닙니다: {value!r}"
        ) from error
    return x, y, yaw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="벤더 nav2_params.yaml. 읽기만 한다",
    )
    parser.add_argument(
        "--namespace",
        required=True,
        help="로봇 ROS namespace. robot_id(PK_01)가 아니라 pinky_01 이다",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--initial-pose",
        type=_initial_pose,
        default=None,
        metavar="X,Y,YAW",
        help="AMCL 이 위치추정을 시작할 자리. 승인된 지도 좌표에서만 온다",
    )
    args = parser.parse_args(argv)

    namespace = args.namespace.strip()
    if not namespace:
        raise SystemExit(
            "--namespace 가 비었습니다. namespace 없이 띄우는 단일 로봇(분기 B)은 "
            "벤더 params 의 맨 키가 그대로 맞으므로 이 도구가 필요 없습니다."
        )
    if not args.source.is_file():
        raise SystemExit(f"원본 params 가 없습니다: {args.source}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    derive_nav2_params(
        args.source,
        namespace,
        args.output,
        initial_pose=args.initial_pose,
        root_key=namespace,
        bt_wait_for_service_timeout_ms=PHYSICAL_BT_ACTION_DISCOVERY_TIMEOUT_MS,
    )

    first_line = args.output.read_text(encoding="utf-8").splitlines()[0]
    print(f"{args.output} 첫 줄: {first_line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
