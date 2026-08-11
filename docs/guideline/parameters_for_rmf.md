# 실제 Pinky Open-RMF 파라미터 측정·보정 가이드

## 1. 목적과 적용 범위

이 문서는 `trihouse_rmf_bridge`의 office demo 설정을 실제 Pinky 설정으로 바꾸기 전에 반드시 측정하고 검증해야 할 최소 파라미터를 관리한다. 대상 기능은 냉동창고↔포장대 작업의 이동시간과 작업 종료 예상 SOC 계산이다.

현재 확인된 개발 환경은 ROS 2 Jazzy, `rmf_demos 2.3.0`, `rmf_ros2 2.7.2`, `rmf_battery 0.3.1`, `rmf_task 2.5.1`, `rmf_traffic 3.3.3`이다.

> `trihouse_rmf_bridge/config/office_bridge.yaml`의 숫자는 office demo용 **초기 참고값**이다. 실제 Pinky 설정 반영 금지 상태이며, 이 문서의 측정·검증 절차를 통과하기 전에는 복사하지 않는다.

## 2. 값 상태와 적용 규칙

| 상태 | 의미 | 허용 범위 |
|---|---|---|
| `미측정` | 실제 Pinky에서 측정하지 않았거나 원본 증거가 없음 | 실제 설정 반영 금지 |
| `초기 참고값` | office demo 또는 제조사 자료의 비교용 숫자 | 측정 계획 수립에만 사용 |
| `측정 완료` | 측정일·조건·반복 횟수·원본 로그가 있는 값 | 제한된 시험 설정에만 사용 |
| `검증 완료` | 반복 시험 결과와 POC 적용 승인이 있는 값 | POC 운영 설정에 사용 가능 |

`미측정`은 빈칸이 아니라 작업 차단 상태다. 값을 입력할 때는 숫자만 바꾸지 말고 상태, 측정일, 원본 로그, 적용 승인도 함께 갱신한다.

## 3. office 참고값과 실제 Pinky 측정표

아래 office 값은 연결 구조를 시험하기 위한 값이다. 실제 Pinky 값은 모두 `미측정`에서 시작한다.

| bridge 필드 | 단위 | office 초기 참고값 | 실제 Pinky 값 | 상태 | 최소 측정 방법 | 원본 증거 | 적용 위치 |
|---|---:|---:|---|---|---|---|---|
| `linear_velocity` | m/s | 0.5 | 미측정 | 미측정 | 직선 왕복 5회에서 안정적으로 유지된 최고 속도 | 미생성 | Pinky bridge config |
| `linear_acceleration` | m/s² | 0.75 | 미측정 | 미측정 | 정지→정속 및 정속→정지 로그 5회 | 미생성 | Pinky bridge config |
| `angular_velocity` | rad/s | 0.6 | 미측정 | 미측정 | 제자리 90°·180° 회전 각 5회 | 미생성 | Pinky bridge config |
| `angular_acceleration` | rad/s² | 2.0 | 미측정 | 미측정 | 회전 속도 변화와 overshoot 로그 | 미생성 | Pinky bridge config |
| `footprint_radius` | m | 0.3 | 미측정 | 미측정 | Pinky와 바구니의 최대 외곽 치수 실측 | 미생성 | Pinky bridge config·RMF profile |
| `vicinity_radius` | m | 0.5 | 미측정 | 미측정 | footprint에 POC 통로 안전 여유를 더해 주행 검증 | 미생성 | Pinky bridge config·RMF profile |
| `nominal_voltage` | V | 12.0 | 미측정 | 미측정 | 배터리 사양서 확인 후 완충·운행 전압 기록 | 미생성 | Pinky bridge config |
| `capacity` | Ah | 24.0 | 미측정 | 미측정 | 사양값으로 시작해 동일 코스 SOC 감소로 usable capacity 보정 | 미생성 | Pinky bridge config |
| `charging_current` | A | 5.0 | 미측정 | 미측정 | 충전기 사양 또는 충전 중 `BatteryState.current` 기록 | 미생성 | Pinky bridge config |
| `mass` | kg | 20.0 | 미측정 | 미측정 | Pinky+고정 장치+POC 대표 적재물을 저울로 측정 | 미생성 | Pinky bridge config |
| `moment_of_inertia` | kg·m² | 10.0 | 미측정 | 미측정 | 형상·질량 기반 초기 계산 후 회전 소비 실험으로 보정 | 미생성 | Pinky bridge config |
| `friction_coefficient` | 무차원 | 0.22 | 미측정 | 미측정 | 평탄 바닥 왕복의 실제 SOC 감소와 모델 결과를 비교해 보정 | 미생성 | Pinky bridge config |
| `ambient_power` | W | 20.0 | 미측정 | 미측정 | 모터 정지 20~30분의 SOC 감소를 전력으로 환산 | 미생성 | Pinky bridge config |
| `expected_loading_duration_s` | s | 30.0 | 미측정 | 미측정 | 냉동창고 적재 단계 10회, 실패 포함 P90 | 미생성 | `EstimateTaskEnergy` 요청 |
| `expected_handover_duration_s` | s | 30.0 | 미측정 | 미측정 | 포장대 인계 단계 10회, 실패 포함 P90 | 미생성 | `EstimateTaskEnergy` 요청 |
| `task_time_buffer_s` | s | 15.0 | 미측정 | 미측정 | 통신·정렬 지연의 예측 대비 실제 오차로 보정 | 미생성 | `EstimateTaskEnergy` 요청 |

