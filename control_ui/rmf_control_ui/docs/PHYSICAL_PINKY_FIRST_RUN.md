# Physical Pinky First Startup and Manual Driving Procedure (실제 Pinky 최초 기동과 수동 주행 절차)

## 1. 목적과 완료 기준

이 문서는 Gazebo 가상 로봇이 아니라 실제 Pinky를 처음 기동하여 센서와 모터를
확인하고, 안전하게 저속 수동 주행하기까지의 절차를 설명한다. RMF 작업 배차와
Nav2 자율주행은 이 검사가 끝난 다음 단계다.

첫 기동의 완료 기준은 다음과 같다.

- 모터 드라이버가 연결된다.
- `/odom`이 지속적으로 발행된다.
- `/scan`이 지속적으로 발행된다.
- `/cmd_vel`을 보내면 바퀴가 움직인다.
- 명령을 중단하면 로봇이 정지한다.
- Gazebo 프로세스와 시뮬레이션 `/clock`을 사용하지 않는다.

전체 순서는 다음과 같다.

```text
기존 Gazebo 완전 종료
→ 실제 Pinky 전원·통신 준비
→ Pinky 컴퓨터에서 하드웨어 bringup
→ 관제 PC에서 ROS 토픽 확인
→ 바퀴를 띄운 상태로 짧은 수동 명령
→ 바닥에서 저속 수동 주행
→ 라이다·odom·TF 확인
→ 실물 지도 준비
→ Nav2 단독 시험
→ RMF 연결
```

## 2. 현재 project1 상태에서 주의할 점

현재 `project1`의 `pinky_01`, `pinky_02`는 `Gazebo 시뮬레이션` 출처로 저장되어
있다. 프로젝트 백엔드를 그대로 실행하면 실제 Pinky가 아니라 Gazebo Pinky가
다시 올라온다.

또한 RMF 프로젝트는 다음 이름을 기대한다.

```text
/pinky_01/odom
/pinky_01/scan
/pinky_01/cmd_vel
pinky_01/odom
pinky_01/base_footprint
```

현재 벤더의 실물 `pinky_bringup`은 네임스페이스 인자를 제공하지 않으므로
기본적으로 다음 이름을 사용한다.

```text
/odom
/scan
/cmd_vel
odom
base_footprint
```

따라서 **첫날에는 실물 Pinky를 단독 기동하여 하드웨어만 확인한다.** UI에서
출처를 실제 로봇으로 바꾸고 RMF에 연결하는 작업은 단독 검사가 끝난 뒤 진행한다.

## 3. 주행 공간과 비상 정지 준비

실물 로봇을 켜기 전에 다음을 준비한다.

- Pinky 주변 최소 1~2m를 비운다.
- 바퀴와 사람 또는 물체가 접촉하지 않게 한다.
- 첫 모터 시험은 받침대 위에서 바퀴를 공중에 띄우고 한다.
- 전원 차단 스위치 또는 배터리 분리 방법을 확인한다.
- 속도 명령을 보내는 터미널과 별도로 정지용 터미널을 연다.
- 처음부터 RMF 작업이나 Nav2 목표를 보내지 않는다.

정지 명령을 미리 준비한다.

```bash
ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist \
  "{linear: {x: 0.0}, angular: {z: 0.0}}"
```

다른 노드가 속도를 계속 발행 중이라면 한 번의 정지 메시지만으로 충분하지 않다.
그 경우 속도 발행 노드나 Nav2를 먼저 종료한다.

## 4. 기존 Gazebo와 백엔드 완전 종료

UI에서 실행 중인 프로젝트 백엔드를 중지한 뒤 남은 프로세스를 확인한다.

```bash
pgrep -af 'run_project1.sh|project1_bringup|project1_nav2|gz sim|parameter_bridge'
```

정상적으로 종료되었다면 관련 프로세스가 출력되지 않아야 한다. ROS 그래프에
Gazebo 시계가 남았는지도 확인한다.

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=22
ros2 topic info /clock -v
```

실물 단독 시험에서는 Gazebo `/clock`을 사용하지 않는다. 실제 Pinky bringup과
Nav2는 `use_sim_time:=False`여야 한다. ROS 2 노드 이름은 DDS 캐시에 잠시 남을 수
있으므로 실제 종료 여부는 프로세스 목록을 우선 기준으로 판단한다.

## 5. Pinky 전원과 컴퓨터 연결

### 5.1 Pinky에 내장 컴퓨터가 있는 경우

Pinky의 Raspberry Pi 또는 내장 컴퓨터에 접속하여 bringup을 실행한다.

```bash
ssh <pinky-user>@<pinky-ip>
```

### 5.2 관제 PC에 하드웨어를 직접 연결한 경우

모터와 라이다 직렬 장치가 관제 PC에 연결되어 있어야 한다. 현재 벤더 launch는
라이다 포트로 `/dev/ttyAMA0`을 사용한다.

```bash
ls -l /dev/ttyAMA0
groups
```

직렬 포트 사용 그룹은 일반적으로 `dialout`이다. 장치가 없거나 접근 권한이
없으면 라이다가 올라오지 않는다. 실제 장치가 `/dev/ttyUSB0` 또는
`/dev/ttyACM0`이라면 현재 launch와 다르므로 장치 이름을 먼저 확정해야 한다.

## 6. Pinky와 관제 PC의 ROS 환경 통일

Pinky 컴퓨터와 관제 PC 양쪽에서 같은 ROS Domain ID를 사용한다. 현재
`project1`의 Domain ID는 22다.

```bash
source /opt/ros/jazzy/setup.bash
source ~/robosapiens/robot_model/pinky_pro/install/setup.bash

