# P0 실물 waypoint 실측과 전체 출고 주행 (`new_map_2`)

기준은 `PK_01`, namespace `pinky_01`, 지도 `new_map_2`다. 실기
`ROS_DOMAIN_ID`는 **12**다. 순서는 다음과 같다.

```text
주행 전 준비 -> 수동 waypoint 실측 -> 좌표 반영·발행
-> 자율/규칙 주행 확인 -> 터미널별 개별 기동 -> 주문 완주
-> 검증된 명령을 실기 통합 bringup으로 묶기
```

주문 한 건은 아래 7 step이 모두 `succeeded`이고 job이 `completed`여야 완주다.

```text
10 arm/pick           사람이 물건을 올린다
20 mobile/navigate    적재 지점으로 이동
30 fms/load           적재 처리
40 mobile/navigate    포장 인계 지점으로 이동
50 fms/handover       인계 처리
60 fms/wait           작업자가 완료 확인
70 mobile/return_home 충전소 복귀
```

---

## 0. 주행 전 준비 사항

### 0-1. 안전과 네트워크

- 물리 비상정지를 손이 바로 닿는 곳에 둔다.
- 첫 기동은 바퀴를 띄우거나 전방 2 m를 비운 상태에서 한다.
- `/pinky_01/cmd_vel` 발행자는 `safety_supervisor` 하나뿐이어야 한다.
- 수동·규칙 주행 모두 `/pinky_01/cmd_vel`에 직접 속도를 보내지 않는다.
- `RESULT: PASS` 전에는 주문을 넣지 않는다.
- 4060과 로봇은 같은 ROS 전용 Ethernet 서브넷에 둔다.
- `control_host`와 `FMS_TCP_BIND`에는 4060의 Ethernet IP를 쓴다.

모든 실기 셸:

```bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```

4060 `.env`:

```dotenv
ROS_DOMAIN_ID=12
FMS_TCP_BIND=<4060 Ethernet IP>
FMS_API_HOST=<4060 Ethernet IP>
PINKY_PK_01_IP=<PK_01 IP>
PINKY_PK_02_IP=<PK_02 IP>
```

### 0-2. build와 지도 배포

4060:

```bash
cd /home/syw/Trihouse/pinky_pro
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
```

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source pinky_pro/install/setup.bash
colcon build --symlink-install --packages-select \
  trihouse_interfaces trihouse_rmf_bridge trihouse_pinky_bringup \
  trihouse_pinky_docking trihouse_pinky_fleet trihouse_pinky_safety \
  trihouse_omx_adapter
```

로봇:

```bash
cd ~/trihouse_ws
source /opt/ros/jazzy/setup.bash
source pinky_pro/install/setup.bash
colcon build --symlink-install --packages-select \
  trihouse_interfaces trihouse_pinky_io trihouse_pinky_safety \
  trihouse_pinky_docking trihouse_pinky_fleet trihouse_pinky_bringup \
  trihouse_pinky_vision
```

4060에서 namespace용 Nav2 params를 만들고 지도와 함께 보낸다.

```bash
cd /home/syw/Trihouse
mkdir -p .trihouse/p0/nav2
scripts/derive_hardware_nav2_params.py \
  --source pinky_pro/pinky_navigation/params/nav2_params.yaml \
  --namespace pinky_01 \
  --output .trihouse/p0/nav2/hardware_pinky_01.yaml
head -1 .trihouse/p0/nav2/hardware_pinky_01.yaml  # 기대: pinky_01:
```

```bash
scp control_ui/rmf_control_ui/data/rmf_maps/new_map_2.yaml \
    control_ui/rmf_control_ui/data/rmf_maps/new_map_2.pgm \
    <로봇계정>@<PK_01 IP>:~/maps/
scp .trihouse/p0/nav2/hardware_pinky_01.yaml \
    config/narrow_zones.new_map_2.yaml \
    config/marker_docks.new_map_2.yaml \
    <로봇계정>@<PK_01 IP>:~/
```

### 0-3. 현재 좌표 파일 필수 경고

아래 두 파일은 현재 `map_pose`, `recognition_pose`, `source_measurements`가 완전히
같다.

- `control_ui/rmf_control_ui/data/import/trihouse_test_01_physical_features.jsonl`
- `control_ui/rmf_control_ui/data/import/trihouse_test_01_physical_features.new_map_2.jsonl`

`*.new_map_2.jsonl`은 기존 파일의 `source_map_name`만 `new_map_2.yaml`로 바꾼
복사본이다. **new_map_2 실측 완료 증거가 아니다.** 1절에서 다시 재기 전에는 전체
자율주행을 시작하지 않는다.

---

## 1. 수동 주행으로 waypoint 찍기

| 창 | 위치 | 역할 |
|---|---|---|
| M1 | 로봇 SSH | 온보드와 Nav2 실행 |
| M2 | 4060 | teleop |
| M3 | 4060 | AMCL pose 기록 |

### 1-1. M1 — 로봇과 Nav2

```bash
ssh <로봇계정>@<PK_01 IP>
cd ~/trihouse_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export REV='<2-2절에서 확인한 전체 map revision>'
```

```bash
ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK_01 namespace:=pinky_01 \
  map:=$HOME/maps/new_map_2.yaml map_revision:="$REV" \
  nav2_params_file:=$HOME/hardware_pinky_01.yaml \
  control_host:=<4060 Ethernet IP> control_port:=8788 \
  vision_enabled:=false 2>&1 | tee /tmp/hw.log