POC에서는 냉동 기능이 실제로 작동하지 않으므로 저온 보정은 제외한다. OMX가 Pinky 배터리를 사용하지 않는다는 결정에 따라 tool power도 제외한다. 두 항목 모두 `POC 제외`이며 0W로 측정 완료된 값이라는 의미가 아니다.

## 4. 반드시 직접 측정해야 하는 최소 파라미터

| 분류 | 측정 대상 | 완료 조건 |
|---|---|---|
| 차량 운동 | 선속도·선가속도·각속도·각가속도 | 무적재 반복 5회 원본 로그와 대표값 |
| 외형 안전 | footprint·vicinity | 최대 적재 외곽 실측과 좁은 통로 시험 |
| 배터리 | 전압·usable capacity·충전 전류 | 사양 근거와 실제 SOC/시간 로그 |
| 기계 모델 | 질량·관성모멘트·마찰계수 | 초기 근거와 직선·회전 소비 보정 기록 |
| 기본 소비 | ambient power | 모터 정지 20~30분 기록 |
| 작업시간 | 적재·인계·buffer | 단계별 10회와 P90 계산표 |
| 모델 검증 | 이동시간·시작 SOC·종료 SOC | 냉동↔포장 양방향 각각 5회 이상 |

## 5. 항목별 측정 절차

### 5.1 공통 준비

1. 동일한 바닥, 속도 제한, 경로, 적재 조건을 사용한다.
2. `TRIHOUSE_MEASUREMENT_RUN_ID`를 실험별 고유 값으로 설정한다.
3. 출발 전 실제 SOC와 `BatteryState` freshness를 확인한다.
4. 측정 시작·종료 시각, 적재 질량, 성공 여부를 기록한다.
5. 실패 주행도 삭제하지 않고 실패 이유와 함께 보존한다.

### 5.2 속도와 가속도

- 3m 이상 직선 구간에서 무적재 왕복을 최소 5회 수행한다.
- odometry의 시간·위치·속도로 가속 구간, 정속 구간, 감속 구간을 나눈다.
- 최고 순간값 대신 5회 모두에서 안전하게 재현된 제한값을 채택한다.
- 90°와 180° 회전은 각각 5회 수행해 실제 시간과 overshoot를 기록한다.

### 5.3 footprint와 vicinity

- 바구니와 돌출 부품을 포함한 최대 폭과 길이를 실측한다.
- 원형 profile을 유지할 경우 중심에서 가장 먼 외곽점까지의 길이를 `footprint_radius` 후보로 쓴다.
- `vicinity_radius`는 footprint보다 작게 두지 않는다.
- 가장 좁은 POC 통로에서 교행 또는 정차 안전성을 확인한 뒤 검증 완료로 전환한다.

### 5.4 배터리와 기계 모델

- nominal voltage와 capacity는 제조사 사양을 원본 증거로 먼저 남긴다.
- 유휴, 직선, 회전, 무적재 왕복, 최대 적재 왕복을 분리해 기록한다.
- 한 번의 SOC 변화에 맞추기 위해 여러 파라미터를 동시에 바꾸지 않는다.
- ambient power를 먼저 보정하고, 직선 소비로 friction, 회전 소비로 moment of inertia를 순서대로 조정한다.

### 5.5 작업 단계 시간

