#!/usr/bin/env bash
# pinky_01 의 URDF 를 만든다.
# rmf_control_ui 가 맵 프로젝트에서 생성했다.
#
# 벤더 xacro 는 링크 이름에는 네임스페이스를 안 붙이면서 <gazebo reference> 에는
# 붙인다. 맞는 링크가 없어 그 블록이 통째로 버려지고, 라이다·카메라·IMU 가
# 하나도 안 올라간다. 토픽 이름은 보이는데 데이터가 영영 안 오고 오류도 안 난다.
#
# 링크에 접두사를 안 붙이는 것은 일부러다 — TF 는 robot_state_publisher 의
# frame_prefix 가 붙인다. 그러니 reference 쪽 접두사를 떼는 것이 맞다.
set -euo pipefail

NAMESPACE="${NAMESPACE:-pinky_01}"
CAM_TILT_DEG="${CAM_TILT_DEG:-0}"

XACRO="$(ros2 pkg prefix pinky_description)"
XACRO="$XACRO/share/pinky_description/urdf/robot.urdf.xacro"

# 펼친 결과를 파일에 받는다. python 을 heredoc 으로 넘기려면 표준 입력이
# 비어 있어야 한다.
RAW="$(mktemp)"
trap 'rm -f "$RAW"' EXIT

# 벤더 launch 와 같은 인자로 펼친다. 네임스페이스 끝의 빗금까지 같아야 한다.
xacro "$XACRO" \
  namespace:="$NAMESPACE/" \
  is_sim:=true \
  cam_tilt_deg:="$CAM_TILT_DEG" > "$RAW"

python3 - "$RAW" "$NAMESPACE" <<'PYTHON'
import re
import sys

path, namespace = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as handle:
    urdf = handle.read()

links = set(re.findall('<link name="([^"]+)"', urdf))
joints = set(re.findall('<joint name="([^"]+)"', urdf))
prefix = namespace + '/'

# 조인트 이름에는 네임스페이스가 붙어 있고 링크 이름에는 안 붙어 있다. 그래서
# 무조건 떼면 조인트 쪽이 깨진다. 가리키는 것이 무엇인지 보고 정한다.
def fix(match):
    name = match.group(1)
    if name in links or name in joints:
        return match.group(0)
    if name.startswith(prefix) and name[len(prefix):] in links:
        return '<gazebo reference="' + name[len(prefix):] + '"'
    sys.stderr.write(
        name + ' 이(가) 없어 그 <gazebo> 블록이 버려집니다.\n')
    return match.group(0)

urdf, seen = re.subn('<gazebo reference="([^"]+)"', fix, urdf)
if seen == 0:
    sys.stderr.write('<gazebo reference> 가 하나도 없습니다.\n')

sys.stdout.write(urdf)
PYTHON
