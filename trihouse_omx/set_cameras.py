#!/usr/bin/env python3
"""front/wrist 카메라 포트를 확인 후 한 번만 저장해둔다.

카메라가 실제로 어느 물리 위치(선반을 보는 front / 손목의 wrist)를 찍는지는
이 스크립트가 알 수 없다 — lerobot-teleoperate --display_data=true로 화면을
직접 보고 확인한 뒤, 그 결과만 여기에 입력한다. 저장되면 deliver.py/store.py가
--front-cam/--wrist-cam 없이도 이 값을 자동으로 쓴다.

실행 예:
    python3 set_cameras.py --front /dev/video0 --wrist /dev/video6
    python3 set_cameras.py --front 0 --wrist 6   # 순수 숫자도 가능(비권장, 오전 대화 참고)
"""

from __future__ import annotations

import argparse

import camera_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--front", required=True, help="front 카메라, 예: /dev/video0")
    parser.add_argument("--wrist", required=True, help="wrist 카메라, 예: /dev/video6")
    args = parser.parse_args()

    camera_config.save(args.front, args.wrist)
    print(f"saved to {camera_config.CONFIG_PATH}: front={args.front} wrist={args.wrist}")
    print("이제 deliver.py/store.py를 --front-cam/--wrist-cam 없이 실행하면 이 값을 자동으로 씀.")


if __name__ == "__main__":
    main()
