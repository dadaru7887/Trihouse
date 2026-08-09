# 로컬 시뮬레이션 시연

## 시연 범위

```text
내일 시연
├─ 기존 control_system UI       # 기존 관제 화면과 자체 시뮬레이션
├─ Pinky SR 정적 테스트         # trihouse_pinky 정책 구현 증거
├─ Pinky Gazebo 검증            # 전제조건을 통과한 항목만
└─ DB 스키마                    # FMS 16개 + recovery 2개 테이블
```

네 항목은 아직 하나의 end-to-end 통합 증거가 아니다. 발표 화면에도 각각
`existing_ui`, `static`, `simulation`, `schema`로 표시한다.

## 1. 기존 Control System 화면

`control_system/openrmf/scripts/run_office_web.sh`는 rmf-web API와 dashboard를
Docker로 실행하고, 호스트 ROS 2/Open-RMF에서 `office_web.launch.xml`을 실행한다.
현재 launch는 stock `office` demo이며 `robosapiens.world`를 사용하지 않는다.

```bash
cd /home/syw/Trihouse/control_system
RMF_OPEN_BROWSER=true ./openrmf/scripts/run_office_web.sh
```

이 명령은 `/opt/ros/jazzy/setup.bash`, `$HOME/rmf_ws/install/setup.bash`, Docker 접근을
요구한다. 원본 스크립트와 launch 파일은 수정하지 않는다.

`compose.simulation.yaml`은 같은 RMF API와 dashboard만 관리하는 대안이다. 기존
스크립트와 동시에 실행하지 않는다. 현재 시연은 스크립트가 ROS 2/Gazebo의 시작과
종료까지 한 번에 관리하므로 위 명령을 우선 사용한다.

## 2. Pinky SR 정적 증거

```bash
cd /home/syw/Trihouse
python3 -m pytest -q \
  trihouse_pinky/test/test_pinky_sr_policies.py \
  trihouse_pinky/test/test_eta_policy.py \
  trihouse_pinky/test/test_integrated_bringup_contract.py
```

성공한 테스트 이름과 commit SHA를 `validation/runs/`에 기록한다. 정적 테스트 성공을
Gazebo 또는 실기 검증으로 표현하지 않는다.

## 3. Pinky Gazebo

Pinky 시뮬레이션은 `trihouse_pinky_bringup/launch/trihouse_gazebo_demo.launch.py`를
사용하며 vendor `pinky_gz_sim`과 `pinky_pro/pinky_navigation/map/my_map.yaml`에
의존한다. stock office/robosapiens RMF와 자동 통합되는 launch는 아직 없다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/syw/Trihouse/install/setup.bash
ros2 launch trihouse_pinky_bringup trihouse_gazebo_demo.launch.py
```

필수 package나 display가 없으면 결과를 `blocked`로 기록하고 정적 증거로 대체한다.

## 4. DB 스키마

[DB 시연 가이드](database_demo.md)에 따라 두 database와 18개 table, recovery 관계를
보여준다. `schema_mysql_bf.sql`은 v3 백업, `schema_mysql.sql`은 v4 신규 설치 기준이다.