```

revision을 아직 발행하지 않았다면 2-2절을 먼저 실행한다.

### 1-2. M3 — namespace, 안전, pose

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export NS=/pinky_01
```

```bash
ros2 topic list | grep -E '/pinky_01/(scan|odom|amcl_pose|cmd_vel|cmd_vel_nav)$'
ros2 topic info "$NS/cmd_vel" --verbose | grep -E 'Publisher count|Node name'
```

`cmd_vel` 발행자가 정확히 하나이고 `safety_supervisor`인지 확인한다. 실제 시작 위치의
대략값으로 초기 pose를 준다.

```bash
ros2 topic pub --once "$NS/initialpose" \
  geometry_msgs/msg/PoseWithCovarianceStamped \
  '{header: {frame_id: "map"}, pose: {pose: {position: {x: 0.065, y: 0.227, z: 0.0}, orientation: {z: 0.0, w: 1.0}}}}'
```

pose 함수를 등록한다.

```bash
pose() { python3 -c "
import math, os, time, rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseWithCovarianceStamped
ns=os.environ.get('NS','').rstrip('/')
rclpy.init(); n=Node('waypoint_pose_probe'); got=[]
n.create_subscription(PoseWithCovarianceStamped, ns+'/amcl_pose', got.append, 10)
end=time.monotonic()+6
while rclpy.ok() and time.monotonic()<end: rclpy.spin_once(n, timeout_sec=0.2)
if got:
    m=got[-1]; p=m.pose.pose.position; q=m.pose.pose.orientation; c=m.pose.covariance
    yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
    print('x=%.4f y=%.4f yaw=%.4f rad (%.1f deg)'%(p.x,p.y,yaw,math.degrees(yaw)))
    print('stddev x=%.3f m y=%.3f m yaw=%.3f rad'%(max(c[0],0)**.5,max(c[7],0)**.5,max(c[35],0)**.5))
else: print('amcl_pose 없음: domain, namespace, AMCL 확인')
n.destroy_node(); rclpy.shutdown()"; }
```

### 1-3. M2 — teleop

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export NS=/pinky_01
ros2 run teleop_twist_keyboard teleop_twist_keyboard \
  --ros-args -r /cmd_vel:="$NS/cmd_vel_nav"
```

처음에 `x`를 여러 번 눌러 선속도를 **0.06 m/s 이하**로 내린다. 절대
`$NS/cmd_vel`로 remap하지 않는다.

### 1-4. 지점별 측정

넓은 곳에서 조금 이동·회전해 AMCL을 수렴시킨다. M3의 `pose`에서 x/y stddev가
**0.12 m 이하**일 때 다음 순서로 잰다.

```text
charging_station_01, charging_station_02
TRIHOUSE-TEST-01-BOTTLENECK-01, TRIHOUSE-TEST-01-BOTTLENECK-02
packing_station_loading_dock_01, packing_station_loading_dock_02
safety_zone_01
ambient_storage_loading_dock_01
chilled_storage_loading_dock_01
frozen_storage_loading_dock_01
```

각 지점에서 정차 후 2~3초 기다리고 `pose`를 실행해 x/y/yaw/stddev를 기록한다.
가능하면 벗어났다가 재접근한다. 도크는 바구니가 선반을 향한 자세로 잰다. 병목은
x/y만 잰다. 근접 gate가 도크 진입을 막으면 안전 임계값을 낮추지 말고, 바퀴가 굴러
odometry가 갱신되도록 사람이 천천히 밀어 위치시킨 뒤 pose만 읽는다.

---

## 2. 좌표 반영·지도 발행·nav graph 생성

### 2-1. JSONL 반영

new_map_2 실측 정본:

```text
control_ui/rmf_control_ui/data/import/trihouse_test_01_physical_features.new_map_2.jsonl
```

각 record의 `map_pose`, `source_map_name`을 갱신하고 `source_measurements[]`에
timestamp, note, map_x/y/yaw, stddev를 **추가**한다. 병목에는 yaw가 없다. 기존
측정 이력은 삭제하지 않는다. fiducial `recognition_pose`는 그 인식 위치도 실제로
다시 잰 경우에만 변경한다.

### 2-2. Docker, 지도 발행, revision

```bash
cd /home/syw/Trihouse
docker compose -p trihouse_p0 \
  -f compose.yaml -f compose.control.yaml -f compose.edge_4060.yaml up -d
