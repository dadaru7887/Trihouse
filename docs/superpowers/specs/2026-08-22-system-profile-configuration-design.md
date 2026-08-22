# Trihouse 시스템 실행 프로파일 설계

## 목적

첫 실물 통합 테스트에서 여러 PC와 로봇에 긴 명령행 인자를 반복해서 입력하지 않는다. 운영자는 하나의 시스템 프로파일과 실행 역할만 선택하고, bringup이 프로파일을 검증한 뒤 Compose 환경과 ROS 2 launch 인자를 일관되게 구성한다.

이 설계의 기준 프로파일은 `physical_01`이고 ROS 2 통신 도메인은 `12`이다.

## 결정

`config/profiles/physical_01.yaml`을 실물 시스템의 정적 구성 정본으로 사용한다. 이 파일은 장비 식별자, ROS namespace, DHCP 예약 주소, 지도와 파라미터 파일 경로, 기능 활성화 여부, 포장대와 작업자 매핑을 담는다.

모든 프로그램이 이 YAML을 제각각 해석하지 않는다. 공용 프로파일 로더가 한 번 검증하고 역할별 resolved configuration을 만든다. ROS launch, Gateway, JobRunner 및 Compose bringup은 같은 검증 결과를 사용한다. 관제 웹 UI는 프로파일 파일을 직접 읽지 않고 Gateway의 Job 응답에 기록된 배정 결과를 사용한다.

다음 값은 시스템 프로파일 밖에 둔다.

- DB·RTSP 암호와 토큰: 호스트별 `.env`
- Nav2 footprint, inflation, 속도와 같은 노드 알고리즘 값: 기존 ROS parameter YAML
- 주문, Job 상태, 실행 단계와 실제 장비 배정 결과: DB
- 일회성 디버그 override: 명시적으로 허용된 launch argument

## 대안 검토

### 하나의 평평한 YAML을 모든 프로세스가 직접 읽기

처음에는 단순하지만 각 프로세스가 서로 다른 기본값과 파싱 규칙을 갖게 된다. 브라우저에 내부 설정 파일을 노출해야 하고, ROS parameter 형식과 FMS 업무 설정 형식도 섞인다. 채택하지 않는다.

### 계층형 시스템 프로파일과 공용 로더

하나의 진입점에서 전체 시스템 구성을 확인하면서도 ROS parameter, 비밀값, 동적 DB 상태의 책임을 분리할 수 있다. 첫 실물 테스트에 이 방식을 채택한다.

### 중앙 설정 서비스

실행 중 설정 갱신과 다수 사이트 운영에는 유리하지만, 첫 실물 통합에는 별도 가용성·인증·캐시 문제가 생긴다. 이번 범위에는 포함하지 않는다.

## 파일 구조

```text
config/
  profiles/
    physical_01.yaml
    simulation.yaml
  narrow_zones.new_map_2.yaml
  marker_docks.new_map_2.yaml

scripts/
  trihouse_config.py
  bringup

.env.example
```

`trihouse_config.py`는 프로파일 로딩, 스키마 검증, 경로 정규화와 역할별 설정 해석을 담당한다. `bringup`은 이를 호출하는 실행 진입점이다. 실제 비밀값이 들어간 `.env`는 버전 관리하지 않는다.

## 프로파일 스키마

