# Pinky·Open-RMF·FMS 수직 통합 수동 검증서

작성 기준일: 2026-08-12  
설계 기준: \`docs/superpowers/specs/2026-08-12-gazebo-rmf-mysql-pinky-integration-design.md\`

## 1. 이번 구현 결과와 시험 범위

이번 구현은 다음 연결 경계를 코드로 만들었다.

~~~text
Control Tower SequenceOrchestrator
  └─ FMS 내부 HTTP API
       ├─ MySQL: Job → Step 10~60 → Attempt → Event
       ├─ RMF dispatch outbox
       └─ TCP 8788: Pinky status/task event
            ↑
RMF task worker → Open-RMF task API
            ↓
Trihouse EasyFullControl adapter
  └─ FMS command claim → TaskContext → Pinky ExecuteTransport
       └─ Nav2 → Safety Supervisor → cmd_vel
~~~

코드로 연결되고 단위 검증된 항목:

- 공용 \`TaskContext\`가 RMF task, command, ROS action, 상태, 이벤트까지 전달된다.
- Control Tower가 출고 Job의 Step 10~60을 만들고, 현재 step 성공 뒤에만 다음 step을 dispatch한다.
- FMS Gateway가 Job/Step, RMF dispatch, command claim, TCP schema v3 상태·이벤트를 처리한다.
- 동일 목적 실패 재시도는 같은 \`job_step_id\`의 새 message/attempt로 처리된다.
- 목적 변경·취소는 자동 진행하지 않고 \`replan_required\`로 latch된다.
- Pinky 배터리는 \`NORMAL / LOCAL_ONLY / RETURN_REQUIRED\`로 분류되고 \`dispatchable\`에 반영된다.
- \`PK_01\`, \`PK_02\`, \`OMX_01\`, \`OMX_02\`, \`project1_pinky\` 및 project1 waypoint registry가 DB seed/migration과 일치한다.
- \`control_system\` 원본을 건드리지 않고 \`control_system_test\`를 독립 local clone으로 만들고, 전용 \`trihouse-integration\` 브랜치에서 native adapter를 제거하고 Nav2 \`cmd_vel_nav\`을 Safety로 연결한다.
- \`control_system_rmf.launch.py\`가 control_system core/Gazebo/Nav2, Pinky runtime, 단일 Trihouse adapter와 RMF worker를 함께 시작한다.

아직 통합 완료로 판정하면 안 되는 항목:

- 현재 원본 project1에는 \`nav_graphs/0.yaml\`이 없다. UI에서 project1을 다시 export해야 launch Gate를 통과한다.
- RMF task booking 응답에 실제 \`assigned_to\`가 없으면 요청한 PK_01을 배정 결과로 꾸미지 않는다. booking ID를 \`RMF_ASSIGNMENT_PENDING\` 근거로 보존하고 message를 \`sent/indeterminate\`에 두므로, assignment observer/cancel reconciliation 전에는 주행과 중복 제출이 모두 차단된다.
- Step 30 OMX 적재와 Step 60 FMS handover outbox consumer는 이번 slice에 포함되지 않았다. 따라서 Step 10~20 mobile 경계 시험과 전체 Step 10~60 완료 시험을 구분한다.
- terminal event를 받은 뒤 Control Tower의 다음 step을 자동으로 깨우는 영속 runtime loop는 아직 연결되지 않았다. 현재 SequenceOrchestrator 단위 경계는 검증됐지만, 실제 다음 step 진행은 후속 runtime worker가 필요하다.
- Pinky TaskEvent는 SQLite outbox에 저장되고 event 종류와 일치하는 terminal RobotStatus ACK 뒤 같은 event ID로 재전송되며 event ACK 뒤 삭제된다. 같은 process의 짧은 ACK 유실은 bounded 재전송하고 outbox 한도에 도달하면 TCP와 RMF 양쪽 새 운송 명령을 차단한다. process 재시작 전에 남은 과거 terminal snapshot은 최신 device 상태로 위장해 재생하지 않고 운영 reconciliation까지 보류한다. FMS RMF dispatch의 lease/reclaim도 아직 없으므로 RMF worker 프로세스 중단 시험에는 사용하면 안 된다.
- map revision은 launch 필수 인자로 바뀌었지만, FMS가 publish manifest를 소유하며 hash를 검증하는 API는 후속 구현이다.
- DB migration은 파일만 준비했으며 이 환경의 실제 MySQL에는 적용하지 않았다.

## 2. 주요 구현 코드

| 경계 | 코드 |
| --- | --- |
| 공용 실행 식별자 | \`trihouse_interfaces/msg/TaskContext.msg\` |
| RMF→Pinky action | \`trihouse_interfaces/action/ExecuteTransport.action\` |
| 출고 Step 10~60 | \`control_tower/task_manager/outbound_sequence.py\` |
| 순차 실행 정책 | \`control_tower/task_manager/sequence_orchestrator.py\` |
| Control Tower→FMS API | \`control_tower/gateway/fms_client.py\` |
| FMS→RMF worker | \`control_tower/rmf_adapter/rmf_gateway_worker_node.py\` |
| FMS HTTP/TCP runtime | \`fms_gateway/app/main.py\`, \`fms_gateway/app/tcp_protocol.py\` |
| FMS MySQL projection | \`fms_gateway/app/repositories.py\` |
| EasyFullControl adapter | \`trihouse_rmf_bridge/trihouse_rmf_bridge/pinky_adapter_node.py\` |
| control_system 시험 clone 도구 | \`trihouse_rmf_bridge/trihouse_rmf_bridge/control_system_overlay.py\` |
| 전체 launch | \`trihouse_rmf_bridge/launch/control_system_rmf.launch.py\` |
| Pinky 상태/TCP | \`trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/status_node.py\`, \`gateway_node.py\` |
| 배터리 정책 | \`trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/battery_policy.py\` |
| DB registry | \`db/seeds/seed_dev.sql\`, \`db/archive/pre_physical_v1/005_normalize_device_registry.sql\` |

출고 sequence는 다음처럼 고정된다.

~~~text
전체 출고 Job
├─ Step 10: 현재 위치 → 입고 대기점
├─ Step 20: 입고 대기점 → OMX_01 설비점
├─ Step 30: OMX_01 적재
├─ Step 40: 설비점 → 협로 대기점
├─ Step 50: 협로 대기점 → 출고 대기점
└─ Step 60: 출고 인계
~~~

각 step의 \`input\`에는 \`source_location_id\`, \`target_location_id\`,
\`sequence_id\`, \`segment_no\`, \`fleet_name\`이 저장된다. RMF worker는 DB의
\`locations.rmf_waypoint_name\`을 사용하며 location code를 waypoint로 임의 해석하지 않는다.

## 3. 이 개발 환경에서 확인한 명령과 결과

다음은 2026-08-12에 실제 실행해 종료 코드 0을 확인한 명령이다.

~~~bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash

colcon build \
  --base-paths trihouse_interfaces trihouse_pinky trihouse_rmf_bridge \
  --packages-select \
    trihouse_interfaces \
    trihouse_pinky_bringup \
    trihouse_pinky_fleet \
    trihouse_pinky_io \
    trihouse_pinky_safety \
    trihouse_pinky_vision \
    trihouse_rmf_bridge
~~~

확인 결과:

~~~text
Summary: 7 packages finished
~~~

개별 자동 시험 결과:

~~~text
trihouse_interfaces/test                         32 passed
trihouse_pinky/test                              76 passed
trihouse_rmf_bridge/test                         31 passed
control_tower/tests                             223 passed
fms_gateway 선택 unit suite                      43 passed
db/tests                                          10 passed
~~~

ROS launch 테스트는 홈의 \`~/.ros/log\` 대신 쓰기 가능한 경로를 지정한다.

~~~bash
ROS_LOG_DIR=/tmp/trihouse_ros_logs/pinky \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -q trihouse_pinky/test

ROS_LOG_DIR=/tmp/trihouse_ros_logs/bridge \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -q trihouse_rmf_bridge/test \
  --ignore=trihouse_rmf_bridge/test/test_office_service.py

ROS_LOG_DIR=/tmp/trihouse_ros_logs/control_tower \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3 -m pytest -q control_tower/tests
~~~

## 4. 사용자가 수동으로 실행할 순서

### 4.1 control_system 원본 확인과 main 갱신

\`control_system\`에 수정 내용이 있으면 pull하지 말고 먼저 보관 여부를 판단한다.

~~~bash
git -C /home/syw/Trihouse/control_system status --short
git -C /home/syw/Trihouse/control_system branch --show-current
git -C /home/syw/Trihouse/control_system fetch origin
git -C /home/syw/Trihouse/control_system switch main
git -C /home/syw/Trihouse/control_system pull --ff-only
~~~

원본은 upstream 보관본이며 통합 patch를 직접 적용하지 않는다.

### 4.2 ROS/RMF/Trihouse 빌드

~~~bash
source /opt/ros/jazzy/setup.bash
source /home/syw/rmf_ws/install/setup.bash
cd /home/syw/Trihouse

colcon build \
  --base-paths trihouse_interfaces trihouse_pinky trihouse_rmf_bridge \
  --packages-select \
    trihouse_interfaces \
    trihouse_pinky_bringup \
    trihouse_pinky_fleet \
    trihouse_pinky_io \
    trihouse_pinky_safety \
    trihouse_pinky_vision \
    trihouse_rmf_bridge

source /home/syw/Trihouse/install/setup.bash
~~~

### 4.3 control_system_test 독립 Git clone 생성

destination이 이미 있으면 도구가 덮어쓰지 않고 실패한다. 기존 후보를 지우거나 move하는
명령은 이 문서에서 제공하지 않는다. 이 도구는 원본의 파일을 단순 복사하지 않고
\`git clone --local --no-hardlinks\`로 별도 저장소를 만든 뒤
\`trihouse-integration\` 브랜치를 생성한다. 따라서 시험 변경은 원본 \`main\`에 섞이지 않는다.

~~~bash
ros2 run trihouse_rmf_bridge prepare_control_system_overlay \
  --source /home/syw/Trihouse/control_system \
  --destination /home/syw/Trihouse/control_system_test \
  --project project1
~~~

clone 결과를 확인한다. 상위 Trihouse 저장소는 \`control_system_test\` 전체를 무시하고,
시험본 자체 Git만 그 안의 소스 변경을 관리한다.

~~~bash
test -d /home/syw/Trihouse/control_system_test/.git
test "$(git -C /home/syw/Trihouse/control_system_test branch --show-current)" = \
  trihouse-integration
test "$(git -C /home/syw/Trihouse/control_system rev-parse HEAD)" = \
  "$(git -C /home/syw/Trihouse/control_system_test rev-parse origin/main)"
git -C /home/syw/Trihouse check-ignore -q control_system_test
! rg -n 'nav2_adapter.py' \
  /home/syw/Trihouse/control_system_test/rmf_maps/project1/project1_nav2.launch.xml
rg -n 'cmd_vel_nav' \
  /home/syw/Trihouse/control_system_test/rmf_maps/project1/robots/PK_01/nav2.launch.xml
git -C /home/syw/Trihouse/control_system_test status --short
~~~

마지막 출력은 빈 값이어야 한다. 시험본에는 upstream이 추적하던 \`.backups\`,
\`.dart_tool\`, build/install/log, Python cache, PID와 생성된 visualization을 제거한
cleanup commit이 들어가며, 같은 파일이 다시 Git 변경으로 잡히지 않도록 시험본
\`.gitignore\`에 기록한다.

이후 원본 main을 다시 갱신해 시험본에 반영할 때는 다음 순서를 사용한다.

~~~bash
git -C /home/syw/Trihouse/control_system switch main
git -C /home/syw/Trihouse/control_system pull --ff-only origin main

git -C /home/syw/Trihouse/control_system_test fetch origin main
git -C /home/syw/Trihouse/control_system_test switch trihouse-integration
git -C /home/syw/Trihouse/control_system_test rebase origin/main
~~~

rebase 충돌이 나면 자동으로 덮어쓰지 말고 중단한 뒤 upstream 변경과 Trihouse patch를
파일별로 검토한다.

### 4.4 control_system UI에서 project1 export

#### 4.4.1 이미 UI가 떠 있을 때 판단

UI 창이 떠 있다는 사실만으로 출력 대상이 맞는 것은 아니다. 앱을 시작할 때
`RMF_ROOT=/home/syw/Trihouse/control_system_test`를 지정했다면 그 창을 그대로
사용한다. 원본 `/home/syw/Trihouse/control_system`에서 시작했거나 `RMF_ROOT`를
지정했는지 확실하지 않다면 아직 `배포하기` 또는 `RMF 설정 내보내기`를 누르지
않고 창을 종료한 뒤 아래 명령으로 다시 시작한다.

원본은 다음 명령의 출력이 비어 있어야 한다.

~~~bash
git -C /home/syw/Trihouse/control_system status --short
~~~

#### 4.4.2 Flutter와 시험용 사본 확인

관제 UI는 Linux용 Flutter desktop 앱이다. Android SDK 오류는 이 UI 실행과
무관하지만 `Linux toolchain`과 `Linux (desktop)` device는 정상이어야 한다.

~~~bash
flutter --version
flutter doctor -v
flutter devices

test -d /home/syw/Trihouse/control_system_test/rmf_control_ui \
  && echo 'CONTROL_SYSTEM_TEST_OK'
~~~

`control_system_test`가 없을 때만 4.3의 `prepare_control_system_overlay`를 실행한다.
이미 존재하는 디렉터리에 다시 실행하면 덮어쓰지 않고 실패하는 것이 정상이다.

Flutter가 설치되지 않은 Ubuntu에서는 한 번만 다음을 수행한다.

~~~bash
sudo snap install flutter --classic
sudo apt-get update
sudo apt-get install -y \
  clang cmake ninja-build pkg-config libgtk-3-dev libstdc++-12-dev
~~~

#### 4.4.3 관제 시스템 UI 실행

새 터미널에서 아래 명령을 순서대로 실행한다. `RMF_ROOT`는 UI가 프로젝트를 읽고
배포 산출물을 쓸 루트이며 반드시 시험용 사본을 가리켜야 한다. 프로젝트 목록은
FMS Gateway에서 읽으므로 4.5의 DB와 Gateway를 먼저 기동한다.

~~~bash
export RMF_ROOT=/home/syw/Trihouse/control_system_test
export RMF_WS=/home/syw/rmf_ws
export FMS_GATEWAY_URL=http://127.0.0.1:8080

source /opt/ros/jazzy/setup.bash
source /home/syw/rmf_ws/install/setup.bash

cd /home/syw/Trihouse/control_system_test/rmf_control_ui
echo "RMF_ROOT=$RMF_ROOT"
curl -fsS "$FMS_GATEWAY_URL/ready"
flutter pub get
flutter run -d linux
~~~

기대되는 경로 출력은 다음과 같다.

~~~text
RMF_ROOT=/home/syw/Trihouse/control_system_test
~~~

`flutter pub get`과 첫 `flutter run`은 SDK·패키지·Linux 실행 파일을 준비하므로
몇 분 동안 터미널 진행률만 보일 수 있다. `Launching lib/main.dart on Linux`와
build 완료 메시지 뒤 관제 UI 창이 열린다. UI가 실행 중인 터미널은 앱 로그를
표시하므로 다른 명령은 새 터미널에서 실행한다.

#### 4.4.4 project1 열기와 배포

처음 canonical DB를 만든 직후 UI 목록에 project1이 없으면 4.5.1의 dry-run과
`--apply`를 먼저 실행한 뒤 이 절로 돌아온다.

UI에서 다음 순서로 진행한다.

~~~text
프로젝트 열기
  → project1 선택
  → Waypoint·Lane·축척·도면 확인
  → 오류 검증
  → 배포하기
~~~

`배포하기`는 `project1.building.yaml`에서 `nav_graphs/0.yaml`과 Gazebo 산출물을
생성하고 `RMF_ROOT/rmf_maps/project1`에 설치한다. backup 파일명을 바꾸거나 빈
YAML을 수동 생성해서 Gate를 우회하지 않는다.

이번 작업이 nav graph 재생성뿐이라면 `RMF 설정 내보내기`는 누르지 않아도 된다.
로봇 등록이나 RMF 설정을 바꿔 `RMF 설정 내보내기`까지 실행하면 UI 생성기가
launch 파일을 다시 쓸 수 있으므로 4.3에서 적용한 단일 adapter와 Safety 경로를
다시 검사한다.

#### 4.4.5 배포 결과 확인

UI를 실행한 터미널은 그대로 두고 새 터미널에서 확인한다.

~~~bash
test -s \
  /home/syw/Trihouse/control_system_test/rmf_maps/project1/nav_graphs/0.yaml \
  && echo 'NAV_GRAPH_OK'

! rg -n 'nav2_adapter.py' \
  /home/syw/Trihouse/control_system_test/rmf_maps/project1/project1_nav2.launch.xml

rg -n 'cmd_vel_nav' \
  /home/syw/Trihouse/control_system_test/rmf_maps/project1/robots/PK_01/nav2.launch.xml

git -C /home/syw/Trihouse/control_system status --short
~~~

성공 기준은 `NAV_GRAPH_OK`가 출력되고, native `nav2_adapter.py` 검색 결과가 없으며,
PK_01 Nav2 launch에서 `cmd_vel_nav`이 검색되고, 마지막 원본 status 출력은 비어
있는 것이다.

UI 종료는 UI 창을 닫거나 실행 터미널에서 `Ctrl+C`를 한 번 누른다. UI의
`백엔드 실행`까지 사용했다면 UI의 중지 기능으로 project1 backend를 먼저 내린
뒤 종료한다.

자주 발생하는 오류는 다음처럼 구분한다.

| 증상 | 원인과 조치 |
| --- | --- |
| `No such file or directory: control_system_test/rmf_control_ui` | 4.3 복사본 생성이 끝나지 않았다. `control_system_test` 존재 여부를 확인한다. |
| `flutter: command not found` | Flutter SDK 미설치 또는 새 Snap PATH 미반영이다. 설치 후 새 터미널에서 `flutter --version`을 확인한다. |
| Android SDK만 `flutter doctor`에서 실패 | Linux desktop UI에는 영향이 없다. Linux toolchain이 통과했는지 본다. |
| `Linux` device가 없음 | `clang`, `cmake`, `ninja-build`, `pkg-config`, `libgtk-3-dev`, `libstdc++-12-dev`를 설치하고 다시 확인한다. |
| 배포 후 `NAV_GRAPH_OK`가 나오지 않음 | UI 오류 검증/배포 로그를 확인하고 `rmf_building_map_tools`가 RMF workspace에서 보이는지 확인한다. |
| UI에서 만든 파일이 원본에 생김 | 잘못된 `RMF_ROOT`로 실행한 것이다. 추가 배포를 중단하고 원본 변경 내용을 먼저 확인한다. |

map revision은 publish artifact 내용으로 계산한다. 아래 값은 launch에 전달할 시험용 content
hash이며 운영 manifest API가 생기면 그 revision을 사용한다.

~~~bash
sha256sum \
  /home/syw/Trihouse/control_system_test/rmf_maps/project1/project1.building.yaml \
  /home/syw/Trihouse/control_system_test/rmf_maps/project1/nav_graphs/0.yaml \
  /home/syw/Trihouse/control_system_test/rmf_maps/project1/project1.world
~~~

세 hash를 release 기록에 보존하고, 이번 시험의 \`map_revision\` 문자열을 하나로 고정한다.

### 4.5 MySQL과 FMS Gateway

먼저 repository 루트의 \`.env\`에 최소 다음 값이 있어야 한다.

~~~text
MYSQL_ROOT_PASSWORD=...
FMS_DB_PASSWORD=...
~~~

신규 빈 volume:

~~~bash
cd /home/syw/Trihouse
docker compose -f compose.db.yaml up -d
docker compose -f compose.control.yaml up --build -d
curl -fsS http://127.0.0.1:8080/ready
nc -zv 127.0.0.1 8788
~~~

기존 DB volume은 seed가 다시 실행되지 않으므로 data-only migration을 수동 적용한다.

~~~bash
cd /home/syw/Trihouse
docker compose -f compose.db.yaml exec -T mysql \
  mysql -uroot -p"$MYSQL_ROOT_PASSWORD" trihouse_fms \
  < db/archive/pre_physical_v1/005_normalize_device_registry.sql

docker compose -f compose.db.yaml exec -T mysql \
  mysql -uroot -p"$MYSQL_ROOT_PASSWORD" trihouse_fms \
  < db/archive/pre_physical_v1/006_add_map_authoring_and_publication.sql
~~~

`control_system_test/db`의 SQL은 upstream UI 참고 자료일 뿐 실행하지 않는다. 신규
volume의 전체 기준은 `db/migrations/001_physical_v1_baseline.sql`, 기존 volume의 증분 기준은 `db/migrations`
뿐이다.

#### 4.5.1 기존 project1을 canonical DB에 가져오기

먼저 DB를 변경하지 않는 dry-run으로 pixel→RMF meter 변환과 고정 location mapping을
확인한다.

~~~bash
cd /home/syw/Trihouse
python3 db/tools/import_control_system_project.py \
  control_system_test/rmf_maps/project1/project1.building.yaml \
  --fleet-yaml control_system_test/rmf_maps/project1/fleet.yaml
~~~

`waypoint_count=13`, `lane_count=11`, `robot_count=4`와 CHG/WAIT/OMX mapping이
출력되면 draft를 저장한다.

~~~bash
python3 db/tools/import_control_system_project.py \
  control_system_test/rmf_maps/project1/project1.building.yaml \
  --fleet-yaml control_system_test/rmf_maps/project1/fleet.yaml \
  --fms-url http://127.0.0.1:8080 \
  --apply

curl -fsS http://127.0.0.1:8080/internal/v1/map-projects/project1 \
  | python3 -m json.tool
~~~

UI에서 배포해 `nav_graphs/0.yaml`이 생긴 뒤에만 immutable revision을 publish한다.
`--publish`는 기존 draft를 다시 PUT하지 않으므로 UI가 저장한 file/fleet/robot
설정을 지우지 않는다.

~~~bash
python3 db/tools/import_control_system_project.py \
  control_system_test/rmf_maps/project1/project1.building.yaml \
  --fleet-yaml control_system_test/rmf_maps/project1/fleet.yaml \
  --fms-url http://127.0.0.1:8080 \
  --publish \
  --nav-graph control_system_test/rmf_maps/project1/nav_graphs/0.yaml \
  --world control_system_test/rmf_maps/project1/project1.world \
  --published-by W-OP-01

curl -fsS http://127.0.0.1:8080/internal/v1/maps/project1/published \
  | python3 -m json.tool
~~~

publish 응답의 `map_revision`을 이후 RMF launch와 Pinky에 똑같이 전달한다. UI에서
Waypoint를 움직이면 이전 meter pose는 무효화되므로 다시 export/import/publish한다.

적용 후 registry를 조회한다.

~~~bash
docker compose -f compose.db.yaml exec -T mysql \
  mysql -uroot -p"$MYSQL_ROOT_PASSWORD" trihouse_fms -e "
SELECT device_id, device_type, fleet_name, home_location_id, capabilities
FROM devices
WHERE device_id IN ('PK_01','PK_02','OMX_01','OMX_02')
ORDER BY device_id;

SELECT location_id, location_code, map_name, rmf_waypoint_name
FROM locations
WHERE location_code IN
  ('A-SLOT-01','OUT-DOCK-01','CHG-01','CHG-02',
   'IN-WAIT-01','NARROW-WAIT-01','OMX-WS-01','OMX-WS-02')
ORDER BY location_code;"
~~~

draft와 revision도 같은 DB에서 확인한다.

~~~bash
docker compose -f compose.db.yaml exec -T mysql \
  mysql -uroot -p"$MYSQL_ROOT_PASSWORD" trihouse_fms -e "
SELECT map_name, drawing_name, waypoint_count, lane_count, draft_revision, updated_at
FROM map_projects WHERE map_name = 'project1';

SELECT location_code, rmf_waypoint_name, x, y, map_x, map_y
FROM map_project_waypoints w
JOIN map_projects p ON p.project_id = w.project_id
WHERE p.map_name = 'project1' AND location_code IS NOT NULL
ORDER BY location_code;

SELECT map_revision, draft_revision, state, published_at
FROM map_revisions WHERE map_name = 'project1'
ORDER BY published_at DESC;"
~~~

기대 핵심 값:

~~~text
PK_01 / PK_02 fleet_name = project1_pinky
PK_01 rmf_robot_name = PK_01
PK_02 rmf_robot_name = PK_02
IN-WAIT-01       -> project1 / 대기1
NARROW-WAIT-01   -> project1 / 대기3
OMX-WS-01        -> project1 / 설비1
OUT-DOCK-01      -> project1 / 드랍오프1
~~~

### 4.6 launch 인자 사전 확인

~~~bash
source /opt/ros/jazzy/setup.bash
source /home/syw/rmf_ws/install/setup.bash
source /home/syw/Trihouse/install/setup.bash

ros2 launch trihouse_rmf_bridge control_system_rmf.launch.py --show-args
~~~

\`control_system_root\`, \`runtime_state_root\`, \`trihouse_root\`, \`rmf_ws_root\`,
\`fleet_config\`, \`map_revision\`은 명시한다. runtime SQLite는 불변
\`control_system_root\` 바깥에 둔다.

### 4.7 전체 simulation 실행

아래 \`project1:<CONTENT_HASH>\`는 4.4에서 정한 값으로 바꾼다.

~~~bash
source /opt/ros/jazzy/setup.bash
source /home/syw/rmf_ws/install/setup.bash
source /home/syw/Trihouse/install/setup.bash

ros2 launch trihouse_rmf_bridge control_system_rmf.launch.py \
  control_system_root:=/home/syw/Trihouse/control_system_test \
  runtime_state_root:=/home/syw/Trihouse/var/pinky_runtime \
  trihouse_root:=/home/syw/Trihouse \
  rmf_ws_root:=/home/syw/rmf_ws \
  project_name:=project1 \
  fleet_config:=/home/syw/Trihouse/trihouse_rmf_bridge/config/pinky_fleet.yaml \
  fleet_name:=project1_pinky \
  robot_id:=PK_01 \
  robot_namespace:=pinky_01 \
  rmf_map_name:=L1 \
  charger_waypoint:=충전1 \
  map_revision:=project1:<CONTENT_HASH> \
  fms_base_url:=http://127.0.0.1:8080 \
  control_host:=127.0.0.1 \
  control_port:=8788 \
  battery_percentage:=0.80 \
  discharge_percent_per_second:=0.0 \
  start_control_system_core:=true \
  start_gazebo:=true \
  start_nav2:=true \
  start_pinky_runtime:=true \
  start_trihouse_adapter:=true \
  start_rmf_worker:=true
~~~

이 launch는 project1에 기존 \`project1_nav2_adapter.py\` 실행 줄이 남아 있으면 의도적으로
실패한다. Trihouse EasyFullControl adapter와 native adapter를 동시에 실행하지 않는다.

### 4.8 ROS 모듈 상태 확인

다른 terminal에서:

~~~bash
source /opt/ros/jazzy/setup.bash
source /home/syw/rmf_ws/install/setup.bash
source /home/syw/Trihouse/install/setup.bash

ros2 node list | sort
ros2 action list | rg 'transport|navigate_to_pose'
ros2 topic echo /pinky_01/trihouse/status --once
ros2 topic echo /pinky_01/trihouse/battery/policy_state --once
ros2 topic echo /fleet_states --once
~~~

\`/pinky_01/trihouse/status\`에서 확인할 필드:

~~~text
robot_id: PK_01
frame_id: map
map_revision: project1:<CONTENT_HASH>
telemetry_valid: true
execution_ready: true
dispatchable: true
task_context.active: false   # 작업 전
~~~

### 4.9 배터리 module 시험

통합 launch를 SOC별로 다시 실행해 정책 상태를 확인한다.

| \`battery_percentage\` | 기대 정책 | 신규 일반 작업 |
| ---: | --- | --- |
| \`0.25\` | NORMAL | 허용 |
| \`0.18\` | LOCAL_ONLY | 제한적으로 허용 |
| \`0.10\` | RETURN_REQUIRED | 차단/귀환 요구 |

각 실행에서:

~~~bash
ros2 topic echo /pinky_01/trihouse/battery/policy_state --once
ros2 topic echo /pinky_01/trihouse/status --once
~~~

\`RETURN_REQUIRED\`에서는 \`RobotStatus.dispatchable=false\`인지 확인한다.

### 4.10 DB 누적 확인

Job ID를 알고 있을 때:

~~~bash
curl -fsS http://127.0.0.1:8080/api/v1/jobs/<JOB_ID> \
  | python3 -m json.tool

curl -fsS http://127.0.0.1:8080/api/v1/jobs/<JOB_ID>/timeline \
  | python3 -m json.tool
~~~

MySQL:

~~~bash
docker compose -f /home/syw/Trihouse/compose.db.yaml exec -T mysql \
  mysql -uroot -p"$MYSQL_ROOT_PASSWORD" trihouse_fms -e "
SELECT job_id, job_code, state, assigned_mobile_id, created_at
FROM jobs ORDER BY job_id DESC LIMIT 5;

SELECT job_step_id, job_id, step_no, executor_type, assigned_device_id,
       action_type, state, retry_count, assignment_revision, rmf_task_id,
       final_outcome_reason_code, final_method_code
FROM job_steps
ORDER BY job_step_id DESC LIMIT 20;

SELECT attempt_uuid, job_step_id, assignment_revision, actor_role,
       actor_device_id, attempt_no, state, outcome, success,
       outcome_reason_code, failure_domain, method_code,
       started_at, completed_at
FROM job_step_attempts
ORDER BY created_at DESC LIMIT 20;

SELECT event_id, event_uuid, job_id, job_step_id, device_id,
       category, event_type, payload, occurred_at
FROM operation_events
ORDER BY event_id DESC LIMIT 50;

SELECT device_id, observed_at, state, health, current_job_step_id,
       battery_pct, progress, details
FROM device_states
WHERE device_id IN ('PK_01','PK_02');"
~~~

정상 mobile segment에서 최소 확인할 연결:

~~~text
job_steps.rmf_task_id
  = TaskContext.rmf_task_id
job_steps.job_step_id
  = TaskContext.job_step_id
job_steps.assignment_revision
  = TaskContext.assignment_revision
job_step_attempts.command_uuid
  = TaskContext.command_id
operation_events.payload.primary_reason
  = WAYPOINT_REACHED 또는 안정적인 실패 reason code
~~~

## 5. 오늘 시험 Gate

다음 순서로 한 Gate씩 통과한다.

- [ ] control_system 원본 main 갱신 전 dirty 여부 확인
- [ ] 새 \`control_system_test\` 독립 clone 및 \`trihouse-integration\` 상태 확인
- [ ] UI에서 project1 export 후 \`nav_graphs/0.yaml\` 존재
- [ ] DB migration 적용 및 PK/OMX/location registry SELECT 확인
- [ ] FMS \`/ready\`, TCP 8788 확인
- [ ] ROS 패키지 build
- [ ] launch \`--show-args\` 확인
- [ ] Gazebo·RMF core·Nav2·Pinky runtime 기동
- [ ] status의 map frame, revision, readiness 확인
- [ ] SOC 25%, 18%, 10% 배터리 module 결과 확인
- [ ] 단일 RMF booking에 authoritative assignment가 포함되는지 확인
- [ ] PK_01 한 mobile segment 실행
- [ ] Job/Step/Attempt/Event/DeviceState SELECT 결과가 같은 TaskContext인지 확인

다음 조건이면 전체 출고 성공으로 표시하지 않는다.

- \`RMF_ASSIGNMENT_PENDING\`
- Step 30 OMX consumer 미기동
- terminal event 뒤 다음 step 자동 dispatch runtime 미기동
- nav graph 또는 map revision 미확정
- DB migration 미적용

## 6. 검증 후 운영 후보 승격

모든 필수 Gate를 통과한 후보만 copy한다. move하지 않는다.

~~~bash
test ! -e /home/syw/Trihouse/control_system_root
cp -a \
  /home/syw/Trihouse/control_system_test \
  /home/syw/Trihouse/control_system_root
~~~

이후 동일 launch에서 경로만 바꾼다.

~~~text
control_system_root:=/home/syw/Trihouse/control_system_root
~~~

\`control_system\`은 계속 upstream 원본으로 보존한다.