until curl -fsS -m 2 http://127.0.0.1:8080/ready; do sleep 3; done; echo
python3 scripts/p0_publish_map.py \
  control_ui/rmf_control_ui/data/rmf_maps/new_map_2.yaml | tail -1
```

```bash
export REV=$(docker exec trihouse-mysql mysql \
  -uroot -p"$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)" \
  -N -B -e "SELECT map_revision FROM trihouse_fms.map_revisions WHERE state='published' ORDER BY published_at DESC LIMIT 1;" 2>/dev/null)
echo "REV=$REV"
```

JSONL이 바뀌면 revision도 바뀌어야 한다. 이후 모든 셸과 로봇이 같은 `REV`를 쓴다.

### 2-3. 실행 자산

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=12
python3 control_tower/bringup/p0_runtime_assets.py \
  --fms-base-url http://127.0.0.1:8080 \
  --map-name trihouse_test_01 --map-revision "$REV" \
  --features control_ui/rmf_control_ui/data/import/trihouse_test_01_physical_features.new_map_2.jsonl \
  --nav2-source pinky_pro/pinky_navigation/params/nav2_params.yaml \
  --world-source control_tower/bringup/p0_world.sdf \
  --map-yaml control_ui/rmf_control_ui/data/rmf_maps/new_map_2.yaml \
  --output-dir .trihouse/p0 \
  --robot PK_01:pinky_01 --robot PK_02:pinky_02
```

```bash
grep -A1 'BOTTLENECK' .trihouse/p0/nav_graph.yaml | grep -E 'mutex'
python3 scripts/p0_show_map.py new_map_2
```

2대 주행에는 `mutex:`가 필요하다. `mutex_group:`은 RMF가 읽지 않는다. 모든 도크가
통과 가능하고 필요한 통로 폭이 0.14 m 이상이어야 한다.

---

## 3. Nav2와 ArUco 협로 후진 도킹

### 3-1. 전환 규칙

일반 목적지는 Nav2가 처리한다. 창고 협로는 Nav2가 회전 가능한 앞 공간까지만 가고,
그 뒤는 `/trihouse/dock` action이 맡는다.

```text
Nav2 -> 창고별 마커 탐색 반경(entry) 정차
-> vision readiness READY 확인
-> 지정 ArUco ID를 연속 관측
-> 마커 bearing=0, 창고별 standoff까지 정렬
-> 벽에서 먼 설정 방향으로 정확히 180도 회전
-> odom yaw를 유지하면서 실측 거리만큼 직선 후진
-> map pose와 최종 적재 pose 대조
```

### 3-2. 마커 도킹 안전 규칙

마커 정렬 중에는 ID, `ttl_ms`, `confidence`, 그리고 **로봇이 메시지를 수신한 시각**을
확인한다. camera/4060과 로봇의 시계가 달라도 `header.stamp` 차이 때문에 신선도를
잘못 판정하지 않기 위해서다. 오래된 수신, 다른 ID, 낮은 confidence, vision readiness
저하는 즉시 0속도/실패다. 180도 회전 뒤 전방 카메라에서 마커가 사라지는 것은
정상이며, 이후에는 `odom ->
base_footprint`로 회전각·후진거리·yaw를 폐루프 제어한다. odom TF 소실, phase timeout,
취소 시 `cmd_vel_dock`에 0을 발행한다. `cmd_vel_dock`은 safety supervisor를 거쳐야
하며 모터 `cmd_vel`에 직접 연결하지 않는다.

상온·냉장은 대각선 출입구이므로 각각 별도 standoff와 회전 방향을 잰다. 냉동은 벽
쪽이므로 회전 외접원이 벽을 침범하지 않는 방향만 허용한다. 세 값을 서로 복사하지
않는다.

현재 `config/narrow_zones.new_map_2.yaml`에서 **활성화된 것은 충전소 두 곳뿐**이다.

| 존 | 탈출 규칙 | exit_target |
|---|---|---|
| `charging_station_01` | 0.680 m 직진 → -1.276 rad 회전 → 0.345 m 직진 | (0.841, -0.111, -1.276) |
| `charging_station_02` | 0.650 m 직진 → -1.083 rad 회전 → 0.333 m 직진 | (0.841, -0.111, -1.083) |

두 충전소 탈출은 기존 `narrow_zone_pilot`이 담당한다. 창고 진입은
`config/marker_docks.new_map_2.yaml`이 담당하며 현재 세 프로필 모두
`verified: false`다. `minimum_confidence`, 연속 관측 수/timeout, standoff, 회전 방향,
후진 거리를 현장에서 잰 뒤에만 `true`로 바꾼다. 미검증 프로필은 action server가
적재하지 않으므로 로봇이 움직이지 않는다.

