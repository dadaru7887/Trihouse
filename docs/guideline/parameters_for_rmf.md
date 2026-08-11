# Open-RMF 배터리·시간 파라미터 POC 가이드

## 적용 범위

이 문서는 냉동창고↔포장대 배차의 이동시간과 작업 종료 예상 SOC를 검증하기 위해 반드시 필요한 최소 항목만 다룬다. 현재 확인된 환경은 ROS 2 Jazzy, `rmf_demos 2.3.0`, `rmf_ros2 2.7.2`, `rmf_battery 0.3.1`, `rmf_task 2.5.1`, `rmf_traffic 3.3.3`이다.

Open-RMF는 등록된 graph와 차량·배터리 모델로 경로와 소비량을 계산하지만, 실제 Pinky의 특성값은 자동으로 알아내지 못한다. 따라서 아래 입력값은 직접 측정해서 fleet adapter 설정에 넣어야 한다.

## 직접 측정해야 하는 최소 파라미터

| 파라미터 | 단위 | POC에서 필요한 이유 | 측정 방법 |
|---|---:|---|---|
| waypoint `x`, `y`, 접근 `yaw` | m, rad | RMF 경로와 실제 적재·인계·충전 위치를 일치시킴 | SLAM map에서 후보 좌표를 정한 뒤 로봇을 5회 정차시켜 성공한 평균 좌표·방향을 기록 |
| 기준 좌표 대응점 | map 좌표↔RMF 좌표 | Nav2 map과 RMF graph 정렬 | 서로 멀리 떨어진 식별점 4개 이상을 두 좌표계에서 측정하고 변환 오차 확인 |
| 선속도·선가속도 제한 | m/s, m/s² | 경로 ETA 계산 | 무적재 직선 왕복 로그에서 안정적으로 재현되는 속도와 정지거리를 측정 |
| 각속도·각가속도 제한 | rad/s, rad/s² | 회전이 포함된 ETA 계산 | 제자리 90°·180° 회전을 각 5회 수행하고 소요시간과 overshoot를 측정 |
| footprint·vicinity 반경 | m | 충돌 회피 및 통로 통과 가능성 판단 | Pinky와 적재 바구니의 최대 외곽 치수를 실측하고 POC 안전 여유를 더함 |
| nominal voltage | V | RMF 배터리 모델 입력 | 배터리 사양값을 쓰고 완충·운행 중 전압 로그로 확인 |
| usable capacity | Ah | SOC 소비 예측의 기준 용량 | 사양값으로 시작하고 완충 후 동일 코스 반복 결과로 보정 |
| charging current | A | 충전 완료 예상시간 계산 | 충전 중 `BatteryState.current`를 기록하거나 충전기 사양값을 사용 |
| 무적재·최대 적재 질량 | kg | 이동 소비량 차이 반영 | 저울로 Pinky 기본 질량과 최대 POC 적재물을 각각 측정 |
| ambient power | W | 정지·대기 중 기본 소비 반영 | 모터 정지 상태로 20~30분 대기하며 SOC 감소량을 기록해 환산 |
| 적재·인계 시간 | s | 이동 외 로봇팔 작업시간 포함 | 각 단계를 10회 수행한 뒤 실패를 포함한 P90 시간을 사용 |
| 작업 고정 여유시간 | s | 통신·정렬 등 짧은 변동 흡수 | 초기 15초로 시작하고 실제 총시간 오차 로그로 조정 |

POC에서는 냉동 기능이 실제로 작동하지 않으므로 저온 보정과 별도 tool power는 0 또는 제외한다. 관성모멘트와 마찰계수는 RMF 배터리 모델에 필요할 때 제조사·형상 기반 초기값으로 시작하고 아래 왕복 실험으로 보정한다.

## 반드시 수행할 최소 배터리 소비 실험

| 실험 | 조건 | 기록할 값 | 적용 위치 |
|---|---|---|---|
| 유휴 소비 | 완충 후 모터 정지 20~30분 | 시작/종료 SOC, 시간 | ambient power 보정 |
| 냉동→포장 무적재 왕복 | 같은 경로·속도, 최소 5회 | 실제 시간, 시작/종료 SOC | RMF ETA·이동 sink 검증 |
| 냉동→포장 최대 적재 왕복 | POC 최대 바구니, 최소 5회 | 질량, 실제 시간, 시작/종료 SOC | 적재 질량에 따른 소비 보정 |
| 적재·인계 | 각 단계 10회 | 단계별 시간, 성공 여부 | P90 phase duration 설정 |
| 충전 | 10% 부근부터 30% 이상 | 시간별 SOC, charging 상태 | charging current와 재투입 시간 검증 |
| 예측 대 실제 비교 | 위 모든 작업 | 예측 종료 SOC, 실제 종료 SOC, 오차 | 안전 임계값·모델 보정 |

`consumption_percent_per_minute`는 Open-RMF 연결이 없을 때만 쓰는 POC fallback 값이다. 실제 RMF 연결 후에도 위 실험은 필요하다. RMF 계산값이 현실과 맞는지 확인하고 차량·배터리 모델 파라미터를 보정해야 하기 때문이다.

## Open-RMF에서 받는 값

