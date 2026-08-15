#!/usr/bin/env bash
#
# Pinky 가상 실험 실행 — 빌드 후 Gazebo 월드와 플릿을 띄운다.
#
#   ./run.sh                        # GUI + 관제 링크
#   ./run.sh gui:=false             # 헤드리스
#   ./run.sh agents:=false          # 관제 없이 Gazebo만 (수동 teleop 확인용)
#   ./run.sh arms:=none             # 적재 로봇팔 없이
#   ./run.sh control_host:=192.168.0.10
#
# 관제센터(robo_control)를 먼저 띄워 두는 편이 좋지만, 순서는 상관없다.
# 에이전트는 관제가 열릴 때까지 재접속을 반복한다.
#
# `set -u`(미정의 변수 오류)는 쓰지 않는다. ROS 2와 colcon의 setup 스크립트가
# 내부에서 미정의 변수를 참조해, -u 상태로 source하면 그 자리에서 죽는다.
set -eo pipefail

cd "$(dirname "$0")"

ROS_SETUP=${ROS_SETUP:-/opt/ros/jazzy/setup.bash}
if [[ ! -f $ROS_SETUP ]]; then
  echo "ROS 2 환경을 찾을 수 없습니다: $ROS_SETUP" >&2
  echo "다른 배포판이라면 ROS_SETUP=/opt/ros/<배포판>/setup.bash ./run.sh" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$ROS_SETUP"
colcon build --symlink-install
# shellcheck disable=SC1091
source install/setup.bash

exec ros2 launch robo_pinky_sim warehouse.launch.py "$@"