### 3-3. 실물 도킹 전: 카메라·마커 관측 gate

도킹 action보다 먼저 카메라 전송과 화면 속 marker/QR 인식을 따로 확인한다. 이 단계에서는
바퀴를 움직이지 않고 `docking_enabled:=false`로 둔다. R1에서 `vision_enabled:=true`로
camera streamer만 기동한 뒤, R2와 4060에서 아래를 확인한다.

```bash
# R2 (로봇): ROS camera stream 상태. HEALTHY가 지속되어야 한다.
source /opt/ros/jazzy/setup.bash
source ~/trihouse_ws/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
ros2 topic echo /pinky_01/trihouse/vision/stream_health
```

```bash
# 4060: RTSP를 10분 decode해 카메라 전송 자체를 검증한다.
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export MTX_VIEWER_PASS='<MediaMTX viewer password>'
$(ros2 pkg prefix --share trihouse_pinky_vision)/scripts/verify_rtsp.sh \
  "rtsp://viewer:${MTX_VIEWER_PASS}@<4060 Ethernet IP>:8554/pinky/CAM-PK-01" 600
```

기존 `model/worker/marker/edge_perception.py`에는 QR과 `DICT_5X5_50` ArUco ID/corner/camera-frame
`rvec/tvec` 검출이 이미 있다. 그러나 현재 실기 launch에는 RTSP를 그 코드에 연결해
검출 결과를 화면/로그로 보여 주고 `MarkerObservation`을 발행하는 bridge 실행 파일이
아직 없다. 따라서 이 gate에서는 영상만 검증하고, marker ID가 보인다는 말만으로
`verified: true` 또는 `docking_enabled:=true`로 넘어가지 않는다. bridge가 추가된 뒤에는
다음 순서로 한 창고씩 재개한다.

```text
RTSP/StreamHealth HEALTHY
-> 화면에서 예상 QR·ArUco ID가 연속 검출됨
-> camera-frame rvec/tvec 기록
-> calibration + camera→base 변환
-> base MarkerObservation 및 readiness가 연속 갱신됨
-> marker profile 검증 및 저속 도킹 시험
```

### 3-4. 영상 pose 차단 조건

저장소에는 아직 카메라 intrinsic/extrinsic 정본과
`trihouse/vision/marker_observation/base` 발행기가 없다. RTSP에서 ID만 보였다는 것은
거리·각도 pose가 검증됐다는 뜻이 아니다. 캘리브레이션과 camera→base 변환을 완료해
다음 두 토픽이 실제로 나오기 전에는 `verified: true`로 바꾸지 않는다. bridge는 새
프레임에 대해서만 `MarkerObservation`을 발행하고 `ttl_ms`를 부여해야 한다. 과거 frame을
재발행해 TTL을 연장해서는 안 된다.

```bash
ros2 topic echo /pinky_01/trihouse/vision/readiness
ros2 topic echo /pinky_01/trihouse/vision/marker_observation/base
```

### 3-5. 창고 한 곳을 활성화하는 순서

한 번에 한 창고만 측정한다. 상온/냉장/냉동 값을 복사하지 않는다.

1. teleop으로 출입구 앞의 넓은 공간에 세우고 물리 비상정지를 준비한다.
2. 해당 ID가 연속으로 보이고 `pose.position.x/y`, confidence, 관측 주기를 기록한다.
3. 마커가 화면 중앙에 오도록 맞춘 뒤 M3 `pose`의 map x/y를
   `marker_docks.new_map_2.yaml`의 `activation_x_m/y_m`와
   `narrow_zones.new_map_2.yaml`의 `entry`에 같은 값으로 기록한다. `activation_radius_m`은
   반복 정차 오차와 회전 가능한 빈 공간 안에서만 정한다. 이 원 밖의 수동 Dock action은
   코드가 거절한다.
4. 그 자리에서 로봇 회전 외접원을 재어 벽에서 먼 `turn_direction`(`1`=반시계,
   `-1`=시계)을 고른다.
5. 마커까지의 정렬 거리 `standoff_m`와 회전 후 적재점까지의 직선
   `reverse_distance_m`를 최소 3회 재서 중앙값을 쓴다.
6. `marker_docks.new_map_2.yaml`의 나머지 tolerance/timeout을 채우고 그 창고만
   `verified: true`로 바꾼다.
7. `narrow_zones.new_map_2.yaml`에서 같은 창고의 `entry`, `zone`, 안전한 전진
   `exit`을 채운 뒤 `enabled: true`로 바꾼다.
8. 무적재·최저속도에서 1회 시험하고, 성공 후에도 최종 map pose 오차를 기록한다.