export ROS_DOMAIN_ID=22
export ROS_LOCALHOST_ONLY=0
```

Pinky 컴퓨터의 저장소 경로가 다르면 실제 설치 경로를 사용한다.

```bash
source ~/robosapiens/robot_model/pinky_pro/install/setup.bash
```

관제 PC에서 통신을 확인한다.

```bash
ping <pinky-ip>
```

양쪽에서 다음 값이 같아야 한다.

```bash
echo "$ROS_DOMAIN_ID"
echo "$ROS_LOCALHOST_ONLY"
```

두 컴퓨터는 같은 로컬 네트워크에 두는 것이 좋다. VPN, Docker 네트워크, 방화벽,
서로 다른 Wi-Fi망은 DDS 탐색을 막을 수 있다.

## 7. Pinky 패키지 확인과 빌드

Pinky 컴퓨터에서 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
source ~/robosapiens/robot_model/pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=22

ros2 pkg prefix pinky_bringup
ros2 pkg prefix pinky_description
ros2 pkg prefix sllidar_ros2
```

세 명령 모두 패키지 경로를 출력해야 한다. 빌드가 필요하면 실행 중인 ROS 노드를
먼저 종료한 다음 진행한다.

```bash
cd ~/robosapiens/robot_model/pinky_pro
source /opt/ros/jazzy/setup.bash
colcon build
source install/setup.bash
```

## 8. 실제 Pinky 하드웨어 기동

Pinky 컴퓨터에서 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
source ~/robosapiens/robot_model/pinky_pro/install/setup.bash

export ROS_DOMAIN_ID=22
export ROS_LOCALHOST_ONLY=0

ros2 launch pinky_bringup bringup_robot.launch.xml
```

현재 bringup은 다음을 실행한다.

- Pinky URDF와 `robot_state_publisher`
- `/dev/ttyAMA0`의 SLLidar C1
- Pinky 모터 드라이버
- 배터리 상태 발행기
- 실물 시간 사용: `use_sim_time=False`

bringup 터미널은 닫지 않는다. 다음 오류를 확인하고 원문을 기록한다.

- `/dev/ttyAMA0` 접근 실패
- Dynamixel 또는 모터 연결 실패
- 라이다 health 오류
- 패키지를 찾을 수 없음
- 장치 권한 오류

## 9. 관제 PC에서 ROS 연결 확인

관제 PC의 새 터미널에서 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
source ~/robosapiens/robot_model/pinky_pro/install/setup.bash

export ROS_DOMAIN_ID=22
export ROS_LOCALHOST_ONLY=0

ros2 node list
ros2 topic list
```

현재 벤더 bringup을 그대로 실행했다면 다음 토픽이 예상된다.

```text
/odom
/scan
/cmd_vel
/joint_states
/tf
/tf_static
```

발행자와 구독자를 확인한다.

```bash
ros2 topic info /odom -v
ros2 topic info /scan -v
ros2 topic info /cmd_vel -v
```

기대 결과는 다음과 같다.

- `/odom`: 발행자 1개 이상
- `/scan`: 발행자 1개 이상
- `/cmd_vel`: 모터 드라이버 구독자 1개 이상

실제 메시지와 주기를 확인한다.

```bash
ros2 topic hz /odom
ros2 topic hz /scan

ros2 topic echo /odom --once
ros2 topic echo /scan --once
```

토픽 이름만 있고 메시지가 오지 않으면 정상 기동이 아니다.

## 10. TF 확인

단독 bringup에서는 기본 프레임을 확인한다.

```bash
ros2 run tf2_ros tf2_echo odom base_footprint
```

필요하면 다음도 확인한다.

```bash
ros2 run tf2_ros tf2_echo odom base_link
ros2 run tf2_tools view_frames
```

변환값이 반복 출력되어야 한다. 아직 AMCL과 Nav2를 실행하지 않았으므로
`map → base_footprint`가 없는 것은 정상이다. 이 단계의 기대 TF는 다음과 같다.

```text
odom → base_footprint → base_link → rplidar_link
```

## 11. 바퀴를 띄운 상태의 모터 시험

먼저 기존 `/cmd_vel` 발행자를 확인한다.

```bash
ros2 topic info /cmd_vel -v
```

Nav2나 다른 원격 조종 노드가 발행 중이면 먼저 종료한다. 받침대 위에서 매우 낮은
전진 속도를 1초간 보낸다.

```bash
timeout 1 ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist \
  "{linear: {x: 0.03}, angular: {z: 0.0}}"
```

