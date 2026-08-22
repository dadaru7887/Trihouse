# VLM+RL 승인 복구 실물 검증

이 절차는 4060이 영상 저장·관제·Gateway·DB를 담당하고, 5080이 추론만 수행하며,
Pinky가 승인된 복구를 Nav2와 Safety Supervisor를 통해 실행하는 구성을 검증한다.
실물 운용 중 학습은 실행하지 않는다.

## 1. 공통 불변 조건

- 모든 ROS 호스트: `ROS_DOMAIN_ID=12`
- 명령 라우팅 ID: DB `device_id`인 `PK_01` 또는 `PK_02`
- ROS namespace: `pinky_01` 또는 `pinky_02`; 빈 값을 명시하면 root namespace
- 5080에는 MySQL 계정과 DB 포트를 제공하지 않는다.
- `cmd_vel`의 최종 발행자는 Pinky의 Safety Supervisor 하나여야 한다.
- 첫 실물 recovery는 이동이 없는 `WAIT_REOBSERVE`만 사용한다.

## 2. 4060 준비

```bash
cd /home/newuser/Trihouse
cp .env.example .env
docker compose -f compose.edge_4060.yaml config --quiet
docker compose -f compose.edge_4060.yaml up -d
docker compose -f compose.edge_4060.yaml ps
curl -fsS http://127.0.0.1:8080/health
```

5080이 접근할 Gateway 주소는 DHCP 예약된 4060 LAN 주소인
`http://192.168.0.9:8080`이다. 영상은 4060 MediaMTX의 RTSP URL로만 제공한다.

## 3. Pinky 준비

Pinky별로 `robot_id`와 namespace만 바꾼다. `map_revision`은 DB의 활성 revision과
정확히 같아야 한다.

```bash
export ROS_DOMAIN_ID=12
source /opt/ros/jazzy/setup.bash
source /home/pinky/Trihouse/install/setup.bash
ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK_01 namespace:=pinky_01 \
  control_host:=192.168.0.9 control_port:=8788 \
  map:=/home/pinky/pinky_pro/src/pinky_navigation/map/new_map_2.yaml \
  map_revision:=new_map_2-r1
```

namespace를 쓰지 않는 단일 로봇 검증은 `namespace:=`를 명시한다. 인자를 아예
생략하면 안전한 기본값 `pinky_01`이 적용된다.

다른 터미널에서 다음을 확인한다.

```bash
export ROS_DOMAIN_ID=12
ros2 node list | sort
ros2 action list | grep trihouse/recovery/execute
ros2 topic info /pinky_01/cmd_vel --verbose
ros2 topic echo --once /pinky_01/trihouse/safety/state
ros2 topic echo --once /pinky_01/trihouse/health
```

`cmd_vel` publisher가 둘 이상이거나 Safety/health 메시지가 없으면 진행하지 않는다.

## 4. 5080 준비

```bash
cd /home/newuser/Trihouse
sha256sum runtime/ai/models/<approved-policy-checkpoint.pt>
docker compose -f compose.ai_5080.yaml config --quiet
docker compose -f compose.ai_5080.yaml up -d ai_runtime
docker compose -f compose.ai_5080.yaml logs -f ai_runtime
```

`.env`의 필수 값은 `FMS_GATEWAY_URL=http://192.168.0.9:8080`,
`RECOVERY_DEVICE_ID=PK_01`, `VISION_RTSP_URL`, segmentation weights 파일명,
policy checkpoint 파일명과 실제 SHA-256이다. 실물 Compose는
`VLM_RL_RUNTIME_MODE=physical`, `VLM_RL_SAFETY_GATE_ENABLED=true`,
`VLM_RL_EXECUTION_MODE=operator_approved`를 강제한다.

5080에서 GPU를 실제 검증한다.

```bash
docker compose -f compose.ai_5080.yaml exec ai_runtime python -c \
  "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0))"
```

## 5. 승인 WAIT 종단 검증

E-stop 담당자가 Pinky 옆에 있고 바퀴가 들리지 않은 정상 바닥 상태에서 수행한다.
5080이 생성한 `WAIT_REOBSERVE` proposal ID를 사용한다.

```bash
export FMS_GATEWAY_URL=http://192.168.0.9:8080
export RECOVERY_WAIT_PROPOSAL_ID=<proposal-uuid>
export SAFETY_MANAGER_ID=W-CONTROL-01
export TRIHOUSE_RUN_RECOVERY_WAIT=1
pytest -q tests/hardware/test_approved_recovery_wait.py -m hardware
```

PASS는 운영자 승인, device TCP downlink, Pinky `ExecuteRecovery`, Nav2 Wait,
실행 결과의 Gateway 복귀까지 성공했다는 뜻이다. 바퀴가 움직이면 즉시 E-stop하고
FAIL로 기록한다.

## 6. 학습 데이터 확인

```bash
curl -fsS http://127.0.0.1:8080/internal/v1/recovery/training-export.jsonl \
  | python -m json.tool --json-lines
```

한 실제 실행은 `state[9], skill, coord[3], reward, next_state[9], done, meta` 한 행으로
나와야 한다. `meta.is_execution=true`가 아니거나 clearance가 관측되지 않은 실행은
학습 행으로 저장하지 않는다.

## 7. 현재 물리 검증이 필요한 항목

- 5080에서 실제 7B VLM 4-bit load와 단일 프레임 latency/VRAM
- Pinky에서 WAIT 후 0.05 m 이하 BACKUP, 좌·우 detour, REJOIN 순차 검증
- costmap·footprint·Nav2 plan을 이용한 원본 6C-Lite 사전 후보 필터의 실 ROS 연결
- Safety Supervisor veto 시 모터 정지와 `safety_intervened=true` 결과 확인

이 항목들은 4060의 빌드 성공만으로 통과 처리하지 않는다.
