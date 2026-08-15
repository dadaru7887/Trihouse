#!/usr/bin/env bash
# OMX-02 의 URDF 를 만든다.
# rmf_control_ui 가 맵 프로젝트에서 생성했다.
#
# 벤더 xacro 의 gz_ros2_control 플러그인에 네임스페이스를 끼워 넣는다. 없으면
# 플러그인이 루트 /robot_description 을 기다리며 Gazebo 갱신 루프를 막는다.
set -euo pipefail

MODEL="${MODEL:-omx_f}"
NAMESPACE="${NAMESPACE:-omx_02}"

XACRO="$(ros2 pkg prefix open_manipulator_description)"
XACRO="$XACRO/share/open_manipulator_description/urdf/$MODEL/$MODEL.urdf.xacro"

xacro "$XACRO" use_sim:=true | python3 -c '
import re
import sys

namespace = sys.argv[1]
urdf = sys.stdin.read()
# 플러그인 여는 태그 바로 뒤에 끼워 넣는다. 벤더 파일을 건드리지 않는다.
urdf = re.sub(
    r"(<plugin[^>]*gz_ros2_control[^>]*>)",
    r"\1<ros><namespace>/" + namespace + r"</namespace></ros>"
    r"<robot_param_node>robot_state_publisher</robot_param_node>",
    urdf,
    count=1,
)
sys.stdout.write(urdf)
' "$NAMESPACE"