- 냉동창고 적재와 포장대 인계를 각각 10회 수행한다.
- 정상 소요시간뿐 아니라 재정렬·재시도 시간을 포함한다.
- 기본 입력값은 평균보다 P90을 사용한다.
- `task_time_buffer_s`는 적재·인계 시간에 이미 포함된 지연을 중복 계산하지 않는다.

## 6. 반드시 수행할 배터리·ETA 보정 실험

| 순서 | 실험 | 조건·반복 | 기록할 값 | 보정 대상 |
|---:|---|---|---|---|
| 1 | 유휴 소비 | 모터 정지 20~30분 | 시작/종료 SOC, 시간 | `ambient_power` |
| 2 | 직선 왕복 | 무적재, 동일 속도, 5회 | 거리, 시간, SOC 감소 | `friction_coefficient` |
| 3 | 회전 반복 | 90°·180° 각 5회 | 회전시간, SOC 감소 | `moment_of_inertia` |
| 4 | 냉동→포장 | 무적재 5회 | RMF ETA, 실제 시간, 예측/실제 SOC | 종합 모델 |
| 5 | 포장→냉동 | 무적재 5회 | RMF ETA, 실제 시간, 예측/실제 SOC | 방향별 graph·모델 |
| 6 | 최대 적재 왕복 | POC 최대 바구니, 5회 | 질량, 시간, SOC 감소 | 대표 `mass`와 보수성 |
| 7 | 충전 | 10% 부근→30% 이상 | 시간별 SOC·충전 상태 | `charging_current`, 재투입 시간 |

`consumption_percent_per_minute`는 Open-RMF가 없는 개발·단위 테스트의 명시적 fallback에만 사용한다. Open-RMF 연결 후에도 위 실험은 모델값이 실제 Pinky와 맞는지 확인하기 위해 반드시 필요하다.

## 7. bridge 설정 필드 매핑

office 설정 파일은 유지하고 수정하지 않는다. 실제 Pinky 연결 구현 시 별도의 Pinky config/launch를 만들며, 측정표가 `측정 완료` 이상인 값만 옮긴다.

| 설정 그룹 | bridge 필드 | 근거 |
|---|---|---|
| 대상 식별 | `fleet_name`, `robot_name` | 실제 Pinky fleet adapter 등록 이름 |
| graph | `nav_graph_file` | `waypoint.md`에서 export·검증한 nav graph |
| 운동 | `linear_velocity`, `linear_acceleration`, `angular_velocity`, `angular_acceleration`, `reversible` | 이동·회전 시험 |
| 외형 | `footprint_radius`, `vicinity_radius` | 최대 외곽 실측·통로 시험 |
| 배터리 | `nominal_voltage`, `capacity`, `charging_current` | 사양·SOC·충전 로그 |
| 기계 | `mass`, `moment_of_inertia`, `friction_coefficient` | 질량 실측·소비 보정 |
| 장치 | `ambient_power` | 유휴 소비 시험 |

설정 반영 후 다음 명령으로 실제 node 값을 확인한다.

```bash
ros2 param dump /trihouse_rmf_bridge
```

출력값을 측정표와 대조하고 office 초기 참고값이 의도치 않게 남아 있으면 적용 승인을 중단한다.

## 8. Open-RMF에서 받는 값과 직접 측정값

| 구분 | 값 | 의미·사용법 |
|---|---|---|
| Open-RMF 제공 | `travel_duration_s` | graph와 차량 운동 제한으로 계산한 이동 ETA |
| Open-RMF 제공 | `total_duration_s` | 이동+적재+인계+고정 여유 예상시간 |
| Open-RMF 제공 | `change_in_charge` | motion+ambient 모델의 예상 SOC 감소량 |
| Open-RMF 제공 | `finish_state_of_charge` | 현재 SOC에서 예상 감소량을 뺀 작업 종료 SOC |
| Open-RMF 제공 | route availability | 요청 waypoint까지 경로 생성 가능 여부 |
| 직접 측정 | 실제 이동시간 | RMF ETA 오차 검증 근거 |
| 직접 측정 | 실제 시작·종료 SOC | 예측 SOC 오차 검증 근거 |
| 직접 측정 | 적재·인계 시간 | 이동 외 작업시간 입력값 |
| 직접 측정 | 차량·배터리 파라미터 | RMF 모델 입력과 보정 근거 |

rmf-web `/fleets`의 battery는 현재 SOC이며 예상 종료 SOC가 아니다. 예상 종료 SOC는 `/trihouse/rmf/estimate_task_energy`의 `finish_state_of_charge`를 사용한다.

