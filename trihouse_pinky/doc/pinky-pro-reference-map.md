# pinky_pro 참조 지도

> 원칙: 아래 파일을 직접 수정하지 않는다.

| 기능 | 경로 | 참조 방식 | 계획된 사용 |
|---|---|---|---|
| 베이스/odometry | `pinky_bringup/pinky_bringup/bringup.py` | 토픽 구독·알고리즘 참고 | safety 출력 `/cmd_vel`의 최종 소비자, odom/TF 이용 |
| 하드웨어/LiDAR | `pinky_bringup/launch/bringup_robot.launch.xml` | launch include | URDF, LiDAR, 모터, odometry, 배터리 기동 |
| 배터리 | `pinky_bringup/pinky_bringup/battery_publisher.py` | 토픽 구독 | fleet 상태와 readiness 입력 |
| IMU | `pinky_imu_bno055/src/main_node.cpp` | 실행·토픽 구독 | bringup에서 실행, 상태 감시 |
| 초음파/IR | `pinky_sensor_adc/src/main_node.cpp` | 실행·토픽 구독 | safety 근접 판정 |
| LED | `pinky_led` | 서비스 호출 | 상태/비상 표시 |
| 램프 | `pinky_lamp_control` | 서비스 호출 | 상태/비상 표시 |
| LCD | `pinky_emotion` | 서비스 호출 | 작업 상태 표시 |
| URDF | `pinky_description` | xacro include/확장 | 카메라 frame과 extrinsic 반영 |
| Nav2/AMCL/SLAM/map | `pinky_navigation` | launch include·액션 호출·파라미터 overlay | 위치 추정과 목표 주행, safety용 remap |
| 목표/취소/pose/상태 | `pinky_navigation/scripts/nav2_web_server.py` | 알고리즘 참고 | Nav2 action과 TF 처리 패턴 참고 |
| 카메라 시뮬레이션 | `pinky_gz_sim` | launch include·토픽 구독 | 실물 스트림과 구분된 인지 선검증 |

## 변경이 필요할 때

파라미터는 Trihouse launch에서 덮어쓰고, 토픽은 remap하며, 모델은 Trihouse xacro에서 include 후 확장한다. 벤더 파일 변경이 불가피하다면 별도 upstream 제안 또는 사유가 기록된 fork로 다룬다.