```yaml
schema_version: 1
profile_name: physical_01
use_sim_time: false

ros:
  domain_id: 12
  rmw_implementation: rmw_fastrtps_cpp
  discovery_range: subnet

hosts:
  control:
    address: 192.168.0.9
  ai_5080:
    address: 192.168.0.7

control:
  gateway_host: 192.168.0.9
  gateway_http_port: 8080
  gateway_robot_port: 8788

map:
  map_name: new_map_2
  map_yaml: pinky_pro_alpha/pinky_navigation/map/new_map_2.yaml
  nav2_params_directory: .trihouse/p0/nav2
  narrow_zones_file: config/narrow_zones.new_map_2.yaml
  marker_docks_file: config/marker_docks.new_map_2.yaml

robots:
  pinky_01:
    device_id: PK_01
    namespace: pinky_01
    host: 192.168.0.21
    nav2_params_file: hardware_pinky_01.yaml
    vision_config_file: pinky_1.yaml

  pinky_02:
    device_id: PK_02
    namespace: pinky_02
    host: 192.168.0.22
    nav2_params_file: hardware_pinky_02.yaml
    vision_config_file: pinky_2.yaml

omx_stations:
  omx_01:
    device_id: OMX_01
    namespace: omx_01
    host: 192.168.0.31

  omx_02:
    device_id: OMX_02
    namespace: omx_02
    host: 192.168.0.32

packing_dock_assignments:
  - packing_dock_id: PACKING-01-DOCK-01
    worker_id: W-FIELD-01
  - packing_dock_id: PACKING-01-DOCK-02
    worker_id: W-FIELD-02

features:
  navigation_enabled: true
  docking_enabled: true
  narrow_zone_enabled: true
  vision_enabled: true
  omx_enabled: true
```

설정 필드와 논리 키는 소문자 `snake_case`를 사용한다. `PK_01`, `OMX_01`, `PACKING-01-DOCK-01`, `W-FIELD-01`은 DB와 명령 메시지에서 쓰는 불변 식별자이므로 기존 표기를 유지한다.

프로파일 내부 경로는 저장소 루트 기준 상대 경로를 우선한다. 로더는 저장소 루트를 기준으로 절대 경로를 계산하고 대상 파일의 존재 여부를 검증한다. 호스트마다 다른 설치 경로를 YAML에 복제하지 않는다.

## 역할과 실행 명령

지원 역할은 다음과 같다.

- `control`: AI-Server-4060의 Gateway, DB, 관제 UI와 JobRunner
- `ai_5080`: AI-Server-5080의 추론 서비스
- `pinky_01`, `pinky_02`: 각 Pinky 내장 Raspberry Pi의 ROS 2 bringup
- `omx_01`, `omx_02`: 각 OMX PC의 ROS bridge와 LeRobot worker
- `simulation`: 실물과 동일한 식별자와 인터페이스를 사용하는 시뮬레이션

기본 실행 형태는 다음과 같다.

```bash
./scripts/bringup --profile config/profiles/physical_01.yaml --role pinky_01
```

운영자가 매번 입력하는 값은 `profile`과 `role` 두 개로 제한한다. 디버깅이 필요한 경우에만 허용 목록에 있는 값을 override한다. 알 수 없는 override는 즉시 실패한다.

## 로딩 순서

1. `bringup`이 프로파일 경로와 역할을 받는다.
2. 공용 로더가 YAML 문법, `schema_version`과 필수 필드를 검증한다.
3. `.env`에서 해당 호스트의 비밀값과 배포 전용 값을 읽는다.
4. 프로파일의 상대 경로를 저장소 루트 기준으로 해석하고 파일 존재 여부를 검사한다.
5. 전체 프로파일의 식별자와 매핑 불변 조건을 검사한다.
6. 선택한 역할에 필요한 최소 설정만 resolved configuration으로 만든다.
7. `ROS_DOMAIN_ID=12`, RMW와 discovery 환경을 자식 프로세스에 적용한다.
8. Compose 역할이면 필요한 compose 파일과 환경을 검증한 뒤 시작한다.
9. ROS 역할이면 최상위 launch에 namespace, device ID와 parameter 파일 경로를 전달한다.

`doctor`는 1~6단계와 포트·파일·장치 존재 확인까지만 수행하며 서비스를 시작하지 않는다. `bringup`은 doctor를 통과한 뒤 서비스를 시작한다.

## ROS 2 경계

ROS 2 launch argument는 실행 구조를 고르는 값에 한정한다.