`verified`와 `enabled` 중 하나라도 false면 실행 대상이 아니다. 두 파일은 역할이
다르다. narrow 표는 Nav2가 멈출 앞 공간과 도크 탈출을 정하고, marker 표는 카메라
정렬·회전·후진을 정한다.

### 3-6. 마커 도킹 단독 시험 명령

이 시험은 1절의 일반 waypoint 측정과 다르다. 다음 조건을 **모두** 충족한 한 창고에서만
실행한다: base-frame marker 토픽이 실제 갱신됨, 해당 profile `verified: true`, 해당
`activation_*`이 실측됨, 로봇이 그 activation 반경 안에 수동으로 정차함. `verified: false`
상태에서 아래 action은 정상적으로 거절되는 것이 맞다.

R1은 5-9절의 `vision_enabled:=true docking_enabled:=true` launch를 사용한다. R2의 별도
터미널에서 다음을 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
source ~/trihouse_ws/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export NS=/pinky_01

ros2 topic echo --once "$NS/trihouse/vision/readiness"
ros2 topic echo --once "$NS/trihouse/vision/marker_observation/base"
ros2 topic hz "$NS/trihouse/vision/marker_observation/base"
ros2 action info "$NS/trihouse/dock"
```

`readiness`가 `STATE_READY`이고 marker ID/`pose.pose.position`/`confidence`가 계속 갱신되는
것을 먼저 확인한다. `ros2 topic hz`는 Ctrl-C로 끝낸다. 이어서 **이미 activation 반경에
세운 로봇**에서만, 예를 들어 상온 marker `2`를 다음처럼 한 번 호출한다. 일반 위치에서
이 명령으로 Nav2 staging을 생략하면 안 된다.

```bash
ros2 action send_goal --feedback "$NS/trihouse/dock" \
  trihouse_interfaces/action/Dock \
  "{job_id: 'manual-marker-test', job_step_id: 'ambient-01', marker_id: '2', target_offset: {position: {x: 0.0, y: 0.0, z: 0.0}, orientation: {x: 0.0, y: 0.0, z: 0.0, w: 1.0}}, linear_tolerance_m: 0.0, angular_tolerance_rad: 0.0, timeout: {sec: 0, nanosec: 0}}"
```

시험 중에는 물리 비상정지를 잡고, 안전 gate의 `/cmd_vel`은 한 발행자만 유지한다. 실제
작업에서는 fleet이 Nav2로 같은 staging 위치까지 먼저 이동한 뒤 이 action을 호출한다.

### 3-7. 코드·설정·테스트 파일

| 파일 | 역할 |
|---|---|
| `config/narrow_zones.new_map_2.yaml` | 지도별 규칙 실측값 |
| `config/marker_docks.new_map_2.yaml` | 창고별 ArUco ID와 도킹 실측 gate |
| `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/narrow_zone_pilot.py` | 파싱, 존 판정, step 속도, pose 검증 |
| `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py` | Nav2↔규칙 전환과 실행·중단 |
| `trihouse_pinky/trihouse_pinky_docking/trihouse_pinky_docking/marker_controller.py` | 마커 정렬·180도 회전·yaw 유지 후진 |
| `trihouse_pinky/trihouse_pinky_docking/trihouse_pinky_docking/marker_dock_node.py` | Dock action·관측·TF·안전 정지 |
| `trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_pinky.launch.py` | 실기 파라미터 배선 |
| `trihouse_pinky/test/test_narrow_zone_pilot.py` | 규칙 단위·계약 테스트 |
| `trihouse_pinky/test/test_marker_docking_controller.py` | 마커 도킹 상태·속도 계약 테스트 |
| `notebooks/narrow_zone_measurement.ipynb` | 협로 실측 계산 |
| `docs/runbooks/p0-narrow-zone-measurement.md` | 협로 재측정 절차 |

---

## 4. 전체 주행 착수 gate

- new_map_2에서 다시 잰 waypoint가 JSONL에 들어 있다.
- `p0_show_map.py new_map_2`에서 모든 도크가 통과 가능하다.
- 병목 키가 `mutex:`다.
- 모든 실기 프로세스가 domain 12다.
- `/pinky_01/scan`, `/pinky_01/odom`이 있다.
- `/pinky_01/cmd_vel` 발행자는 safety 하나다.
- Nav2 lifecycle 실패가 없다.
- 규칙주행이 필요하면 `협로 존 2개 적재` 로그가 있다.
- 창고 도킹 전 base-frame MarkerObservation과 vision readiness가 실제로 갱신된다.
- 시험할 창고 하나만 narrow `enabled`와 marker `verified`가 true다.
- Gazebo, `sim_hardware`, `ros_gz_bridge`가 없다.

---

## 5. 통합 bringup 전: 터미널로 모두 개별 기동

먼저 이 방식으로 한 주문을 완주한다. 프로세스별 창을 두면 실패 지점을 바로 알 수 있다.

### 5-1. 터미널 배치

| 창 | 위치 | 프로세스 |
|---|---|---|
| C1 | 4060 | Docker/FMS |
| C2 | 4060 | RMF core |
| C3 | 4060 | PK_01 fleet adapter |
| C4 | 4060 | job runner |
| C5 | 4060 | executor worker |
| C6 | 4060 | RMF gateway worker |
| C7 | 4060 | 판정·주문·완료 처리 |
| C8 | 4060 | DB 진행 관측 |
| R1 | 로봇 | Pinky/Nav2 launch |
| R2 | 로봇 | 센서·안전·초기 pose |

### 5-2. C2~C7 공통 환경

각 새 셸에서 실행한다.

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
export PYTHONPATH="/home/syw/Trihouse:$PYTHONPATH"
export REV=$(docker exec trihouse-mysql mysql \
  -uroot -p"$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)" \
  -N -B -e "SELECT map_revision FROM trihouse_fms.map_revisions WHERE state='published' ORDER BY published_at DESC LIMIT 1;" 2>/dev/null)
echo "REV=$REV"
```