| 값 | 의미 | POC 사용법 |
|---|---|---|
| `travel_duration_s` | graph 경로 주행 예상시간 | 적재·인계 시간을 제외한 이동 ETA로 기록 |
| `total_duration_s` | 이동+적재+인계+고정 여유 예상시간 | 작업 전체 예상시간 표시와 검증에 사용 |
| `change_in_charge` | 해당 작업의 예상 SOC 감소량(0.0~1.0) | 배터리 소비 모델 검증에 사용 |
| `finish_state_of_charge` | 작업 종료 예상 SOC(0.0~1.0) | `LOCAL_ONLY`의 최종 배차 판단에 사용 |
| route availability | 요청 waypoint 경로 생성 가능 여부 | 경로가 없으면 새 작업 배정 금지 |
| estimate source | `open_rmf` 또는 명시적 POC fallback | 운영 판단과 실험 데이터를 구분 |

현재 rmf-web `/fleets`에서 바로 볼 수 있는 배터리 값은 로봇의 **현재 SOC**다. 작업 종료 예상 SOC는 웹 API의 현재 상태 필드와 다르므로, fleet adapter가 RMF 경로·배터리 모델을 이용해 `EstimateTaskEnergy` service에 응답하도록 연결해야 한다. Control Tower의 `RmfEnergyEstimator`는 이 service를 호출하는 port와 검증·retry를 구현했으며, 실제 service server는 RMF nav graph와 fleet adapter를 연결할 때 구현한다.

전체 시간 계약은 다음과 같다.

```text
total_duration_s
= travel_duration_s
 + expected_loading_duration_s
 + expected_handover_duration_s
 + task_time_buffer_s
```

## POC 배차 규칙

| 현재 정책 | RMF 예상 종료 SOC | 결정 |
|---|---:|---|
| `LOCAL_ONLY` | 10% 초과 | 냉동↔포장 작업 허용(`ALLOW_LOCAL_JOB`) |
| `LOCAL_ONLY` | 5% 초과 10% 이하 | 이 작업까지만 완료 후 충전 복귀(`COMPLETE_THEN_RETURN`) |
| `LOCAL_ONLY` | 5% 이하 | 새 작업 금지, 즉시 충전 복귀(`RETURN_TO_CHARGE`) |
| `LOCAL_ONLY` | 값 없음/timeout/경로 없음 | 새 작업 금지, 가까운 냉동·포장 안전점 대기(`WAIT_AT_SAFE_NODE`) |

## rmf-web에서 확인 가능한 상태

| API·항목 | 의미 |
|---|---|
| `/fleets`의 fleet/name | fleet와 로봇 식별자 |
| status | 로봇 운행 상태 문자열 |
| battery | 현재 SOC; 예상 종료 SOC가 아님 |
| task_id | 현재 할당된 RMF task |
| location의 map/x/y/yaw | 현재 level과 자세 |
| issues | 로봇·task에서 보고한 문제 |
| mutex groups | 현재 점유한 상호배제 자원 |
| `/tasks`의 category/status/assigned_to | 작업 종류·진행상태·할당 로봇 |

## 자동 측정 로그

기본 저장 위치는 `~/.ros/trihouse/measurements/<run_id>/`다. 실험 전에 두 프로세스에 같은 `TRIHOUSE_MEASUREMENT_RUN_ID`를 설정한다.

| 파일 | 자동 기록 내용 |
|---|---|
| `run_metadata.json` | schema, run ID, 생성시각, 기록 component |
| `battery_telemetry_<robot_id>.jsonl` | 실제 SOC, 유효성·freshness, 충전 상태, job/step, 정책 state |
| `rmf_energy_estimates.jsonl` | 요청 경로, phase 시간, RMF ETA, 예상 감소량·종료 SOC, source·오류 |
| `battery_policy_decisions.jsonl` | 배차에 사용한 state/action/reason, 실제·예상 SOC, 선택 여부 |

```bash
export TRIHOUSE_MEASUREMENT_RUN_ID=poc_20260811_01
export TRIHOUSE_MEASUREMENT_LOG_ROOT=$HOME/.ros/trihouse/measurements

find "$TRIHOUSE_MEASUREMENT_LOG_ROOT/$TRIHOUSE_MEASUREMENT_RUN_ID" -maxdepth 1 -type f -print
tail -f "$TRIHOUSE_MEASUREMENT_LOG_ROOT/$TRIHOUSE_MEASUREMENT_RUN_ID"/battery_telemetry_PK-01.jsonl
jq . "$TRIHOUSE_MEASUREMENT_LOG_ROOT/$TRIHOUSE_MEASUREMENT_RUN_ID"/rmf_energy_estimates.jsonl
```

로그 저장 실패는 배터리 정책이나 주행 결정을 바꾸지 않는다. 파일이 없으면 노드 경고와 디렉터리 권한·환경변수를 확인한다.

## 설치·연결 확인 명령

```bash
source /opt/ros/jazzy/setup.bash
source /home/syw/rmf_ws/install/setup.bash
source /home/syw/Trihouse/install/setup.bash

ros2 pkg prefix rmf_demos_gz
ros2 pkg prefix rmf_demos_fleet_adapter
python3 -c "import rmf_adapter, rmf_adapter.battery; print('RMF Python OK')"

ros2 topic echo /trihouse/battery
ros2 topic echo /trihouse/battery/policy_state
ros2 interface show trihouse_interfaces/srv/EstimateTaskEnergy
ros2 service list | grep estimate_task_energy
```

마지막 service가 아직 표시되지 않으면 fleet adapter 쪽 `EstimateTaskEnergy` server 연결이 남은 상태다. `pinky_pro`는 배터리 원본과 하드웨어 안전만 담당하고, Control Tower가 RMF 예측과 배차 정책을 결합한다.