- `profile`
- `role`
- `use_sim_time`의 허용된 override
- 필요 시 단일 기능의 진단용 enable/disable

노드가 소비하는 계산·제어 값은 ROS parameter YAML로 전달한다. 로봇 구분은 namespace로 하고, DB 및 명령 라우팅은 `device_id`로 한다.

```text
pinky_01 역할
→ namespace /pinky_01
→ 메시지 device_id PK_01

pinky_02 역할
→ namespace /pinky_02
→ 메시지 device_id PK_02
```

두 식별자의 1:1 매핑은 프로파일에 한 번만 기록한다. 노드는 토픽명을 하드코딩하지 않고 상대 이름을 사용해 namespace가 적용되게 한다.

## Compose 경계

Compose는 이미지, 컨테이너, 볼륨, 네트워크와 프로세스 생명주기를 관리한다. 프로파일 자체를 Compose 변수 전체로 펼치지 않는다. `bringup`이 역할에 맞는 필수 환경만 Compose에 전달하고, 필요한 설정 파일은 읽기 전용으로 mount한다.

`.env`에는 다음만 둔다.

- DB 계정과 암호
- RTSP 계정과 암호
- 외부 서비스 토큰
- 호스트 bind 주소처럼 배포 호스트에 종속된 값

`ROS_DOMAIN_ID`처럼 시스템 전체에서 동일해야 하는 비밀이 아닌 값은 프로파일을 정본으로 한다. 호스트 `.env`에 같은 항목이 있으면 로더는 값이 동일한지 검사하고 불일치 시 시작을 거부한다.

## 포장대 작업자 배정

포장대와 작업자의 고정 관계는 `packing_dock_assignments`가 정본이다. JobRunner가 포장대를 배정할 때 Gateway는 해당 매핑을 사용해 Job의 assignment context에 다음 값을 함께 기록한다.

```json
{
  "packing_dock_code": "PACKING-01-DOCK-01",
  "packing_worker_id": "W-FIELD-01"
}
```

관제 UI는 프로파일을 직접 읽지 않고 Job API 응답의 `packing_worker_id`를 표시하고 완료 요청에 사용한다. Gateway는 완료 요청의 `worker_id`가 해당 Job의 `packing_worker_id`와 같은지, DB의 활성 작업자인지, 포장 준비 단계가 완료됐는지를 다시 검증한다.

작업자 완료 팝업은 다음 조건이 모두 충족되는 순간 한 번만 표시한다.

- 포장 도크 배정이 존재한다.
- 포장 도크 `handover` 단계가 `succeeded`이다.
- `worker_completion` 대기 단계가 `pending` 또는 `running`이다.
- 해당 Job의 완료 승인이 아직 기록되지 않았다.

팝업을 닫아도 완료 처리하지 않는다. 관제 화면에 승인 대기 상태를 유지하며 다시 열 수 있어야 한다. 완료 요청은 Job과 assignment revision을 포함한 안정적인 idempotency key를 사용한다.

## 검증 규칙

bringup은 프로세스를 시작하기 전에 다음 조건을 모두 확인한다.

- `schema_version`이 지원되는 값이다.
- `profile_name`과 역할 이름이 소문자 `snake_case`이다.
- `ros.domain_id`가 `12`이다.
- 각 `device_id`, namespace와 IP가 중복되지 않는다.
- `pinky_01 ↔ PK_01`, `pinky_02 ↔ PK_02` 매핑이 존재한다.
- `omx_01 ↔ OMX_01`, `omx_02 ↔ OMX_02` 매핑이 존재한다.
- 모든 포장대와 작업자 매핑이 중복되지 않는다.
- 포장대와 작업자 ID가 DB seed의 불변 ID 형식과 일치한다.
- 참조한 지도, Nav2, narrow-zone, docking과 vision 파일이 존재한다.
- 실물 프로파일에서 `use_sim_time`이 `false`이다.
- 선택한 역할의 host가 현재 호스트에서 확인한 DHCP 예약 주소와 일치한다.
- `.env`에 필요한 비밀값이 존재하고 placeholder가 아니다.