### 5-3. C1 — Docker/FMS

```bash
cd /home/syw/Trihouse
docker compose -p trihouse_p0 \
  -f compose.yaml -f compose.control.yaml -f compose.edge_4060.yaml up -d
until curl -fsS -m 2 http://127.0.0.1:8080/ready; do sleep 3; done; echo
```

### 5-4. C2 — RMF core

```bash
ros2 launch trihouse_rmf_bridge rmf_core.launch.py \
  use_sim_time:=false start_visualization:=false \
  2>&1 | tee /tmp/hw_rmf_core.log
```

### 5-5. C3 — PK_01 adapter

```bash
ros2 launch trihouse_rmf_bridge pinky_easy_fleet_adapter.launch.py \
  nav_graph:=/home/syw/Trihouse/.trihouse/p0/nav_graph.yaml \
  robot_name:=PK_01 rmf_map_name:=L1 \
  charger_waypoint:=charging_station_01 \
  map_revision:="$REV" fms_base_url:=http://127.0.0.1:8080 \
  robot_status_topic:=/pinky_01/trihouse/status \
  transport_action:=/pinky_01/trihouse/transport/execute \
  use_sim_time:=false 2>&1 | tee /tmp/hw_adapter_pk01.log
```

### 5-6. C4 — job runner

```bash
python3 -m control_tower.task_manager.job_runner_node \
  --fms-base-url http://127.0.0.1:8080 2>&1 | tee /tmp/hw_job_runner.log
```

### 5-7. C5 — executor worker

```bash
python3 -m control_tower.task_manager.executor_worker_node \
  --fms-base-url http://127.0.0.1:8080 \
  --environment hardware \
  --act-config /home/syw/Trihouse/config/act.simulation.yaml \
  2>&1 | tee /tmp/hw_executor.log
```

`act.simulation.yaml`은 이번 범위의 팔 동작만 fake로 처리한다. 모바일 주행을 시뮬로
바꾸지 않는다.

### 5-8. C6 — RMF gateway worker

```bash
python3 -m control_tower.rmf_adapter.rmf_gateway_worker_node \
  --fms-base-url http://127.0.0.1:8080 \
  --fleet-name project1_pinky --worker-id trihouse-rmf-worker \
  2>&1 | tee /tmp/hw_rmf_worker.log
```

### 5-9. R1 — 로봇 launch

```bash
ssh <로봇계정>@<PK_01 IP>
cd ~/trihouse_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export REV='<C1에서 확인한 전체 revision>'
```

3-4절의 base-frame marker pose 배선을 검증한 뒤에만:

```bash
ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK_01 namespace:=pinky_01 \
  map:=$HOME/maps/new_map_2.yaml map_revision:="$REV" \
  nav2_params_file:=$HOME/hardware_pinky_01.yaml \
  narrow_zones_file:=$HOME/narrow_zones.new_map_2.yaml \
  marker_docks_file:=$HOME/marker_docks.new_map_2.yaml \
  narrow_map_name:=new_map_2 \
  control_host:=<4060 Ethernet IP> control_port:=8788 \
  vision_enabled:=true docking_enabled:=true 2>&1 | tee /tmp/hw.log
```

### 5-10. R2 — 로봇 판정과 초기 pose

```bash
ssh <로봇계정>@<PK_01 IP>
source /opt/ros/jazzy/setup.bash
source ~/trihouse_ws/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export NS=/pinky_01
```

