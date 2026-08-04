#!/bin/bash
set -e

# ROS2(apt, system python)와 conda(python=3.12) 파이썬 버전을 맞춰뒀기 때문에
# setup.bash가 잡아주는 PYTHONPATH 위에 conda 환경을 얹으면 rclpy + torch를 같은 프로세스에서 쓸 수 있음
source /opt/ros/jazzy/setup.bash
source /ros2_ws/install/setup.bash
source /opt/conda/etc/profile.d/conda.sh
conda activate unified_env_ver2

exec "$@"
