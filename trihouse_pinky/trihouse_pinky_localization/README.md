# trihouse_pinky_localization

IMU와 바퀴 odometry를 표준화하고 `robot_localization` EKF로 결합한다.

- 입력: `/imu_raw`, `/odom`
- 표준 입력: `/imu/data_raw`, `/wheel/odometry`
- 출력: `/odometry/filtered`, TF `odom -> base_link`
- 구성: `config/ekf.yaml`, `launch/localization.launch.py`
- 제외: AMCL의 `map -> odom`, Nav2 경로 계획, FMS 상태 보고