```bash
grep -c 'Managed nodes are active' /tmp/hw.log  # 기대 2
grep -E 'Failed to bring up all requested|Failed to change state' /tmp/hw.log
ros2 topic echo --once "$NS/scan" sensor_msgs/msg/LaserScan | head -3
ros2 topic echo --once "$NS/odom" nav_msgs/msg/Odometry | head -3
ros2 topic echo --once "$NS/trihouse/battery" sensor_msgs/msg/BatteryState | head -3
ros2 topic echo --once "$NS/trihouse/readiness" trihouse_interfaces/msg/Readiness
ros2 topic info "$NS/cmd_vel" --verbose | grep -E 'Publisher count|Node name'
```

초기 pose는 new_map_2에서 다시 잰 실제 시작 좌표다.

```bash
ros2 topic pub --once "$NS/initialpose" \
  geometry_msgs/msg/PoseWithCovarianceStamped \
  '{header: {frame_id: "map"}, pose: {pose: {position: {x: <실측 x>, y: <실측 y>, z: 0.0}, orientation: {z: 0.0, w: 1.0}}}}'
```

### 5-11. C7 — 판정과 주문

```bash
python3 scripts/verify_robot_status.py pinky_01 20
```

`publishers` 모두 1, `frame_id: map`, `dispatchable: true`, `errors: []`,
`RESULT: PASS`여야 한다.

```bash
docker exec trihouse-mysql mysql \
  -uroot -p"$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)" \
  --table -e "SELECT product_code,temperature_zone,available_qty,reserved_qty,state FROM trihouse_fms.inventory_lots ORDER BY temperature_zone,product_code;"
```

```bash
ORDER=$(curl -sS -X POST http://127.0.0.1:8080/api/v1/orders \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: hw-$(date +%s)" \
  -d '{"requested_by":"W-OP-01","priority":"normal","items":[{"product_code":"SKU-DUMPLING","quantity":1}]}')
echo "$ORDER" | python3 -m json.tool
export JOB=$(echo "$ORDER" | python3 -c 'import sys,json; print(json.load(sys.stdin)["job_id"])')
echo "JOB=$JOB"
```

step 10 뒤, step 20 전 물건을 올린다. step 60에서 실제 인계를 확인하고 호출한다.

```bash
curl -sS -X POST \
  "http://127.0.0.1:8080/api/v1/jobs/$JOB/worker-completion" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: worker-completion-$JOB" \
  -d '{"worker_id":"W-OP-01","completion_note":"hardware run"}' \
  | python3 -m json.tool
```

### 5-12. C8 — 진행 관측과 완주

```bash
cd /home/syw/Trihouse
export JOB=<C7에서 출력한 job ID>
watch -n2 'docker exec trihouse-mysql mysql \
  -uroot -p"$(grep -E "^MYSQL_ROOT_PASSWORD=" /home/syw/Trihouse/.env | cut -d= -f2-)" \
  --table -e "SELECT s.step_no,s.executor_type,s.action_type,s.state,IFNULL(m.channel,\"-\") ch,IFNULL(m.state,\"-\") outbox FROM trihouse_fms.job_steps s LEFT JOIN trihouse_fms.integration_messages m ON m.job_step_id=s.job_step_id WHERE s.job_id='"$JOB"' ORDER BY s.step_no;" 2>/dev/null'
```

```bash
docker exec trihouse-mysql mysql \
  -uroot -p"$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)" \
  --table -e "SELECT job_id,state,IFNULL(assigned_mobile_id,'-') robot FROM trihouse_fms.jobs WHERE job_id=$JOB; SELECT step_no,executor_type,action_type,state,final_outcome_reason_code FROM trihouse_fms.job_steps WHERE job_id=$JOB ORDER BY step_no;"
```

7 step 모두 `succeeded`, job `completed`, 실제 충전 위치 복귀면 성공이다.

---

## 6. 개별 기동 성공 후: 실기 통합 bringup 구성

5절 성공 뒤에만 묶는다. 목표는 다음 3개 터미널이다.

| 창 | 위치 | 역할 |
|---|---|---|
| H1 | 4060 | Docker 확인 + 관제 ROS 통합 bringup |
| H2 | 로봇 | Pinky/Nav2 통합 bringup |
| H3 | 4060 | 판정·주문·관측·완료 처리 |

한 ROS launch가 서로 다른 두 호스트를 직접 관리하게 만들지 않는다. 완전 원클릭 배포가
필요하면 두 호스트의 명령을 systemd service로 만들고 별도 배포 도구가 health check와
시작 순서를 관리한다.

### 6-1. 4060 실기 bringup

새 실기 전용 launch/감독 스크립트는 다음을 한 프로세스 그룹으로 시작한다.

1. `rmf_core.launch.py`, `use_sim_time:=false`
2. PK_01 `pinky_easy_fleet_adapter.launch.py`
3. `job_runner_node`
4. `executor_worker_node --environment hardware`
5. `rmf_gateway_worker_node`