즉시 정지한다.

```bash
ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist \
  "{linear: {x: 0.0}, angular: {z: 0.0}}"
```

제자리 회전도 낮은 값으로 1초만 시험한다.

```bash
timeout 1 ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist \
  "{linear: {x: 0.0}, angular: {z: 0.15}}"

ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist \
  "{linear: {x: 0.0}, angular: {z: 0.0}}"
```

다음을 확인한다.

- 전진 명령에서 양쪽 바퀴가 같은 전진 방향으로 도는가
- 회전 명령에서 두 바퀴가 반대 방향으로 도는가
- 명령이 끝나면 즉시 정지하는가
- `/odom` 위치 또는 yaw가 변하는가
- 비정상 소음이나 모터 과열이 없는가

바퀴 방향이 반대이거나 정지하지 않으면 바닥에 내려놓지 않는다.

## 12. 바닥에서 수동 저속 주행

공중 시험이 정상일 때만 바닥에 내려놓는다. 키보드 원격 조종을 실행한다.

```bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard
```

매우 낮은 선속도와 각속도로 시작한다. 벤더 teleop가 `/cmd_vel`에 발행하는지도
확인한다.

```bash
ros2 topic info /cmd_vel -v
```

짧게 전진, 후진, 좌회전, 우회전을 시험하고 매번 정지한다. 이후 Nav2 보정을
위해 다음 항목을 기록한다.

- 명령 속도
- 실제 이동 거리
- 직진 편향
- 제자리 회전 각도 오차
- `/odom`이 측정한 거리
- 라이다 스캔 상태
- 배터리 전압

## 13. RMF 연결 전에 필요한 네임스페이스 작업

UI에서 출처만 `실제 로봇`으로 바꾸는 것으로는 충분하지 않다. Fleet Adapter와
Nav2는 `/pinky_01/...`을 기다리지만 현재 실물 bringup은 `/odom`, `/scan`,
`/cmd_vel`을 사용하기 때문이다.

실물 RMF 연결 전 `pinky_bringup`에 다음을 적용해야 한다.

- `namespace:=pinky_01` launch 인자
- URDF `frame_prefix:=pinky_01/`
- `/pinky_01/odom`
- `/pinky_01/scan`
- `/pinky_01/cmd_vel`
- `/pinky_01/joint_states`
- `pinky_01/odom → pinky_01/base_footprint` TF

토픽만 remap하고 TF 프레임을 그대로 두면 여러 대 운용할 때 프레임이 충돌한다.
토픽과 TF를 함께 네임스페이스화해야 한다.

## 14. 단독 시험 후 UI 전환 순서

단독 하드웨어 시험을 통과한 다음 진행한다.

1. `로봇 등록`에서 `pinky_01`을 수정한다.
2. 값의 출처를 `실제 로봇`으로 선택한다.
3. 시스템 ID는 `pinky_01`로 유지한다.
4. 표시 이름은 `PK-01`로 유지한다.
5. 충전 위치를 실제 로봇이 놓인 위치와 맞춘다.
6. `저장하기`를 누른다.
7. `디스크로 내보내기`를 누른다.
8. 실물 전용 Pinky bringup을 별도로 실행한다.
9. 그 후 RMF/Nav2 백엔드를 실행한다.

현재 프로젝트 실행 스크립트는 Gazebo bringup부터 시작하는 구조이므로, 실물 운용
전용 실행 경로를 분리하여 점검해야 한다.

## 15. Nav2와 RMF로 넘어가는 기준

다음 결과가 정상일 때 실물 네임스페이스와 Nav2 연결 단계로 넘어간다.

```bash
ros2 node list
ros2 topic list | grep -E 'odom|scan|cmd_vel|joint|battery'
ros2 topic info /odom -v
ros2 topic info /scan -v
ros2 topic info /cmd_vel -v
ros2 topic hz /odom
ros2 topic hz /scan
```

Pinky bringup 터미널의 WARN과 ERROR도 함께 보존한다. 그다음 단계에서는 실제
건물 지도를 선택하거나 SLAM으로 만들고, `map → odom` 위치추정을 확인한 뒤
Nav2 단독 목표를 보낸다. Nav2가 안정적으로 멈추고 도착하는 것을 확인하기 전에는
RMF 작업을 제출하지 않는다.

## 관련 파일과 문서

- [실물 Pinky bringup launch](../../robot_model/pinky_pro/pinky_bringup/launch/bringup_robot.launch.xml)
- [Pinky 모터 파라미터](../../robot_model/pinky_pro/pinky_bringup/config/pinky_params.yaml)
- [THREE_SOURCES.md](THREE_SOURCES.md) — Mock, Gazebo와 실물 출처 차이
- [NAV2_PATH.md](NAV2_PATH.md) — 실제 지도, AMCL과 Nav2 연결
- [ROBOT_REGISTRATION.md](ROBOT_REGISTRATION.md) — 실제 로봇 출처 등록
- [MULTI_ROBOT_NAMESPACES.md](MULTI_ROBOT_NAMESPACES.md) — 토픽과 TF 네임스페이스