검증 실패 시 어떤 필드와 파일이 문제인지 출력하고 어떤 프로세스도 시작하지 않는다.

## 오류 처리와 감사

- YAML 파싱 및 스키마 오류: 시작 전 실패, 필드 경로 출력
- 파일 누락: 시작 전 실패, 해석된 절대 경로 출력
- 현재 호스트 IP 불일치: 실제 IP와 기대 IP를 함께 출력하고 시작 거부
- DB 식별자 불일치: Gateway readiness 실패
- Job에 포장 작업자 매핑 없음: 완료 팝업을 띄우지 않고 관제 경고 표시
- 완료 작업자 불일치: Gateway가 충돌 응답을 반환하고 operation event 기록

로그와 API 응답에는 암호나 인증된 RTSP URL을 출력하지 않는다.

## 호환성과 전환

기존 launch 파일의 개별 argument는 한 번에 제거하지 않는다. 첫 단계에서는 프로파일 로더가 기존 argument를 생성해 현재 launch에 전달한다. 프로파일 경로가 없는 직접 실행은 테스트에서 경고 대상으로 만들고, 실물 runbook은 프로파일 기반 명령만 제공한다.

현재 승인된 작업은 격리 worktree에서 수행한다. 이 worktree의 `.env.example`에 있는 `ROS_DOMAIN_ID=12`를 기준으로 하며, main 작업 디렉터리에 남아 있는 `52`는 통합 전에 `12`로 맞춘다.

## 테스트 전략

루트 `tests/`는 simulation 전용 흐름을 유지한다. 프로파일 자체의 정적 검증은 `tests/config/`에 두지 않고 설정 로더 소유 모듈의 단위 테스트에 둔다. 실제 장치와 네트워크 확인 절차는 `scripts/hardware/`의 읽기 전용 점검 명령과 `docs/runbooks/`의 수동 절차로 둔다.

필수 자동 테스트는 다음과 같다.

- 정상 `physical_01` 및 `simulation` 프로파일 파싱
- 잘못된 schema version 거부
- 중복 device ID, namespace, IP 거부
- 누락된 참조 파일 거부
- 실물 `use_sim_time=true` 거부
- `ROS_DOMAIN_ID != 12` 거부
- 알 수 없는 역할과 override 거부
- 포장대-작업자 중복 및 누락 거부
- 역할별 resolved configuration 스냅샷
- 기존 launch가 resolved configuration을 정확히 전달하는 계약 테스트
- Gateway가 Job assignment에 `packing_worker_id`를 기록하는 테스트
- 잘못된 작업자의 완료 요청을 거부하는 테스트
- 포장 준비 시 한 번만 팝업을 표시하는 관제 UI 테스트

Compose 검증은 실제 컨테이너 시작 없이 `docker compose config --quiet`로 수행한다. ROS launch 검증은 노드를 움직이지 않는 launch description 및 namespace 계약 테스트로 수행한다.

## 완료 조건

- 운영자가 프로파일과 역할만 지정해 각 PC의 doctor 및 bringup을 실행할 수 있다.
- 모든 ROS 프로세스가 domain `12`를 사용한다.
- 두 Pinky와 두 OMX의 namespace 및 DB device ID 매핑이 한 정본에서 검증된다.
- 지도, Nav2, 협로와 docking 설정이 프로파일을 통해 동일하게 선택된다.
- 포장 도크별 작업자가 Job assignment에 기록되고 Gateway가 완료 요청을 검증한다.
- 포장 준비 상태에서 관제 UI 완료 팝업이 정확히 한 번 표시된다.
- 시뮬레이션과 실물이 같은 식별자 및 통신 인터페이스를 사용한다.
- 비밀값이 프로파일이나 로그에 포함되지 않는다.