Gazebo, `sim_hardware`, `ros_gz_bridge`, 관제 PC 쪽 `trihouse_pinky.launch.py`,
`use_sim_time:=true`는 포함하지 않는다.

권장 파일과 책임:

```text
trihouse_rmf_bridge/launch/p0_hardware_control.launch.py
  관제 ROS 프로세스 5개 기동, argument 전달, 종료 전파

scripts/p0_hardware_up.sh
  Docker readiness, published REV 조회, runtime assets 생성,
  p0_hardware_control.launch.py 실행

scripts/p0_hardware_down.sh
  실기 관제 프로세스만 정상 종료; Docker 데이터 유지
```

필수 argument:

```text
map_revision, nav_graph, fms_base_url, fleet_name,
robot_id/robot_name, robot_namespace, charger_waypoint,
environment=hardware
```

스크립트가 DB에서 `REV`를 조회해 launch에 넘겨야 한다. 자식 하나가 죽으면 비정상
상태를 반환하고, 종료 시 모든 자식에 SIGINT를 전달하며, 로그는 프로세스별로 분리한다.

### 6-2. 로봇 bringup

`trihouse_pinky.launch.py`는 `narrow_zones_file`, `narrow_map_name`,
`marker_docks_file`을 받고, `docking_enabled:=true`일 때 marker action server를 함께
기동한다.

```python
{
    'robot_id': robot_id,
    'map_revision': map_revision,
    'narrow_zones_file': narrow_zones_file,
    'narrow_map_name': narrow_map_name,
}
```

최종 로봇 명령:

```bash
ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK_01 namespace:=pinky_01 \
  map:=$HOME/maps/new_map_2.yaml map_revision:="$REV" \
  nav2_params_file:=$HOME/hardware_pinky_01.yaml \
  narrow_zones_file:=$HOME/narrow_zones.new_map_2.yaml \
  marker_docks_file:=$HOME/marker_docks.new_map_2.yaml \
  narrow_map_name:=new_map_2 \
  control_host:=<4060 Ethernet IP> control_port:=8788 \
  vision_enabled:=true docking_enabled:=true
```

### 6-3. 완료 조건

- `verify_robot_status.py pinky_01 20`이 `RESULT: PASS`
- 모든 실기 프로세스가 domain 12
- Gazebo/가짜 센서 0개
- `cmd_vel` 발행자 safety 하나
- `협로 존 2개 적재` 로그
- 5절과 같은 주문 7 step 완주
- Ctrl-C 한 번으로 해당 호스트의 모든 자식 종료
- 재기동 후 중복 publisher 없음

통합 bringup은 터미널 수를 줄이는 작업이지 검증 항목을 줄이는 작업이 아니다.

---

## 7. 반복 시험과 종료

로봇 1대에서는 job 하나가 끝나기 전에 새 주문을 넣지 않는다.

| 회차 | SKU | 구역 |
|---|---|---|
| 1 | `SKU-DUMPLING` | frozen |
| 2 | `SKU-YOGURT` | chilled |
| 3 | `SKU-ORANGE` | ambient |

실패 로그:

```bash
for f in /tmp/hw_rmf_core.log /tmp/hw_adapter_pk01.log \
  /tmp/hw_job_runner.log /tmp/hw_executor.log /tmp/hw_rmf_worker.log; do
  echo "== $f"
  grep -aE '\[(ERROR|WARN)\]|Traceback' "$f" | tail -8 | cut -c1-180
done
```

로봇:

```bash
grep -aE '\[(ERROR|WARN)\]' /tmp/hw.log | tail -30 | cut -c1-200
```

각 foreground 터미널에서 Ctrl-C로 종료한다. `scripts/sim_teardown.sh`는 실기에 쓰지
않는다. Docker/FMS 데이터는 다음 회차를 위해 유지해도 된다.

## 절대 규칙

- 실기 ROS domain은 **12**다.
- `p0_simulation_bringup.sh`를 실기에 쓰지 않는다.
- `cmd_vel`에 직접 teleop하거나 규칙 속도를 발행하지 않는다.
- `new_map_2.pgm`은 SLAM 원본이다. 통로를 넓히거나 픽셀을 덮어쓰지 않는다.
- waypoint와 협로 값은 사용 중인 지도에서 다시 잰 값만 쓴다.
- `source_map_name`만 바꾼 JSONL을 재실측 파일로 취급하지 않는다.
- 규칙 YAML 배선 여부를 로봇 로그로 확인한다.
- 물리 비상정지가 항상 우선이다.

관련 문서:

- `docs/runbooks/p0-new-map-waypoint-measurement.md`
- `docs/runbooks/p0-narrow-zone-measurement.md`
- `docs/validation/2026-08-18-pinky-hardware-nav2-smoke.md`
- `docs/validation/2026-08-20-sr-runtime-wiring-map.md`