```text
total_duration_s
= travel_duration_s
 + expected_loading_duration_s
 + expected_handover_duration_s
 + task_time_buffer_s
```

## 9. 측정 결과 기록 양식

측정할 때 아래 표를 복사해 실험 기록 문서에 사용한다.

| 항목 | 기록값 |
|---|---|
| run ID | 미생성 |
| 파라미터 | 미측정 |
| 측정값·단위 | 미측정 |
| 측정일 | 미측정 |
| 장소·바닥·온도 | 미측정 |
| Pinky ID·software revision | 미측정 |
| 적재 질량 | 미측정 |
| 반복 횟수·성공 횟수 | 미측정 |
| 원본 로그 경로 | 미생성 |
| 계산 방법·대표값 | 미측정 |
| 예측 대비 실제 오차 | 미측정 |
| 상태 | 미측정 |
| 적용 승인자·승인일 | 미승인 |

## 10. 적용 승인 체크리스트

- [ ] 필수 파라미터가 모두 `측정 완료` 이상이다.
- [ ] 각 값에 측정일, 조건, 반복 횟수, 원본 로그가 있다.
- [ ] 핵심 경로 양방향을 각각 5회 이상 실행했다.
- [ ] RMF ETA와 실제 이동시간 오차를 계산했다.
- [ ] 예상 종료 SOC와 실제 종료 SOC 오차를 계산했다.
- [ ] 허용 오차는 반복 결과를 본 뒤 운영팀이 승인했다.
- [ ] `office_bridge.yaml` 초기 참고값을 실제 설정에 그대로 복사하지 않았다.
- [ ] `waypoint.md`의 graph 연결 체크리스트가 완료됐다.
- [ ] 적용 승인자와 승인일을 기록했다.

허용 오차 숫자는 실험 전 임의로 확정하지 않는다. 반복 결과가 나온 뒤 승인한 기준과 계산 근거를 기록해야 `검증 완료`로 전환한다.

## 11. 자동 측정 로그

기본 저장 위치는 `~/.ros/trihouse/measurements/<run_id>/`다. Pinky와 Control Tower에 같은 run ID를 설정한다.

| 파일 | 자동 기록 내용 |
|---|---|
| `run_metadata.json` | schema, run ID, 생성시각, component |
| `battery_telemetry_<robot_id>.jsonl` | 실제 SOC, freshness, 충전 상태, job/step, 정책 state |
| `rmf_energy_estimates.jsonl` | waypoint, 단계시간, RMF ETA, 예상 감소량·종료 SOC, source·오류 |
| `battery_policy_decisions.jsonl` | state/action/reason, 실제·예상 SOC, 배차 선택 여부 |

```bash
export TRIHOUSE_MEASUREMENT_RUN_ID=pinky_rmf_measure_01
export TRIHOUSE_MEASUREMENT_LOG_ROOT=$HOME/.ros/trihouse/measurements

find "$TRIHOUSE_MEASUREMENT_LOG_ROOT/$TRIHOUSE_MEASUREMENT_RUN_ID" \
  -maxdepth 1 -type f -print
tail -f \
  "$TRIHOUSE_MEASUREMENT_LOG_ROOT/$TRIHOUSE_MEASUREMENT_RUN_ID"/rmf_energy_estimates.jsonl
```

로그 저장 실패는 배차 판단을 바꾸지 않지만 해당 실험값은 원본 증거가 없으므로 `측정 완료`로 전환하지 않는다.

## 12. POC 배차 규칙 확인

| 현재 정책 | RMF 예상 종료 SOC | 결정 |
|---|---:|---|
| `LOCAL_ONLY` | 10% 초과 | 냉동↔포장 작업 허용(`ALLOW_LOCAL_JOB`) |
| `LOCAL_ONLY` | 5% 초과 10% 이하 | 해당 작업 완료 후 충전 복귀(`COMPLETE_THEN_RETURN`) |
| `LOCAL_ONLY` | 5% 이하 | 새 작업 금지, 즉시 충전 복귀(`RETURN_TO_CHARGE`) |
| `LOCAL_ONLY` | 값 없음/timeout/경로 없음 | 안전점 대기(`WAIT_AT_SAFE_NODE`) |

파라미터 측정은 이 정책 임계값을 임의로 변경하지 않는다. 예측 오차가 크면 모델을 보정하고, 임계값 변경은 별도의 정책 결정으로 다룬다.
