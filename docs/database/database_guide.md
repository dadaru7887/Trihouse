# Trihouse FMS 데이터베이스 가이드라인

기준 스키마: [db/schema_mysql.sql](../../db/schema_mysql.sql) (v5: FMS 17개 + recovery 2개 테이블)
관련 문서: [환경 구성](../deployment/environment_overview.md) · [DB 시연](../deployment/database_demo.md) · [Recovery Memory](../architecture/recovery_memory.md)

이 문서는 `trihouse_fms` 스키마를 읽고 쓰는 모든 코드가 지켜야 할 규약을 정리한다. 스키마 자체의 정의는 SQL 파일이 기준이며, 이 문서는 **왜 그렇게 설계했고 어떻게 써야 하는가**를 설명한다.

---

## 목차

1. [적용 범위와 권한 경계](#1-적용-범위와-권한-경계)
2. [컨테이너 토폴로지와 DB 경계](#2-컨테이너-토폴로지와-db-경계)
3. [기본 규약](#3-기본-규약)
4. [테이블 지도](#4-테이블-지도)
5. [테이블별 사용 가이드](#5-테이블별-사용-가이드)
6. [열거값 참조표](#6-열거값-참조표)
7. [트랜잭션 경계](#7-트랜잭션-경계)
8. [동시성 제어 규칙](#8-동시성-제어-규칙)
9. [조회 패턴과 인덱스](#9-조회-패턴과-인덱스)
10. [VLM/RL 학습 데이터 활용](#10-vlmrl-학습-데이터-활용)
11. [금지 사항과 안티패턴](#11-금지-사항과-안티패턴)
12. [스키마 변경 절차](#12-스키마-변경-절차)
13. [리뷰 체크리스트](#13-리뷰-체크리스트)

---

## 1. 적용 범위와 권한 경계

### 1.1 쓰기 주체는 FMS Gateway 하나뿐이다

```text
Flutter control_system UI
        | HTTPS / WebSocket
        v
FMS Gateway / Task Manager   <-- 유일한 MySQL 쓰기 주체
        | MySQL transaction
        v
MySQL trihouse_fms

FMS Gateway <-> Safety Supervisor

[주행: 2계층]
FMS Gateway <-> RMF Adapter <-> Open-RMF <-> Pinky Adapter <-> Pinky-Pro / Nav2
                (함대·교통 계층)                (로봇 계층)

[조작: 1계층]
FMS Gateway <-> OMX Adapter <-> Cyclo / MoveIt 2 / OMX-AI
                (로봇 계층)
```

| 주체 | MySQL 권한 | 비고 |
| --- | --- | --- |
| FMS Gateway | 읽기 + 쓰기 | 모든 상태 확정의 단일 지점 |
| Flutter UI / 웹 관제 | 없음 | Gateway API/WebSocket만 사용 |
| RMF / Pinky / OMX Adapter | 없음 | Gateway를 통해 상태 보고 |
| VLM / RL 파이프라인 | 없음 | 2.4의 파일 교환 또는 read-only 계정 |
| 운영 분석 · 대시보드 | 읽기 전용 계정 | 별도 계정 분리 |

### 1.2 어댑터 세 개의 계층 구분

**Pinky Adapter와 OMX Adapter는 둘 다 로봇 수준이다.** 어댑터를 가르는 축은 담당 도메인(주행/조작)이 아니라 **위에 함대(fleet) 계층이 있는가**다.

| 어댑터 | 계층 | 상위에 무엇이 있는가 | 대상 | DB 채널 |
| --- | --- | --- | --- | --- |
| **RMF Adapter** | 함대·교통 | — (Open-RMF 자체) | Pinky 2대를 묶은 fleet | `rmf` |
| **Pinky Adapter** | 로봇 (주행) | RMF Fleet Adapter | Pinky 개별 1대 | `pinky` |
| **OMX Adapter** | 로봇 (조작) | FMS Gateway 직접 | OMX 개별 1대 | `omx` |

**왜 주행만 2계층이고 조작은 1계층인가**

주행로봇 2대는 **같은 바닥을 공유**한다. 경로가 물리적으로 겹치므로 누가 먼저 지나갈지 협상하는 계층이 반드시 필요하고, 그것이 Open-RMF다. 반면 로봇팔 2대는 **각자 고정된 작업장에 있어 경로가 겹치지 않는다.** 필요한 것은 교통 협상이 아니라 작업장·인계 지점의 독점뿐이고, 그건 `reservations`의 `exclusive_lock`이 처리한다.

> 즉 **로봇팔에 한해서는 MySQL `reservations`가 함대 계층의 역할을 대신한다.** 이것이 OMX에 RMF에 해당하는 중간 계층이 없는 이유다.

**스키마에 남은 근거**

`chk_messages_channel`이 `('rmf','pinky','omx')`로 정의되어 있는데, 이 셋은 같은 종류가 아니다.

- `rmf` — **계층** 채널. 장비가 아니라 교통·배차 권한을 가진 시스템과 주고받는 메시지
- `pinky`, `omx` — **장비** 채널. 개별 로봇에 내리는 명령과 그 응답

`job_steps.rmf_task_id`가 `rmf` 채널로 채워지고, `device_states`는 `pinky`/`omx` 채널로 채워진다. 채널이 섞이면 멱등 키 공간이 충돌하므로 어댑터도 이 경계로 나눈다.

**분리를 유지해야 하는 실질적 이유**

1. **장애 격리** — RMF가 내려가도 로봇 텔레메트리는 관제 화면과 `device_states`로 계속 흘러야 한다. 반대로 로봇 한 대가 offline이어도 나머지 fleet의 배차는 계속된다.
2. **계약 안정성 차이** — Open-RMF task API는 표준이라 안정적이지만, Pinky의 ROS 2 인터페이스(action 이름, frame, 단위, heartbeat, boot session)와 OMX/Cyclo/MoveIt skill 이름은 **아직 확정되지 않았다** (설계 스펙 §Hardware-contract). 한 덩어리로 두면 미확정 계약이 바뀔 때마다 RMF 연동 코드가 흔들린다.
3. **배포 형태와 무관** — 프로세스를 하나로 합치든 셋으로 나누든 구현 선택이다. 하지만 **DB 채널과 책임 경계는 반드시 분리해서 기록한다.**

### 1.3 데이터베이스가 결정하지 않는 것

- **주행 교통과 전역 경로**: Open-RMF의 권한이다. `reservations`는 RMF lane schedule을 복제하지 않는다.
- **로컬 장애물 회피와 즉시 정지**: Nav2 / Collision Monitor의 권한이다.
- **최종 안전 판단**: Safety Supervisor의 권한이다.

DB는 이 판단들을 **기록**하고, 그 기록이 나중에 학습 데이터가 된다. "결정하지 않는다"와 "학습 근거를 제공하지 않는다"는 다른 이야기다 — 10절 참조.

`reservations`가 관리하는 자원은 도크, 포장대, OMX 작업장, 장비 사용 시간, 그리고 RMF가 표현하지 못하는 특수 단일 진입 구역으로 한정한다.

---

## 2. 컨테이너 토폴로지와 DB 경계

### 2.1 서비스는 컨테이너 단위로 나눈다

의존성 격리를 위해 환경을 따로 "만드는" 것이 아니라, **서비스가 원래 컨테이너 단위로 나뉘고 격리는 그 경계에서 자동으로 따라온다.** 호스트에서 conda 환경과 venv를 나란히 관리할 일은 없다.

| 서비스 | 이미지 기반 | 런타임 | GPU | DB 접근 |
| --- | --- | --- | --- | --- |
| `mysql` | `mysql:8.4` | — | 없음 | 자기 자신 |
| `gateway` | slim Python 3.12 + [requirements.txt](../../fms_gateway/requirements.txt) | FastAPI / uvicorn | 없음 | **읽기 + 쓰기 (유일)** |
| `web` (관제) | 기존 [rmf-web-dashboard Dockerfile](../../control_system/openrmf/docker/rmf-web-dashboard/Dockerfile) (nginx) | 정적 자산 | 없음 | **없음** |
| `vision` (VLM/RL) | `compose.ai_5080.yaml`에서 고정한 CUDA/Python image | model runtime | **필요** | **없음** |

한 이미지에 합치면 안 되는 이유는 여전히 유효하지만, 컨테이너를 나누면 **애초에 마주칠 일이 없다.**

| 충돌 | 내용 |
| --- | --- |
| Python 버전 | `unified_env`는 3.10 고정 (`spconv-cu124`, `pointops`, `ocnn` 등 컴파일 확장이 이 버전에 맞춰 빌드됨). Gateway는 3.12. |
| pydantic 세대 | `gradio==3.35.2`는 pydantic 1.x 시대의 핀, `pydantic-settings==2.14.2`는 pydantic ≥ 2 요구. |
| 이미지 크기 | 비전 이미지는 CUDA 툴체인 포함으로 수 GB 단위다. Gateway를 여기 얹으면 배포·재시작이 느려진다. |
| 갱신 주기 | 학습 환경은 실험 재현이 목적이라 잠가 둔다. Gateway는 보안 패치를 따라간다. |

### 2.2 네트워크 경계 — 이 절의 핵심

**MySQL 포트에 닿을 수 있는 컨테이너는 `gateway` 하나뿐이어야 한다.** 1.1의 권한 경계를 문서가 아니라 네트워크로 강제한다.

```yaml
# compose.yaml — 네트워크 분리 예시
networks:
  fms_internal:          # DB 전용. 외부 노출 없음
    internal: true
  fms_edge:              # API 통신용

services:
  mysql:
    image: mysql:8.4
    networks: [fms_internal]
    # ports: 를 두지 않는다. 개발 중 DB 툴이 필요하면 127.0.0.1 바인딩으로만 노출한다.

  gateway:
    build: ./fms_gateway
    networks: [fms_internal, fms_edge]   # 유일하게 양쪽에 속한다
    depends_on:
      mysql: {condition: service_healthy}

  web:
    build: ./control_system/openrmf/docker/rmf-web-dashboard
    networks: [fms_edge]                 # DB 네트워크에 없다

  vision:
    image: ${TRIHOUSE_AI_IMAGE}
    networks: [fms_edge]                 # DB 네트워크에 없다
```

`web`과 `vision`은 `fms_internal`에 속하지 않으므로 **MySQL 호스트 이름 자체가 해석되지 않는다.** 실수로 드라이버를 넣어도 접속할 수 없다. 이것이 "UI/학습 파이프라인은 DB에 직접 쓰지 않는다"를 지키는 가장 확실한 방법이다.

> 개발 DB는 `compose.db.yaml`에서 `127.0.0.1:3306`으로만 노출한다. Gateway를 같은 Docker network로 옮긴 운영 구성에서는 host port를 제거한다.

### 2.3 시간대는 모든 컨테이너에 전파한다

DB 쪽은 이미 두 겹으로 맞춰져 있다.

```yaml
# compose.yaml
environment:
  TZ: Asia/Seoul
command:
  - --default-time-zone=+09:00
```

**나머지 컨테이너에도 `TZ: Asia/Seoul`을 넣는다.** 컨테이너 기본 시간대는 UTC이므로, 넣지 않으면 로그 시각과 DB 시각이 9시간 어긋나 장애 조사가 매우 어려워진다.

- `gateway` — `TZ` + 커넥션마다 `SET time_zone = '+09:00'` (둘 다 필요하다. 3.2 참조)
- `vision` — `TZ` + Python에서 `ZoneInfo("Asia/Seoul")`. Python 3.10에 `zoneinfo`가 표준 포함이라 추가 패키지가 없다.
- `web` — `TZ`. 브라우저 표시 시각은 클라이언트 로캘을 따르므로 서버 응답에 `+09:00` 오프셋을 반드시 포함시킨다.

```python
# vision 컨테이너 안에서
from zoneinfo import ZoneInfo
KST = ZoneInfo("Asia/Seoul")
```

naive `datetime`으로 시각을 다루면 DB의 `DATETIME(6)` 값과 어긋난다. 학습 데이터의 시간축이 어긋나면 원인을 찾기 매우 어렵다.

### 2.4 vision 컨테이너와 DB 사이의 데이터 교환

`vision`은 DB 네트워크에 없으므로 다음 두 경로만 쓴다.

**1) Gateway HTTP API — 온라인, 소량**

관측 기록이나 복구 제안을 실시간으로 남길 때. `unified_env.yml`에 `requests`가 이미 있어 추가 의존성이 없다.

```python
import requests
requests.post("http://gateway:8000/events", json={...}, timeout=5)
```

**2) Gateway가 내보낸 파일 — 오프라인 대량 학습 (권장)**

학습용 대량 조회는 Gateway가 배치로 실행해 Parquet/JSONL로 떨어뜨리고, `vision`은 공유 볼륨에서 파일만 읽는다. `unified_env.yml`에 `polars>=0.20.0`과 `h5py`가 이미 있어 DB 드라이버가 필요 없다.

```python
import polars as pl
df = pl.read_parquet("/data/exports/2026-08-03/job_steps_navigate.parquet")
```

내보낸 스냅샷은 반드시 `artifacts` 행으로 등록한다 (`artifact_type = 'dataset'`) — 10.5 참조.

> **read-only 계정 직접 조회는 예외적으로만.** 꼭 필요하면 `fms_readonly` 계정을 만들고 그 배치 잡만 `fms_internal`에 임시로 붙인다. `vision` 서비스 자체를 DB 네트워크에 상주시키지 않는다.
>
> ```sql
> CREATE USER 'fms_readonly'@'%' IDENTIFIED BY '...';
> GRANT SELECT ON trihouse_fms.* TO 'fms_readonly'@'%';
> ```

### 2.5 GPU와 자원 경합

GPU 예약은 `vision` 컨테이너에만 준다. MySQL과 Gateway는 CPU·메모리·디스크만 쓴다.

```yaml
  vision:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

GPU 경합은 없지만 **디스크 I/O 경합은 실재한다.**

- `trihouse_db` 볼륨과 학습 데이터셋(rosbag, pointcloud) 볼륨을 **다른 물리 디스크**에 둔다.
- 대량 학습 데이터 추출은 운영 시간대를 피해 배치로 돌린다 (10.6).
- 호스트 NVIDIA driver와 `compose.ai_5080.yaml`의 CUDA image 호환성을 배포 전에 확인한다.

### 2.6 AI 이미지 기준

과거 `docs/setup/vision_environment`의 Conda 환경과 `post_install.sh`는 archive로
이동했다. 새 AI 환경의 기준은 backend Dockerfile, 고정된 requirements/lock file,
`compose.ai_5080.yaml`이다. CUDA, PyTorch, compiled extension은 image digest와 model
version을 함께 기록하고, container 기동 후 네트워크에서 추가 패키지를 설치하지 않는다.

### 2.7 검증 명령

```bash
# 1) MySQL 설정
docker compose exec -T mysql sh -lc '
  MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot \
    -e "SELECT @@version, @@global.time_zone, @@character_set_server;"
'
#    8.4.x / +09:00 / utf8mb4 여야 한다

# 2) 네트워크 경계 — vision에서 DB가 보이면 안 된다
docker compose exec vision python -c "import socket; socket.gethostbyname('mysql')" \
  && echo "FAIL: vision이 DB 네트워크에 있다" || echo "OK: 격리됨"

# 3) 각 컨테이너 시간대
for s in mysql gateway vision web; do
  echo -n "$s: "; docker compose exec -T $s date +%Z%z
done   # 모두 KST+0900

# 4) vision 런타임
docker compose exec vision python -c \
  "import sys, torch; print(sys.version); print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
#    3.10.x / 2.5.0 / 12.4 / True

# 5) Gateway 테스트 (개발 단계, 호스트 venv 기준)
set -euo pipefail
cleanup_test_db() {
  docker compose -f compose.db_test.yaml down
}
trap cleanup_test_db EXIT
docker compose -f compose.db_test.yaml up -d --wait mysql_test
test "$(docker compose -f compose.db_test.yaml port mysql_test 3306)" = 127.0.0.1:3307
FMS_DB_HOST=127.0.0.1 \
FMS_DB_PORT=3307 \
FMS_DB_USER=fms_gateway \
FMS_DB_PASSWORD=test_gateway_password \
FMS_DB_DATABASE=trihouse_fms \
PYTHONPATH= \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
fms_gateway/.venv/bin/pytest -c fms_gateway/pytest.ini fms_gateway/tests -v
trap - EXIT
cleanup_test_db
```

### 2.8 저장 경계

**rosbag, point cloud, 영상, 이미지 원본을 MySQL에 넣지 않는다.** 원본은 NAS/MinIO/S3에 두고 `artifacts` 테이블에는 URI와 SHA-256만 기록한다 (5.15 참조). `vision` 컨테이너는 이 URI로 원본에 접근하고, DB는 계보와 무결성만 관리한다.

---

## 3. 기본 규약

### 3.1 엔진과 문자셋

```sql
CREATE DATABASE `trihouse_fms`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;
```

- MySQL **8.0 이상**만 지원한다. CHECK 제약, 생성 컬럼, 내림차순 인덱스, `SKIP LOCKED`를 모두 사용하기 때문이다. 운영 이미지는 `mysql:8.4`다.
- 모든 테이블은 `ENGINE=InnoDB`다. 트랜잭션과 FK가 필수다.
- 문자셋은 `utf8mb4`로 고정한다. 한글 위치명·품목명을 담는다.

### 3.2 시간 정책

| 규칙 | 내용 |
| --- | --- |
| 기준 시간대 | 대한민국 표준시 `Asia/Seoul` |
| 컬럼 타입 | `DATETIME(6)` — 마이크로초 정밀도, **시간대 정보 없음** |
| 세션 설정 | Gateway는 커넥션을 만들 때마다 `SET time_zone = '+09:00'` 실행 |
| API 표현 | ISO 8601에 `+09:00` 오프셋을 반드시 포함 |
| 외부 시각 | Adapter가 보낸 시각은 오프셋 확인 후 `Asia/Seoul`로 변환하여 저장 |

`DATETIME(6)`에는 시간대가 없으므로 **세션 시간대를 설정하지 않은 커넥션은 잘못된 값을 쓴다.** 서버의 `--default-time-zone=+09:00`이 있어도 클라이언트 드라이버가 세션 시간대를 UTC로 재설정할 수 있으므로 두 겹 모두 필요하다. 커넥션 풀을 쓸 경우 풀 초기화 콜백에서 설정한다.

시각 컬럼의 의미를 혼동하지 않는다.

- `observed_at` — 장비가 관측한 시각
- `integration_messages.created_at` — Gateway가 수신·생성한 시각
- `occurred_at` — 사건이 발생한 시각 (기록 시각이 아니다)

### 3.3 명명 규칙

| 대상 | 규칙 | 예시 |
| --- | --- | --- |
| 테이블 | 소문자 복수형 snake_case | `job_steps`, `inventory_lots` |
| 기본 키 | `<단수 테이블명>_id` | `job_step_id`, `lot_id` |
| 외래 키 컬럼 | `<대상>_id` | `parent_location_id`, `assigned_mobile_id` |
| 유니크 키 | `uq_<테이블>_<의미>` | `uq_jobs_code` |
| 일반 인덱스 | `idx_<테이블>_<의미>` | `idx_jobs_dispatch` |
| 외래 키 제약 | `fk_<테이블>_<의미>` | `fk_job_items_job` |
| CHECK 제약 | `chk_<테이블>_<의미>` | `chk_jobs_state` |
| 시각 컬럼 | `<동사 과거분사>_at` | `created_at`, `resolved_at` |
| 불리언 | `TINYINT(1)` + 형용사 | `active` |

이름이 길어지면 테이블 부분을 축약하기도 한다 (`inventory_lots` → `idx_lots_location`, `integration_messages` → `idx_messages_delivery`). 새 제약을 추가할 때는 **같은 테이블에 이미 있는 축약형을 따른다.**

### 3.4 타입 규칙

| 용도 | 타입 | 이유 |
| --- | --- | --- |
| 대량 증가 PK | `BIGINT UNSIGNED AUTO_INCREMENT` | 이력 테이블 고갈 방지 |
| 외부 부여 식별자 | `VARCHAR(64)` | `devices.device_id`, `workers.worker_id` |
| UUID | `CHAR(36)` | `integration_messages.message_id`, `operation_events.event_uuid` |
| 수량 | `INT` | 음수 델타를 표현해야 하므로 UNSIGNED 아님 |
| 비율 (0~1) | `DECIMAL(5,4)` / `DECIMAL(6,5)` | `progress`, `confidence` |
| 퍼센트 (0~100) | `DECIMAL(5,2)` | `battery_pct` |
| 좌표 | `DOUBLE` | ROS 좌표계와 동일 정밀도 |
| 무게 | `DECIMAL(10,3)` | kg 단위, 부동소수 오차 회피 |
| 해시 | `CHAR(64)` (hex) / `BINARY(32)` (raw) | `sha256` / `storage_uri_hash` |
| 자유 구조 | `JSON` | 아래 3.5 참조 |

`ENUM` 타입은 쓰지 않는다. 값 추가 시 `ALTER TABLE`이 테이블을 재작성하므로 `VARCHAR` + `CHECK` 조합으로 통일한다.

### 3.5 JSON 컬럼 사용 규칙

`metadata`, `context`, `payload`, `details`, `capabilities`, `input`, `result`, `geometry`, `properties`, `allowed_zones`가 JSON이다.

**허용**

- 장비 모델마다 다른 상태 필드 (`device_states.details`)
- 어댑터별로 형태가 다른 명령·응답 원문 (`integration_messages.payload`)
- 지도 도형 좌표 (`map_features.geometry`)
- 확정되지 않은 하드웨어 계약에 의존하는 필드
- 학습용 파생 지표 (`job_steps.result` — 10.4 참조)

**금지**

- 조인 키를 JSON 안에 넣는 것 — FK로 표현할 수 있으면 컬럼으로 뺀다
- 자주 필터링하는 값을 JSON에만 두는 것 — 컬럼으로 승격하거나 생성 컬럼 + 인덱스를 만든다
- 재고 수량, 상태 문자열 등 **불변식이 걸린 값** — CHECK가 걸리지 않는다

JSON은 스키마가 없으므로 어떤 키를 넣는지는 Gateway 코드의 타입 정의에 문서화한다. DB는 검증하지 않는다.

### 3.6 삭제 정책

물리 삭제는 원칙적으로 하지 않는다.

| 테이블 | 은퇴 방법 |
| --- | --- |
| `workers` | `active = 0`, `retired_at` 설정 |
| `devices` | `active = 0`, `retired_at` 설정 |
| `locations` | `state = 'blocked'` 또는 `'maintenance'` |
| `map_features` | `active = 0` |
| `inventory_lots` | `state = 'depleted'` / `'expired'` / `'damaged'` |
| `jobs` | `state = 'cancelled'` |

`inventory_moves`와 `operation_events`는 **추가 전용(append-only)** 원장이다. `UPDATE`와 `DELETE`를 하지 않는다. 잘못 기록한 값은 보정 행을 새로 넣어 상쇄한다.

FK의 삭제 동작은 다음과 같이 구분되어 있다.

| 동작 | 적용 대상 | 의미 |
| --- | --- | --- |
| `ON DELETE CASCADE` | `job_items.job_id`, `job_steps.job_id`, `reservations.job_id`, `device_states.device_id` | 부모가 사라지면 종속 행도 의미가 없다 |
| `ON DELETE SET NULL` | `reservations.job_step_id`, `device_states.current_job_step_id`, `integration_messages.job_step_id` | 참조는 끊어지되 행 자체는 남는다 |
| 기본값 (RESTRICT) | 그 외 전부 | 원장·감사 행이 참조 중이면 부모를 지울 수 없다 |

`inventory_moves`와 `operation_events`가 RESTRICT로 job/lot/device를 붙잡고 있으므로 **감사 이력이 있는 업무는 물리 삭제가 불가능하다.** 의도된 설계다.

---

## 4. 테이블 지도

### 4.1 도메인 그룹

| 그룹 | 테이블 | 역할 |
| --- | --- | --- |
| 공간·작업장 | `locations`, `map_features` | 창고의 모든 운영 위치와 지도 feature |
| 사람·권한 | `workers` | 책임 주체 계정 |
| 장비 | `devices`, `device_states` | 마스터와 최신 상태 |
| 업무 | `jobs`, `job_items`, `job_steps`, `job_step_attempts` | 업무 헤더 / 품목 / 현재 단계 / 실행 시도 이력 |
| 재고 | `inventory_lots`, `inventory_moves` | 현재 수량과 변동 원장 |
| 점유 | `reservations` | 자원 잠금과 시간 예약 |
| 연동 | `integration_messages` | 내구성 있는 메시지 큐 |
| 운영·AI·안전 | `incidents`, `operation_events` | 진행 중 사고와 감사 로그 |
| 학습 원본 | `artifacts` | 외부 저장소 파일의 위치·무결성 |
| 복구 Reference Memory | `location_recovery_profiles` | 검증된 `safe_node`의 사용 가능 상태와 신뢰도 |
| 복구 Episodic Memory | `trihouse_recovery.recovery_episodes`, `recovery_steps` | 실제 실행된 복구 사건과 행동 결과 |

### 4.2 주요 참조 관계

```text
locations ──self──> locations (parent_location_id)
    ^  ^  ^  ^
    │  │  │  └──── map_features.location_id
    │  │  └─────── devices.home_location_id / current_location_id
    │  └────────── inventory_lots.location_id
    └───────────── jobs.source/destination_location_id, job_steps.target_location_id,
                   reservations.location_id, incidents.location_id

workers ──> jobs.requested_by
        ──> incidents.raised_by / acknowledged_by / resolved_by_worker_id
        ──> operation_events.actor_worker_id

devices ──> device_states (1:1, PK = device_id)
        ──> job_steps.assigned_device_id
        ──> jobs.assigned_mobile_id
        ──> reservations.device_id
        ──> integration_messages.device_id, operation_events.device_id, artifacts.device_id

jobs ──self──> jobs (parent_job_id, 복구 계보)
     ──> job_items ──> inventory_lots
     ──> job_steps ──> job_step_attempts, reservations, device_states, integration_messages, artifacts
     ──> reservations, inventory_moves, operation_events, artifacts

inventory_lots ──> inventory_moves (추가 전용 원장)

map_features ──> reservations.map_feature_id (병목 잠금)

incidents ──> operation_events.incident_id

job_step_attempts ──> operation_events.attempt_uuid
operation_events ──> artifacts.event_id

locations ──> location_recovery_profiles (1:0..1, location_id UNIQUE)
workers ──> location_recovery_profiles.reviewed_by_worker_id

trihouse_recovery.recovery_episodes
    ──> trihouse_recovery.recovery_steps (1:N, ON DELETE CASCADE)
```

`trihouse_fms`와 `trihouse_recovery` 사이에는 FK를 만들지 않는다.
`source_event_uuid`, FMS job ID, `reference_node_uuid`, `map_revision`을 Gateway가
검증해 논리적으로 연결한다. 두 database의 백업·복구 수명주기는 독립적이다.

### 4.3 1:1 / 1:N 요약

- `devices` 1 — 1 `device_states` (PK가 `device_id`이므로 장비당 정확히 한 행, 최신 상태만)
- `jobs` 1 — N `job_items` / `job_steps` / `reservations`
- `job_steps` 1 — N `job_step_attempts` / `integration_messages` / `artifacts`
- `inventory_lots` 1 — N `inventory_moves`
- `locations` 1 — N `locations` (자기 참조 트리: 랙 → 슬롯)
- `jobs` 1 — N `jobs` (자기 참조: 원본 → 복구 job)
- `locations` 1 — 0..1 `location_recovery_profiles`
- `recovery_episodes` 1 — N `recovery_steps`

---

## 5. 테이블별 사용 가이드

### 5.1 `locations` — 공간·작업장

창고의 모든 운영 위치를 하나의 기준으로 관리한다. 랙·슬롯·도크·충전기·포장대·OMX 작업장·RMF waypoint가 모두 이 테이블의 행이다.

| 컬럼 | 설명 |
| --- | --- |
| `location_code` | 사람이 읽는 유일 코드. UI와 로그의 기본 식별자 |
| `parent_location_id` | 자기 참조. 랙 → 슬롯 계층 표현 |
| `location_type` | 10종 (6절 참조) |
| `map_name` + `rmf_waypoint_name` | RMF waypoint 연결. 두 컬럼 조합이 유니크 |
| `pose_x/y/yaw` | 지도 좌표계 기준 위치 |
| `state` | `available` / `reserved` / `occupied` / `blocked` / `maintenance` |

**사용 규칙**

- RMF waypoint가 없는 위치(논리적 랙 등)는 `map_name`과 `rmf_waypoint_name`을 NULL로 둔다. MySQL 유니크 키는 NULL 중복을 허용하므로 여러 행이 공존할 수 있다.
- `temperature_zone`은 NULL 허용이다. 온도 구분이 없는 도크·충전기는 NULL로 둔다. 슬롯·랙에는 반드시 채운다 — `inventory_lots.temperature_zone`과 일치하는지 확인하는 것은 Gateway의 책임이며 **DB는 검증하지 않는다.**
- `state`는 자원 예약과 별개다. 실제 잠금 상태는 `reservations`가 결정한다. `locations.state`는 운영자에게 보여주는 요약값이며, 두 값을 동기화하는 것은 Gateway의 책임이다.
- 조회는 `idx_locations_zone_type (zone_code, location_type)`을 탄다. `zone_code` 없이 `location_type`만으로 필터링하면 인덱스를 쓰지 못한다.

### 5.2 `map_features` — 지도 feature

정적 장애물, ArUco marker, 병목 통로, 출입문, 진입 금지 구역의 메타데이터다.

**실제 지도 파일(Nav2 pgm/yaml, RMF building map)은 이 테이블에 넣지 않는다.** 지도 파일은 버전 관리 저장소에 두고, 이 테이블은 UI 표시·운영 규칙·marker 조회에 필요한 정보만 가진다.

**사용 규칙**

- `(map_name, map_revision, feature_code)`가 유니크하다. 지도를 개정하면 `map_revision`을 올려 새 행을 추가하고, 이전 revision 행은 `active = 0`으로 둔다. 기존 행을 덮어쓰면 과거 사건의 위치 근거가 사라진다.
- `chk_map_features_marker`가 **`feature_type = 'fiducial'`일 때만 `marker_code`를 강제한다.** fiducial이 아닌데 marker_code를 넣거나, fiducial인데 비워두면 INSERT가 거부된다.
- `geometry`는 `NOT NULL` JSON이다. 형태(point / polygon / polyline)는 `feature_type`에 따라 Gateway가 해석하며 DB는 검증하지 않는다.
- 병목 예약(`reservation_mode = 'bottleneck_lock'`)의 대상이 되는 통로는 `feature_type = 'bottleneck'`으로 등록해야 한다.

### 5.3 `workers` — 사람·권한

관제 요청, 수동 복구, 안전 해제에 **책임을 남길 계정**이다.

> 이 테이블은 카메라가 감지한 사람의 실시간 위치를 기록하는 곳이 아니다. 작업자 침입 감지는 `incidents.incident_type = 'worker_intrusion'`으로 남긴다.

**사용 규칙**

- `worker_id`는 애플리케이션이 부여하는 문자열 키다 (예: `W-OP-01`). AUTO_INCREMENT가 아니므로 Gateway가 생성 규칙을 관리한다.
- `external_auth_id`는 SSO 연동용이며 유니크다. 미연동 계정은 NULL로 둔다.
- `allowed_zones`는 JSON 배열이다 (`JSON_ARRAY('ambient', 'outbound')`). 권한 판정은 Gateway가 수행하며 DB는 강제하지 않는다.
- 퇴사 시 행을 지우지 않고 `active = 0` + `retired_at`을 설정한다. 과거 `operation_events.actor_worker_id`가 이 행을 참조하고 있다.

### 5.4 `devices` — 장비 마스터

Pinky-pro 주행로봇과 OMX-AI 로봇팔의 공통 마스터다.

| 컬럼 | 설명 |
| --- | --- |
| `device_type` | `mobile` (Pinky) 또는 `arm` (OMX) |
| `fleet_name` | 장비 그룹 이름. 시드 기준 `pinky_fleet` / `omx_fleet` |
| `home_location_id` | 복귀 위치 (Pinky는 충전기, OMX는 자기 작업장) |
| `current_location_id` | 마지막으로 확인된 논리 위치. **실시간 좌표는 `device_states`에 있다** |
| `control_mode` | `automatic` / `manual` / `offline` / `maintenance` / `safety_hold` |
| `capabilities` | JSON. 어댑터가 참조하는 기능 플래그 |

**사용 규칙**

- `fleet_name`은 nullable이지만 시드는 두 종류 모두 채운다. 다만 **의미가 다르다** — `pinky_fleet`은 실제 Open-RMF fleet 이름과 대응하고, `omx_fleet`은 RMF와 무관한 논리적 그룹 라벨이다 (1.2 참조). RMF에 이름을 넘길 때 `device_type = 'mobile'`인 행만 대상으로 한다.
- `control_mode = 'safety_hold'`인 장비에는 새 `job_step`을 배정하지 않는다. 이 판정은 Gateway가 한다.
- 장비 교체 시 같은 `device_id`를 재사용하지 않는다. 과거 이력이 새 하드웨어에 붙어 학습 데이터의 라벨이 오염된다.
- `current_location_id`는 논리적 위치(어느 도크/작업장에 있는가)를 위한 것이고, `pose_x/y/yaw`는 `device_states`에 있다. 두 값을 혼용하지 않는다.

### 5.5 `device_states` — 장비 최신 상태

**장비당 정확히 한 행**이다 (`PRIMARY KEY (device_id)`). 관제 화면 갱신과 Gateway 재시작 후 복구에 쓴다.

**사용 규칙**

- `REPLACE`가 아니라 `INSERT ... ON DUPLICATE KEY UPDATE`를 쓴다. `REPLACE`는 DELETE + INSERT라서 `current_job_step_id`의 FK `ON DELETE SET NULL`이 함께 발동한다.
- **상태 이력은 여기에 쌓지 않는다.** 시간축 이력이 필요하면 `operation_events`에 남긴다. 이 테이블은 항상 최신 한 행만 유지한다.
- `observed_at`은 장비 관측 시각이다. 늦게 도착한 메시지가 최신 상태를 덮어쓰지 않도록 갱신 시 조건에 넣는다.

```sql
INSERT INTO device_states (device_id, observed_at, state, health, battery_pct)
VALUES (?, ?, ?, ?, ?)
ON DUPLICATE KEY UPDATE
  state       = IF(VALUES(observed_at) > observed_at, VALUES(state), state),
  health      = IF(VALUES(observed_at) > observed_at, VALUES(health), health),
  battery_pct = IF(VALUES(observed_at) > observed_at, VALUES(battery_pct), battery_pct),
  observed_at = IF(VALUES(observed_at) > observed_at, VALUES(observed_at), observed_at);
```

> `observed_at`을 **마지막에** 갱신한다. MySQL은 `ON DUPLICATE KEY UPDATE` 절을 왼쪽부터 평가하므로, `observed_at`을 먼저 바꾸면 뒤따르는 비교가 이미 갱신된 값을 보게 된다.

- `battery_pct`는 0~100, `progress`는 0~1이다. 두 스케일을 섞지 않는다.
- Pinky는 위치·배터리를, OMX는 관절·카메라·툴 상태를 `details` JSON에 기록한다. OMX는 고정 장비라 `pose_x/y/yaw`가 NULL인 것이 정상이다.

### 5.6 `inventory_lots` — 재고 lot

유통기한과 보관 온도를 가진 재고 lot의 **현재 수량**이다.

> **주의: `available_qty`는 총 보유 수량이다.**
> CHECK 제약이 `reserved_qty <= available_qty`이므로 `reserved_qty`는 `available_qty`의 **부분집합**이다.
> 실제로 새 업무에 할당 가능한 수량은 `available_qty - reserved_qty`다.
> 이름만 보고 `available_qty`를 "예약을 뺀 가용 수량"으로 해석하면 이중 할당이 발생한다.

**사용 규칙**

- 수량 변경은 **반드시** `inventory_moves` INSERT와 같은 트랜잭션에서 한다. 원장 없는 수량 변경은 감사가 불가능하다.
- `state = 'pending_inbound'`인 lot은 아직 물리적으로 도착하지 않았다. 출고 후보에서 제외한다.
- `expiry_date`는 `NOT NULL`이다. 유통기한 개념이 없는 품목이라면 이 테이블 사용 여부를 먼저 재검토한다.
- FEFO 조회는 `idx_lots_product_expiry (product_code, expiry_date)`를 탄다.
- `updated_at`은 `ON UPDATE CURRENT_TIMESTAMP(6)`로 자동 갱신된다. 직접 쓰지 않는다.

### 5.7 `inventory_moves` — 재고 원장

재고 수량이 변한 **모든 근거**를 추가 전용으로 남긴다.

| 컬럼 | 설명 |
| --- | --- |
| `quantity_delta` | 이번 변동량 (음수 가능) |
| `quantity_after` | 변동 후 `inventory_lots.available_qty` |
| `reserved_delta` | 예약 수량 변동량 |
| `reserved_after` | 변동 후 `inventory_lots.reserved_qty` |
| `recorded_by` | 기록 주체 문자열 (`worker_id`, 서비스 이름 등). FK가 아니다 |

**사용 규칙**

- `UPDATE`와 `DELETE`를 절대 하지 않는다. 잘못 기록한 값은 `move_type = 'adjustment'` 보정 행으로 상쇄한다.
- `quantity_after` / `reserved_after`는 같은 트랜잭션에서 갱신한 `inventory_lots`의 값과 **정확히 일치해야 한다.** DB는 두 테이블 간 일치를 검증하지 않는다.
- `recorded_by`는 `workers` FK가 아니다. 사람이 아닌 주체(스케줄러, 어댑터)도 기록하기 때문이다. 사람 주체를 감사하려면 같은 트랜잭션의 `operation_events.actor_worker_id`를 쓴다.
- 예약과 예약 해제는 `move_type`이 각각 `reservation` / `reservation_release`다. 이때 `quantity_delta = 0`이고 `reserved_delta`만 변한다.

### 5.8 `jobs` — 업무 헤더

입고·출고·이동·보충·폐기·복구·비상 대응을 **하나의 업무 단위**로 관리한다. 주문 헤더와 로봇 미션 헤더를 분리하지 않아 운영자가 한 화면에서 상태를 본다.

| 컬럼 | 설명 |
| --- | --- |
| `parent_job_id` | 복구 계보. 원본 job을 가리킨다 |
| `operation_type` | 7종 |
| `priority` + `priority_rank` | `priority_rank`는 **생성 컬럼(STORED)**. 직접 쓰지 않는다 |
| `state` | `queued`, `assigned`, `running`, `held`, `completed`, `failed`, `cancelled` |
| `state_reason_code` / `state_detail` | 현재 상태의 기계 판독 코드와 운영자 설명 |
| `result_code` | terminal 작업의 최종 결과 코드 |
| `revision` | 낙관적 락 버전. 갱신마다 +1 |
| `external_reference` | 외부 요청 멱등 키. 유니크. 내부 job은 NULL |
| `assigned_mobile_id` | 배차된 Pinky |

**사용 규칙**

- **`priority_rank`를 INSERT/UPDATE에 포함하지 않는다.** 생성 컬럼이라 MySQL이 거부한다. `priority` 문자열만 쓰면 `critical=1 … low=4`로 자동 계산된다.
- 배차 조회는 `idx_jobs_dispatch (state, priority_rank, due_at, created_at)`을 탄다. `ORDER BY priority`(문자열)로 정렬하면 알파벳 순이 되어 우선순위가 뒤집힌다.
- 상태 전이는 **반드시 낙관적 락**으로 한다 (8.3 참조).
- 외부 요청은 `external_reference`에 전역 유일 UUID를 넣는다. 재전송으로 유니크 위반이 발생하면 기존 job을 조회해 반환한다.
- 단순 재시도는 새 job을 만들지 않고 `job_steps.retry_count`를 올린다. 회수·복구처럼 **별도 절차**가 필요할 때만 `operation_type = 'recovery'`인 새 job을 만들고 `parent_job_id`로 원본을 가리킨다.

### 5.9 `job_items` — 업무 품목

한 업무에 포함된 상품·lot·수량·검수 상태다. 입고 예정 품목, 출고 요청 품목, 실제 배정된 lot을 같은 구조로 기록한다.

**사용 규칙**

- `lot_id`는 NULL 허용이다. 입고 시점에는 아직 lot이 없고, 출고 계획 시점에는 아직 lot을 배정하지 않았을 수 있다.
- `chk_job_items_qty`가 `completed_qty <= requested_qty`를 강제한다. 초과 수령·초과 출고는 이 테이블로 표현할 수 없다. `verification_state = 'mismatch'`로 표시하고 차이는 `metadata`와 `operation_events`에 남긴다.
- `requested_qty > 0`이 강제된다. 0 수량 품목 행은 만들지 않는다.
- `job_id` FK가 `ON DELETE CASCADE`다. job을 지우면 품목도 사라진다 — 그래서 job은 지우지 않고 `cancelled`로 둔다.

### 5.10 `job_steps` — 실행 단계

업무를 Pinky 이동 → OMX 조작 → 검수 → 인계 순서의 실행 단계로 나눈다. 이 테이블은 **현재 단계 상태의 원본**이고 재시도별 학습 라벨은 `job_step_attempts`가 소유한다.

| 컬럼 | 설명 |
| --- | --- |
| `step_no` | job 내 순번. `(job_id, step_no)`가 유니크 |
| `executor_type` | `mobile` / `arm` / `fms` |
| `action_type` | 13종 |
| `assignment_revision` | 재배정 전의 늦은 결과를 거부하는 fencing 값 |
| `rmf_task_id` | RMF 작업 직접 연결. 전역 유니크 |
| `rmf_phase_id` / `rmf_event_id` | RMF task 내부 진행 단위와 연결 |
| `rmf_status` / `rmf_status_observed_at` | 마지막 RMF 관측 사실과 시각 |
| `final_outcome_reason_code` / `final_method_code` | 단계 최종 결과의 조회용 요약 |
| `policy_name` + `policy_version` | 단계 수준의 마지막 정책 계보 요약 |
| `retry_count` | 단순 재시도 횟수 |
| `input` / `result` | 어댑터 명령 payload와 결과 JSON |
| `started_at` / `completed_at` | 소요 시간 계산 근거 |

**사용 규칙**

- `executor_type` 세 값은 1.2의 계층과 대응한다. `mobile`은 RMF를 거쳐 Pinky Adapter로, `arm`은 OMX Adapter로 직접, `fms`는 로봇 없이 FMS가 수행한다 (검수 확정, 대기 등). `fms` 단계는 `assigned_device_id`를 NULL로 둔다.
- `rmf_task_id`는 `executor_type = 'mobile'` 단계에만 채워진다. `arm` 단계는 RMF를 거치지 않으므로 항상 NULL이다.
- `rmf_task_id`는 유니크다. RMF task를 재제출하면 **새 `job_step`을 만들거나** 기존 행의 값을 갱신한다. 두 단계가 같은 RMF task를 가리킬 수 없다.
- `retry_count` 증가는 같은 물리 명령의 재전송을 의미한다. 명령 내용이 달라지면 새 단계를 만든다.
- 배차 대기 조회는 `idx_job_steps_dispatch (state, executor_type)`을 탄다.
- **VLM/RL이 개입한 시도는 `job_step_attempts`의 policy/model 계보를 반드시 채운다.** `job_steps` 값은 UI 조회를 위한 최종 요약일 뿐이다.
- `started_at` / `completed_at`을 빠짐없이 채운다. 비어 있으면 그 단계는 학습 데이터에서 통째로 빠진다.

### 5.10.1 `job_step_attempts` — 단계 실행 시도 이력

동일 단계에서 Pinky·OMX·FMS가 수행한 **한 번의 실행**을 한 행으로 남긴다. `job_steps`를 재시도할 때 덮어쓰지 않으므로 성공하기 전 실패 과정도 학습 데이터에 보존된다.

| 컬럼군 | 채우는 시점과 역할 |
| --- | --- |
| `attempt_uuid`, `command_uuid`, `attempt_no` | 명령 생성 transaction에서 확정한다 |
| `assignment_revision`, `actor_role`, `actor_device_id` | 현재 배정과 결과 주체를 검증한다 |
| `state` | `created → dispatched → running → reconciling/finished` 진행을 표시한다 |
| `outcome`, `success` | `finished`일 때만 채운다. 모든 성공 기준을 통과해야 `success=1`이다 |
| `method_code`, `selection_reason_code` | 명령 생성 시 정하며 결과를 보고 바꾸지 않는다 |
| `outcome_reason_code`, `failure_domain`, `detail` | 구조화된 실행 사실을 결정적 분류기로 판정해 채운다 |
| `criteria`, `metrics` | 무엇을 기준으로 어떻게 성공·실패했는지 저장한다 |
| `before_observation`, `after_observation`, `evidence_refs` | 학습 관측과 원본 artifact를 연결한다 |
| policy/model 계보, `data_quality_status` | 재현 가능한 학습 export의 필터가 된다 |

`event_uuid`, `command_uuid`, `(job_step_id, assignment_revision, actor_role, attempt_no)`는 각각 유일하다. 명령 생성 시에는 아직 결과 이벤트가 없으므로 `event_uuid`는 NULL이며, terminal 결과를 반영할 때 채운다.
`state='finished'`인 시도는 `started_at`과 `completed_at`이 모두 있어야 하며 `completed_at >= started_at`이어야 한다. 실행 전 취소는 attempt를 finished로 위장하지 않고 별도 취소 감사 이벤트로 남긴다.

### 5.11 `reservations` — 자원 점유

가장 복잡한 테이블이다. 세 가지 모드가 하나의 테이블을 공유한다. 1.2에서 설명했듯 **로봇팔에 대해서는 이 테이블이 함대 계층의 역할을 대신한다.**

| 모드 | 대상 | 잠금 시점 | 용도 |
| --- | --- | --- | --- |
| `exclusive_lock` | `location_id` 또는 `device_id` | `reserved` + `in_use` | 도크·작업장·장비 독점 |
| `bottleneck_lock` | `map_feature_id` | `reserved` + `in_use` | 단일 진입 통로 |
| `time_slot` | `location_id` 또는 `device_id` | `in_use`만 | 시간대 예약 |

**`active_resource_key` 생성 컬럼이 핵심이다.**

```sql
active_resource_key VARCHAR(160) GENERATED ALWAYS AS (
  CASE
    WHEN reservation_mode = 'bottleneck_lock' AND state IN ('reserved','in_use')
      THEN CONCAT('feature:', map_feature_id)
    WHEN reservation_mode = 'exclusive_lock' AND state IN ('reserved','in_use')
      THEN CASE WHEN location_id IS NOT NULL THEN CONCAT('location:', location_id)
                ELSE CONCAT('device:', device_id) END
    WHEN reservation_mode = 'time_slot' AND state = 'in_use'
      THEN CASE WHEN location_id IS NOT NULL THEN CONCAT('location:', location_id)
                ELSE CONCAT('device:', device_id) END
    ELSE NULL
  END
) STORED,
UNIQUE KEY uq_reservations_active_resource (active_resource_key)
```

동작 원리:

- 활성 상태의 예약만 키를 만들고 `released` / `expired` / `cancelled`는 NULL이 된다.
- MySQL 유니크 키는 NULL 중복을 허용하므로 **종료된 예약은 몇 개든 공존**하고 **활성 예약은 자원당 하나만** 존재한다.
- 즉 자원 독점이 애플리케이션 로직이 아니라 **DB 제약으로 보장된다.**

**사용 규칙**

- 예약 해제는 `state`를 `released`로 바꾸는 것이다. 그 순간 키가 NULL이 되어 다음 예약이 들어올 수 있다.
- `time_slot`은 `in_use`일 때만 잠긴다. 따라서 **`planned_start_at`/`planned_end_at` 구간의 겹침은 DB가 막지 못한다.** 겹침 방지는 Gateway가 기준 행 잠금 + 충돌 검사로 수행한다 (8.1).
- `chk_reservations_target`이 모드별 대상 컬럼 조합을 강제한다. `bottleneck_lock`은 `map_feature_id`만, 나머지는 `location_id` **또는** `device_id` 중 정확히 하나만 채운다.
- `chk_reservations_schedule`이 `time_slot`에만 `planned_start_at < planned_end_at`을 강제하고, 다른 모드에서는 두 컬럼이 NULL이어야 한다.
- `expires_at > created_at`이 강제된다. `expires_at`은 확정된 `planned_end_at`에 lease grace period를 더해 계산하고, 예약이 뒤로 이동하면 함께 재계산한다.
- `reservation_id`는 **fencing token**이다. 명령 payload에 포함시키고, Adapter는 더 오래된 token의 늦은 명령을 실행하지 않는다.
- `planned_start_at`과 `entered_at`의 차이가 **대기·혼잡 지표**다. 학습에 쓰인다 (10.2).

### 5.12 `integration_messages` — 메시지 큐

RMF 배차, Pinky/OMX 명령, 장비 응답을 모두 담는 내구성 있는 큐다. 채널이 `rmf` / `pinky` / `omx`로 나뉘어 1.2의 어댑터 경계와 대응한다.

**사용 규칙**

- `(direction, channel, idempotency_key)`가 유니크하다. 재전송 시 중복 실행을 이 키로 막는다. **채널이 키의 일부이므로 같은 문자열이 다른 채널에서 재사용되어도 충돌하지 않는다.**
- 전송 대상 선점은 `FOR UPDATE SKIP LOCKED`로 한다.

```sql
SELECT message_id, payload
FROM integration_messages
WHERE direction = 'outbound'
  AND state = 'pending'
  AND (next_attempt_at IS NULL OR next_attempt_at <= NOW(6))
ORDER BY next_attempt_at, created_at
LIMIT 20
FOR UPDATE SKIP LOCKED;
```

- 전송 **전에** `attempts`, `sent_at`, `next_attempt_at`을 갱신한다. 전송 후에 갱신하면 프로세스가 죽었을 때 무한 재전송한다.
- 전송은 **at-least-once**다. 물리 효과를 한 번만 적용하는 것은 Adapter가 `idempotency_key`를 내구성 있게 중복 제거해서 보장한다.
- 재시도 한도를 넘긴 메시지는 `state = 'dead_letter'`로 두고 사람이 확인한다. 조용히 버리지 않는다.
- 전달 조회는 `idx_messages_delivery (direction, state, next_attempt_at, created_at)`을 탄다. WHERE 절 컬럼 순서를 이 인덱스에 맞춘다.

### 5.13 `incidents` — 진행 중 안전 사고

단순 로그와 다르다. `active` 상태·영향 위치·해제 승인자를 가지며, **FMS가 해당 구역을 차단하고 RMF 재계획 또는 정지를 요청하는 기준**이 된다.

**사용 규칙**

- 사고가 발생하면 `incidents` 행을 만들고, 그 사건의 상세는 `operation_events`에 `incident_id`로 연결한다. 두 테이블의 역할을 바꾸지 않는다.
- 세 명의 작업자를 각각 기록한다: `raised_by` (신고), `acknowledged_by` (확인), `resolved_by` (해제). 안전 해제 책임이 누구에게 있는지가 감사 대상이다.
- `state = 'active'`인 사고가 있는 위치에는 새 업무를 배정하지 않는다. `idx_incidents_active`와 `idx_incidents_location`으로 조회한다.
- `geometry` JSON은 위치가 단일 `location_id`로 표현되지 않는 경우(엎질러진 구역, 연기 확산 범위)에 쓴다.

### 5.14 `operation_events` — 감사 로그

작업·안전·VLM·RL 판단을 시간 순서대로 남기는 **추가 전용** 로그다. 학습에서는 시계열 관측과 negative sample의 출처가 된다 (10절).

| 컬럼 | 설명 |
| --- | --- |
| `event_uuid` | 전역 유니크. 중복 기록 방지 |
| `occurred_at` | 사건 발생 시각 (기록 시각 아님) |
| `category` | 8종 (`vision`, `policy` 포함) |
| `severity` | 5종 (`debug` 포함) |
| `model_name` + `model_version` + `confidence` | VLM/RL 판단 추적 |
| `safety_decision` | `approved` / `denied` / `stopped` / `manual_review` |

**사용 규칙**

- **VLM/RL 제안은 여기에 먼저 기록한 뒤, Safety Supervisor가 승인한 허용 목록 내 복구 행동만 실행한다.** 제안과 승인은 별개의 이벤트다.
- `safety_decision`을 채울 때는 `actor_worker_id`도 함께 채운다. 누가 승인했는지 없는 승인 기록은 감사에 쓸 수 없다.
- `UPDATE` / `DELETE` 금지. 정정은 새 이벤트로 남긴다.
- `confidence`는 0~1이다. 퍼센트(0~100)를 넣으면 CHECK가 거부한다.
- 최신 이벤트 조회는 `idx_events_occurred_at (occurred_at DESC)`를 탄다. MySQL 8의 내림차순 인덱스이므로 `ORDER BY occurred_at DESC`가 정렬 없이 처리된다.
- 이 테이블은 가장 빠르게 커진다. 장기 보관·파티셔닝 정책은 1차 연동 범위 밖이며 별도로 결정한다.

### 5.15 `artifacts` — 학습 원본 참조

이미지·영상·point cloud·ROS bag·Cyclo episode·데이터셋·모델의 **위치와 무결성 정보**만 관리한다. 원본 파일은 NAS/MinIO/S3에 저장한다.

**사용 규칙**

- **파일 바이너리를 DB에 넣지 않는다.** `storage_uri`가 유일한 접근 경로다.
- `storage_uri_hash`는 `UNHEX(SHA2(storage_uri, 256))`의 생성 컬럼이다. `storage_uri`가 `VARCHAR(1024)`라 그대로 인덱싱할 수 없어 해시로 유니크를 건다. **직접 쓰지 않는다.**
- `uq_artifacts_sha_uri (sha256, storage_uri_hash)`가 같은 내용 + 같은 경로의 중복 등록을 막는다. 같은 내용이 다른 경로에 있으면 별도 행이 된다 (의도된 동작 — 복제본 추적).
- `sha256`은 파일 내용의 해시다. 업로드 후 검증과 학습 데이터 무결성 확인에 쓴다.
- 모델 산출물과 데이터셋 스냅샷은 `model_name` + `model_version`을 채운다. `idx_artifacts_model`로 특정 버전의 산출물을 모아본다.
- `job_step_id` / `event_id` / `device_id`를 최대한 채운다. **관측(파일)과 라벨(DB)을 잇는 유일한 다리다** — 10.1 참조.

### 5.16 `location_recovery_profiles` — 복구 Reference Memory

`locations`의 `safe_node` 좌표를 복제하지 않고, 해당 위치를 복구 목표로 사용할 수
있는지와 결과 기반 신뢰도만 관리한다. `location_id`가 UNIQUE이므로 한 location에는
profile이 최대 한 개다.

| 컬럼 | 설명 |
| --- | --- |
| `reference_node_uuid` | FMS와 recovery DB가 공유하는 안정적인 논리 식별자 |
| `location_id` | `locations` FK. 연결 대상은 Gateway가 `safe_node`인지 검증 |
| `map_revision` | profile이 검증된 지도 revision |
| `recovery_roles` | `wait`, `retreat`, `detour`, `rejoin` 중 허용하는 비어 있지 않은 JSON 배열 |
| `availability_status` | `active`, `suspect`, `quarantined`, `retired` |
| `reliability_alpha`, `reliability_beta` | 성공·위험 관측을 누적하는 양수 신뢰도 파라미터 |
| `last_verified_at`, `last_outcome_at` | 검증과 실제 복구 결과의 최신 시각 |
| `reviewed_by_worker_id` | 수동 검토자. `workers` FK |
| `revision` | Gateway의 낙관적 동시성 제어 버전 |

**사용 규칙**

- 좌표의 원본은 항상 `locations`다. profile에 pose 컬럼을 추가하지 않는다.
- 현재 RMF/Nav2 map revision과 일치하고 `active`인 profile만 복구 후보로 조회한다.
- 지도나 `safe_node`가 바뀌면 Gateway가 profile을 `suspect`로 바꾸고
  `operation_events`에 기록한다.
- VLM/RL은 profile을 직접 갱신하지 않는다. 복구 결과를 Gateway에 보고한다.
- `quarantined → active` 전이는 검토자와 감사 이벤트를 남긴 관리자 승인으로만
  수행한다.

### 5.17 `trihouse_recovery.recovery_episodes` — 복구 사건

하나의 복구 trigger가 성공·중단·실패로 끝날 때까지의 범위와 모델 계보를 저장한다.

| 컬럼 | 설명 |
| --- | --- |
| `recovery_episode_uuid` | 복구 사건의 전역 UUID |
| `source_event_uuid` | FMS `operation_events.event_uuid`의 논리 참조 |
| `device_id`, `fms_job_id`, `fms_job_step_id` | 로봇과 업무 문맥 snapshot |
| `map_name`, `map_revision` | 복구 당시 공간 문맥과 version gate |
| `trigger_type` | `blocked`, `person`, `low_visibility`, `localization` |
| `vlm_model_name`, `vlm_model_version` | VLM을 사용한 경우 둘 다 기록하는 계보 |
| `recovery_policy_name`, `recovery_policy_version` | 실행 정책의 필수 계보 |
| `started_at`, `ended_at`, `final_status` | 사건 시간 범위와 최종 결과 |

**사용 규칙**

- `running`이면 `ended_at`은 NULL이다. 종료 상태이면 `ended_at >= started_at`이다.
- rule-only 복구는 VLM 이름과 버전을 모두 NULL로 둔다. 한쪽만 채우지 않는다.
- FMS 식별자는 snapshot이며 cross-database FK가 아니다. Gateway가 기록 전에 존재와
  map revision을 검증한다.
- 같은 record를 재전송할 때 Gateway는 `recovery_episode_uuid`와
  `(recovery_episode_uuid, step_no)` 유니크 키를 idempotency 기준으로 사용해야 한다.

### 5.18 `trihouse_recovery.recovery_steps` — 실제 복구 행동

episode 안에서 실제로 실행한 복구 행동 한 번을 저장한다. 실행되지 않은 VLM 후보,
Safety 승인·거부, Nav2 취소는 이 테이블이 아니라 `operation_events`에 남긴다.

| 컬럼 | 설명 |
| --- | --- |
| `recovery_episode_uuid`, `step_no` | episode FK와 1부터 시작하는 유일한 실행 순서 |
| `reference_node_uuid` | 사용한 Reference Memory의 논리 참조. 없으면 NULL |
| `action_type` | `wait`, `retreat`, `detour`, `rejoin`, `stop` |
| `target_pose` | Nav2에 실제 전달한 목표 pose JSON object |
| `before_state_uri`, `before_state_sha256` | 실행 전 관측 파일의 URI와 무결성 해시 |
| `after_state_uri`, `after_state_sha256` | 실행 후 관측 파일의 URI와 무결성 해시 |
| `reward_components` | progress·clearance·time·intervention 등 보상 구성 JSON object |
| `outcome_class` | `safe`, `boundary`, `critical` |
| `execution_status`, `is_terminal` | 실행 상태와 episode 종료 여부 |
| `started_at`, `completed_at` | 행동 실행 시간 |

**사용 규칙**

- URI와 SHA-256은 항상 둘 다 NULL이거나 둘 다 값이 있어야 한다.
- `queued`·`running` 상태에서는 `completed_at`이 NULL이고 `is_terminal = 0`이다.
- `succeeded`·`failed`·`cancelled` 상태에서는 `completed_at >= started_at`이다.
- episode 삭제 시 step은 `ON DELETE CASCADE`로 함께 삭제된다. 운영 FMS 행은 영향을
  받지 않는다.
- SAC replay 데이터는 완료된 step을 export해 만들며 MySQL 테이블을 replay buffer로
  직접 사용하지 않는다.

---

## 6. 열거값 참조표

모든 열거값은 `VARCHAR` + `CHECK`로 정의되어 있다. 값을 추가하려면 `ALTER TABLE ... DROP CHECK` 후 재생성해야 하므로 12절의 절차를 따른다.

### locations

| 컬럼 | 값 |
| --- | --- |
| `location_type` | `rack`, `slot`, `waypoint`, `staging`, `inbound_dock`, `outbound_dock`, `charger`, `workstation`, `door`, `safe_node` |
| `temperature_zone` | `ambient`, `chilled`, `frozen` (NULL 허용) |
| `state` | `available`, `reserved`, `occupied`, `blocked`, `maintenance` |

### map_features

| 컬럼 | 값 |
| --- | --- |
| `feature_type` | `fiducial`, `static_obstacle`, `bottleneck`, `door`, `no_go_zone` |

### workers

| 컬럼 | 값 |
| --- | --- |
| `role` | `operator`, `supervisor`, `safety_manager`, `administrator` |

### devices / device_states

| 컬럼 | 값 |
| --- | --- |
| `devices.device_type` | `mobile`, `arm` |
| `devices.control_mode` | `automatic`, `manual`, `offline`, `maintenance`, `safety_hold` |
| `device_states.state` | `idle`, `moving`, `docking`, `working`, `waiting`, `charging`, `blocked`, `error`, `estop`, `offline`, `maintenance` |
| `device_states.health` | `ok`, `warning`, `fault`, `safety_hold` |

### inventory_lots / inventory_moves

| 컬럼 | 값 |
| --- | --- |
| `inventory_lots.temperature_zone` | `ambient`, `chilled`, `frozen` (NOT NULL) |
| `inventory_lots.state` | `pending_inbound`, `stored`, `on_hold`, `depleted`, `expired`, `damaged` |
| `inventory_moves.move_type` | `inbound`, `outbound`, `reservation`, `reservation_release`, `adjustment`, `disposal`, `cycle_count` |

### jobs / job_items / job_steps

| 컬럼 | 값 |
| --- | --- |
| `jobs.operation_type` | `inbound`, `outbound`, `relocation`, `replenishment`, `disposal`, `recovery`, `emergency` |
| `jobs.priority` | `critical`(rank 1), `high`(2), `normal`(3), `low`(4) |
| `jobs.state` | `queued`, `assigned`, `running`, `held`, `completed`, `failed`, `cancelled` |
| `job_items.verification_state` | `pending`, `matched`, `mismatch`, `manual_review` |
| `job_steps.executor_type` | `mobile`, `arm`, `fms` |
| `job_steps.action_type` | `navigate`, `dock`, `inspect`, `pick`, `load`, `unload`, `place`, `verify`, `handover`, `wait`, `recover`, `return_home`, `safety_stop` |
| `job_steps.state` | `pending`, `running`, `succeeded`, `failed`, `cancelled` |

> `jobs.state`와 `job_steps.state`는 **서로 다른 집합**이다. job은 `completed`, step은 `succeeded`다. 공용 헬퍼로 두 상태를 함께 처리하지 않는다.

### job_step_attempts

| 컬럼 | 값 |
| --- | --- |
| `actor_role` | `pinky`, `omx`, `fms` |
| `state` | `created`, `dispatched`, `running`, `reconciling`, `finished` |
| `outcome` | `succeeded`, `failed`, `aborted`, `cancelled` (진행 중에는 NULL) |
| `failure_domain` | `none`, `robot`, `perception`, `navigation`, `manipulation`, `safety`, `integration`, `operator`, `unknown` |
| `policy_source` | `rule`, `rmf`, `nav2`, `vlm`, `rl`, `operator`, `hardware` |
| `data_quality_status` | `complete`, `incomplete`, `invalid` |

### reservations

| 컬럼 | 값 |
| --- | --- |
| `reservation_mode` | `exclusive_lock`, `bottleneck_lock`, `time_slot` |
| `state` | `reserved`, `in_use`, `released`, `expired`, `cancelled` |

### integration_messages

| 컬럼 | 값 |
| --- | --- |
| `direction` | `inbound`, `outbound` |
| `channel` | `rmf` (계층 채널), `pinky` (장비), `omx` (장비) |
| `state` | `pending`, `sent`, `acknowledged`, `completed`, `failed`, `dead_letter` |

### incidents / operation_events

| 컬럼 | 값 |
| --- | --- |
| `incidents.incident_type` | `worker_intrusion`, `worker_emergency`, `estop`, `spill`, `blocked_path`, `fire`, `power_cut`, `device_fault` |
| `incidents.severity` | `info`, `warning`, `serious`, `critical` |
| `incidents.state` | `active`, `acknowledged`, `resolved`, `cancelled` |
| `operation_events.severity` | `debug`, `info`, `warning`, `serious`, `critical` |
| `operation_events.category` | `operation`, `inventory`, `rmf`, `omx`, `vision`, `policy`, `safety`, `system` |
| `operation_events.safety_decision` | `approved`, `denied`, `stopped`, `manual_review` (NULL 허용) |

### artifacts

| 컬럼 | 값 |
| --- | --- |
| `artifact_type` | `image`, `video`, `pointcloud`, `rosbag`, `episode`, `dataset`, `model`, `report` |

### location_recovery_profiles

| 컬럼 | 값 |
| --- | --- |
| `recovery_roles` | `wait`, `retreat`, `detour`, `rejoin`의 비어 있지 않은 부분집합 |
| `availability_status` | `active`, `suspect`, `quarantined`, `retired` |

### recovery_episodes

| 컬럼 | 값 |
| --- | --- |
| `trigger_type` | `blocked`, `person`, `low_visibility`, `localization` |
| `final_status` | `running`, `succeeded`, `aborted`, `failed` |

### recovery_steps

| 컬럼 | 값 |
| --- | --- |
| `action_type` | `wait`, `retreat`, `detour`, `rejoin`, `stop` |
| `outcome_class` | `safe`, `boundary`, `critical` |
| `execution_status` | `queued`, `running`, `succeeded`, `failed`, `cancelled` |
| `is_terminal` | `0`(계속), `1`(episode 종료) |

---

## 7. 트랜잭션 경계

다음 여섯 가지는 **각각 하나의 트랜잭션**이다. 중간 상태가 외부에 보이면 안 된다.

| # | 트랜잭션 | 포함 작업 |
| --- | --- | --- |
| 1 | 업무 생성 | `jobs` INSERT + `job_items` INSERT + `job_steps` INSERT + 최초 `operation_events` INSERT |
| 2 | 배차 | `jobs` UPDATE (낙관적 락) + `reservations` INSERT + outbound `integration_messages` INSERT |
| 3 | 재고 변경 | `inventory_lots` UPDATE + `inventory_moves` INSERT + `operation_events` INSERT |
| 4 | 안전 처리 | `incidents` UPDATE + safety `integration_messages` INSERT + `operation_events` INSERT |
| 5 | 수신 처리 | inbound 중복 확인 + `device_states`/`jobs`/`job_steps` UPDATE + `operation_events` INSERT |
| 6 | 복구 생성 | 복구 `jobs` INSERT (`parent_job_id` 설정) + 원본 `jobs` UPDATE |

### 7.1 재시도 정책

Deadlock(`ER_LOCK_DEADLOCK`, 1213)과 lock wait timeout(`ER_LOCK_WAIT_TIMEOUT`, 1205)은 **동시성 경쟁의 정상적인 결과**로 취급한다. 오류 로그로 남기되 경보를 울리지 않고, Gateway가 제한된 횟수(예: 3회, 지수 백오프)로 **트랜잭션 전체를 재시도**한다.

부분 재시도는 금지한다. 롤백된 트랜잭션의 일부만 다시 실행하면 원장이 어긋난다.

### 7.2 트랜잭션 밖으로 내보내야 하는 것

- **외부 HTTP/ROS 호출** — 트랜잭션 안에서 네트워크를 기다리지 않는다. 명령은 `integration_messages`에 넣고 커밋한 뒤 Dispatcher가 보낸다.
- **긴 계산** — 예약 충돌 계산처럼 잠금을 잡고 도는 작업은 최소화한다.
- **학습 데이터 대량 스캔** — 운영 트랜잭션과 같은 커넥션에서 돌리지 않는다 (10.6).

---

## 8. 동시성 제어 규칙

### 8.1 예약 계산의 자원 직렬화

예약 행이 하나도 없는 상태에서도 두 요청이 동시에 같은 시작 시각을 선택할 수 있다. 이를 막기 위해 **대상 자원의 기준 행을 먼저 잠근다.**

| 예약 대상 | 잠글 행 |
| --- | --- |
| 위치 예약 | `SELECT ... FROM locations WHERE location_id = ? FOR UPDATE` |
| 장비 예약 | `SELECT ... FROM devices WHERE device_id = ? FOR UPDATE` |
| 병목 예약 | `SELECT ... FROM map_features WHERE feature_id = ? FOR UPDATE` |

기준 행을 잠근 뒤에 충돌을 검사하고 예약 행을 만든다.

### 8.2 자동 시간 이동 알고리즘

요청 구간 `[requested_start, requested_end)`의 **duration을 보존**한다. 같은 자원의 `reserved` / `in_use` 예약과 겹치면, 충돌한 예약의 `planned_end_at`을 새 시작 시각으로 삼고 다시 검사한다. 충돌이 없어지는 가장 이른 시각에 확정한다.

```text
기존 예약: 10:00-10:20, 10:25-10:40
요청 예약: 10:10-10:30 (20분)
1차 이동: 10:20-10:40 -> 두 번째 예약과 충돌
2차 이동: 10:40-11:00 -> 확정
```

만족해야 할 조건:

- 종료 시각과 다음 시작 시각이 같은 **반개방 구간**은 겹치지 않는다 (`10:20` 종료와 `10:20` 시작은 충돌 아님).
- duration은 이동 전후 동일하다.
- `expires_at`은 확정된 `planned_end_at` + lease grace period다. 예약이 뒤로 이동하면 함께 재계산한다.
- 업무 `due_at`을 넘기는 후보도 예약할 수 있으나, Gateway가 지연 이벤트를 남기고 재계획 정책을 실행한다.
- 병목 `exclusive_lock`은 시간 이동 대상이 아니다. 현재 활성 잠금이 해제된 뒤 다시 취득한다.
- `time_slot`을 `in_use`로 전환할 때 `uq_reservations_active_resource` 충돌이 나면 **예약 계산을 처음부터 다시 수행한다.**

### 8.3 낙관적 락으로 업무 상태 전이

UI 취소, RMF 완료, Safety 정지가 동시에 같은 job을 건드릴 수 있다. 현재 `revision`과 허용된 이전 `state`를 조건에 넣는다.

```sql
UPDATE jobs
SET state = 'running',
    revision = revision + 1,
    started_at = NOW(6)
WHERE job_id = ?
  AND revision = ?               -- 읽어온 시점의 revision
  AND state IN ('assigned');     -- 허용된 이전 상태
```

영향 행이 **0행이면 충돌이다.** 최신 job을 다시 읽어 API에 충돌 응답(409)을 반환한다. 조용히 성공으로 처리하지 않는다.

### 8.4 큐 선점

메시지 Dispatcher는 `FOR UPDATE SKIP LOCKED`로 대상을 선점한다 (5.12). 여러 워커가 동시에 돌아도 같은 메시지를 두 번 잡지 않는다.

### 8.5 Fencing token

`reservation_id`를 명령 payload에 포함한다. 네트워크 지연으로 오래된 명령이 뒤늦게 도착했을 때, Adapter는 자신이 아는 최신 token보다 작은 token의 명령을 **실행하지 않는다.** 예약이 이미 만료·해제되었는데 옛 명령이 로봇을 움직이는 것을 막는다.

---

## 9. 조회 패턴과 인덱스

### 9.1 배차 대기 업무

```sql
SELECT job_id, job_code, operation_type, priority, due_at
FROM jobs
WHERE state = 'pending'
ORDER BY priority_rank, due_at, created_at
LIMIT 50;
```

`idx_jobs_dispatch (state, priority_rank, due_at, created_at)` 사용.

### 9.2 FEFO 출고 후보 lot

```sql
SELECT lot_id, lot_code, available_qty, reserved_qty, expiry_date
FROM inventory_lots
WHERE product_code = ?
  AND state = 'stored'
  AND available_qty - reserved_qty > 0
ORDER BY expiry_date, lot_id
LIMIT 20;
```

`idx_lots_product_expiry (product_code, expiry_date)` 사용. `available_qty - reserved_qty`가 실제 할당 가능 수량이다 (5.6 주의).

### 9.3 만료 예정 예약

```sql
SELECT reservation_id, job_id, expires_at
FROM reservations
WHERE state IN ('reserved', 'in_use')
  AND expires_at <= NOW(6)
ORDER BY expires_at
LIMIT 100;
```

`idx_reservations_expiry (state, expires_at)` 사용.

### 9.4 특정 자원의 예약 일정

```sql
SELECT reservation_id, planned_start_at, planned_end_at, state
FROM reservations
WHERE location_id = ?
  AND state IN ('reserved', 'in_use')
  AND planned_end_at > ?
  AND planned_start_at < ?
ORDER BY planned_start_at;
```

`idx_reservations_location_schedule (location_id, state, planned_start_at, planned_end_at)` 사용.

### 9.5 최신 운영 이벤트

```sql
SELECT event_id, occurred_at, severity, category, event_type, message
FROM operation_events
ORDER BY occurred_at DESC
LIMIT 100;
```

`idx_events_occurred_at (occurred_at DESC)` 사용. job/device/incident 기준 조회는 각각 `idx_events_job_at`, `idx_events_device_at`, `idx_events_incident_at`을 탄다.

### 9.6 진행 중 안전 사고

```sql
SELECT incident_id, incident_code, incident_type, severity, location_id, raised_at
FROM incidents
WHERE state IN ('active', 'acknowledged')
ORDER BY raised_at;
```

`idx_incidents_active (state, severity, raised_at)` 사용. `severity`는 문자열이므로 심각도 순 정렬이 필요하면 Gateway에서 매핑한다.

### 9.7 관제 화면 장비 상태

```sql
SELECT d.device_id, d.name, d.device_type, d.control_mode,
       s.state, s.health, s.battery_pct, s.pose_x, s.pose_y, s.observed_at
FROM devices d
LEFT JOIN device_states s ON s.device_id = d.device_id
WHERE d.active = 1
ORDER BY d.device_type, d.device_id;
```

`LEFT JOIN`을 쓴다. 등록 직후 아직 상태 보고가 없는 장비도 화면에 나와야 한다.

---

## 10. VLM/RL 학습 데이터 활용

DB는 주행 경로를 **결정하지 않지만**, 경로 재추정 모델을 학습시킬 **라벨과 보상의 출처**다. 이 절은 그 데이터를 어떻게 구조화하고 꺼내는지 정리한다.

### 10.1 역할 분담: 관측은 파일, 라벨은 DB

| 구분 | 저장 위치 | 예시 |
| --- | --- | --- |
| **관측 (observation)** | NAS/MinIO/S3 원본 파일, `artifacts` 행이 가리킴 | rosbag(궤적·TF·스캔), point cloud, 카메라 영상, Cyclo episode |
| **라벨 / 보상 (label, reward)** | MySQL | 성공·실패, 소요 시간, 재시도 횟수, 대기 시간, 안전 사건 발생 여부 |
| **계보 (lineage)** | MySQL | 어느 모델 버전이 판단했고, 누가 승인했고, 어떤 스냅샷으로 학습했는지 |

**둘을 잇는 다리는 `artifacts.job_step_id` / `artifacts.event_id` / `artifacts.device_id`다.** 이 컬럼을 비워 두면 그 파일은 라벨 없는 데이터가 되어 학습에 쓸 수 없다. 수집 파이프라인의 최우선 규칙이다.

```text
job_steps (현재 단계 상태와 최종 요약)
    │  job_step_id
    v
job_step_attempts (시도별 method/reason/criteria/metrics/계보)
    │  job_step_id / event_uuid
    v
artifacts (관측: rosbag / pointcloud / episode)  ──> storage_uri + sha256
    ^  event_id
    │
operation_events (시계열 관측, 모델 판단, safety_decision)
```

### 10.2 DB에서 바로 뽑히는 학습 신호

| 신호 | 출처 | 계산 |
| --- | --- | --- |
| 시도 성공/실패/중단/취소 | `job_step_attempts.outcome`, `success` | terminal 구조화 라벨 |
| 성공·실패 판단 근거 | `criteria`, `metrics`, `outcome_reason_code` | 기준별 관측과 고정 코드 |
| 실행 방법과 선택 이유 | `method_code`, `selection_reason_code` | 명령 생성 시 확정 |
| 실패 원인 분류 | `failure_domain`, `outcome_reason_code`, `detail` | 영역·코드·설명 분리 |
| 단계 소요 시간 | `job_step_attempts.started_at`, `completed_at` | 시도별 차이 |
| 재시도 비용 | `attempt_no` | 동일 단계·revision·actor 내 순번 |
| **대기·혼잡** | `reservations.planned_start_at` vs `entered_at` | 차이 = 실제 대기 시간 |
| **점유 시간** | `reservations.entered_at` vs `exited_at` | 차이 |
| 납기 지연 | `jobs.due_at` vs `completed_at` | 차이 |
| 안전 페널티 | `incidents`, `job_steps.action_type = 'safety_stop'` | 발생 횟수 |
| 모델 신뢰도 | `operation_events.confidence` | 0~1 |
| **승인/거부 (negative sample)** | `operation_events.safety_decision` | `approved` / `denied` / `stopped` |
| 물류 결과 | `inventory_moves` | 실제 이동 수량 |

`safety_decision = 'denied'`인 이벤트는 **모델이 제안했지만 Safety Supervisor가 거부한 행동**이다. 이것이 negative sample의 출처다. DB에 "실행된 행동"만 남으면 학습 데이터가 생존 편향에 빠지는데, 이 구조는 거부된 제안도 남기므로 편향을 줄일 수 있다.

### 10.3 정책 버전별 성과 집계

`job_step_attempts.policy_name` / `policy_version`이 채워져 있어야 성립한다.

```sql
SELECT policy_name,
       policy_version,
       COUNT(*)                                   AS attempts,
       SUM(outcome = 'succeeded')                 AS succeeded,
       SUM(outcome = 'failed')                    AS failed,
       SUM(success = 1) / COUNT(*)                AS success_rate,
       AVG(TIMESTAMPDIFF(MICROSECOND, started_at, completed_at) / 1e6) AS avg_seconds
FROM job_step_attempts
WHERE policy_name IS NOT NULL
  AND state = 'finished'
  AND completed_at >= ? AND completed_at < ?
GROUP BY policy_name, policy_version
ORDER BY policy_name, policy_version;
```

구간별 주행 성과 (경로 재추정 학습의 1차 지표):

```sql
SELECT j.source_location_id,
       s.target_location_id,
       s.assigned_device_id,
       COUNT(*)                                    AS runs,
       AVG(TIMESTAMPDIFF(MICROSECOND, s.started_at, s.completed_at) / 1e6) AS avg_seconds,
       STDDEV_SAMP(TIMESTAMPDIFF(MICROSECOND, s.started_at, s.completed_at) / 1e6) AS sd_seconds,
       SUM(s.retry_count)                          AS retries
FROM job_steps s
JOIN jobs j ON j.job_id = s.job_id
WHERE s.action_type = 'navigate'
  AND s.state = 'succeeded'
  AND s.started_at IS NOT NULL AND s.completed_at IS NOT NULL
GROUP BY j.source_location_id, s.target_location_id, s.assigned_device_id
HAVING runs >= 10;
```

병목·대기 혼잡도:

```sql
SELECT COALESCE(CONCAT('location:', location_id), CONCAT('feature:', map_feature_id)) AS resource,
       COUNT(*) AS uses,
       AVG(TIMESTAMPDIFF(MICROSECOND, planned_start_at, entered_at) / 1e6) AS avg_wait_seconds,
       AVG(TIMESTAMPDIFF(MICROSECOND, entered_at, exited_at) / 1e6)        AS avg_hold_seconds
FROM reservations
WHERE entered_at IS NOT NULL
  AND state IN ('released', 'expired')
GROUP BY resource;
```

실패 에피소드와 원본 파일 조인 (학습 배치의 입력):

```sql
SELECT s.job_step_id, s.action_type, s.failure_reason, s.policy_name, s.policy_version,
       a.artifact_type, a.storage_uri, a.sha256
FROM job_steps s
JOIN artifacts a ON a.job_step_id = s.job_step_id
WHERE s.state = 'failed'
  AND a.artifact_type IN ('rosbag', 'episode', 'video', 'pointcloud')
  AND s.completed_at >= ? AND s.completed_at < ?;
```

### 10.4 파생 지표는 `job_step_attempts.metrics`에 넣는다

DB에는 주행 **궤적 자체**가 없다. 궤적은 rosbag에 있다. 하지만 매번 rosbag을 파싱해 요약 지표를 다시 뽑는 것은 비효율적이다.

어댑터는 단계 결과를 보고할 때 `job_step_attempts.metrics` JSON에 시도별 요약 지표를 넣는다. 단계의 최종 호환 payload가 필요하면 `job_steps.result`에도 요약할 수 있지만 학습 원본은 attempt 행이다.

```json
{
  "traveled_distance_m": 24.7,
  "mean_speed_mps": 0.42,
  "stop_count": 3,
  "replan_count": 1,
  "min_obstacle_clearance_m": 0.31,
  "path_artifact_id": 10245
}
```

키 이름은 Gateway 타입 정의에 고정하고, 값이 없으면 키를 생략한다 (NULL을 넣지 않는다). 이 규약이 있어야 10.3의 집계 쿼리에 거리·정지 횟수를 추가할 수 있다.

지표가 반복적으로 쓰이고 필터 조건이 되기 시작하면, 그때 생성 컬럼 + 인덱스로 승격하는 것을 검토한다 (12절).

### 10.5 학습 데이터셋 스냅샷과 재현성

학습에 쓴 데이터는 **`artifacts` 행으로 고정한다.** 그러지 않으면 "이 모델을 어떤 데이터로 학습했는가"에 답할 수 없다.

```sql
INSERT INTO artifacts
  (artifact_type, storage_uri, sha256, mime_type, byte_size,
   model_name, model_version, metadata, captured_at)
VALUES
  ('dataset',
   's3://trihouse-ml/datasets/nav-2026-08-03.parquet',
   ?, 'application/vnd.apache.parquet', ?,
   NULL, NULL,
   JSON_OBJECT(
     'source_tables', JSON_ARRAY('job_steps', 'reservations', 'operation_events'),
     'time_range_start', '2026-05-01T00:00:00+09:00',
     'time_range_end',   '2026-08-01T00:00:00+09:00',
     'filters', JSON_OBJECT('action_type', 'navigate', 'state', 'succeeded'),
     'row_count', ?,
     'image_digest', ?,          -- vision 컨테이너 이미지 다이제스트
     'schema_git_commit', ?
   ),
   NOW(6));
```

학습된 모델도 같은 방식으로 남긴다 (`artifact_type = 'model'`, `model_name` + `model_version` 필수). 이후 그 버전이 현장에 투입되면 `job_steps.policy_version`에 같은 문자열이 들어가고, 10.3의 집계로 성과가 다시 측정된다. **계보가 닫힌 고리를 이룬다.**

```text
artifacts(dataset) ──학습──> artifacts(model, model_version = "nav-rl-v3")
                                        │
                                        v 현장 투입
                              job_steps.policy_version = "nav-rl-v3"
                                        │
                                        v 성과 집계 (10.3)
                                다음 데이터셋 스냅샷
```

컨테이너 환경에서는 `metadata`에 **이미지 다이제스트**를 함께 남긴다. `unified_env.yml`이 `git+https://...`와 `-f https://data.pyg.org/...` 같은 가변 소스를 참조하므로, 같은 yml로 빌드해도 시점에 따라 결과가 달라질 수 있다. 다이제스트가 실제 재현의 기준이다.

### 10.6 학습 데이터 추출 시 지켜야 할 것

- **읽기 부하를 운영과 격리한다.** 대량 스캔은 Gateway의 export 배치로, 운영 시간대를 피해 돌린다. 같은 커넥션에서 운영 트랜잭션과 섞지 않는다.
- **`operation_events`는 전체 스캔하지 않는다.** 가장 빠르게 커지는 테이블이다. 반드시 `occurred_at` 범위와 `category`로 좁힌다.
- **자기 생성 데이터 편향에 주의한다.** 모델 v3가 만든 기록으로 v4를 학습하면 v3의 실수를 강화한다. `policy_version`으로 반드시 구분하고, 필요하면 특정 버전을 제외한다.
- **시간대를 맞춘다.** 2.3 참조. naive datetime을 쓰면 시간축이 9시간 어긋난다.
- **`sha256`으로 원본 무결성을 확인한 뒤 학습한다.** URI만 믿고 읽으면 파일이 교체되었는지 알 수 없다.
- **모델의 출력은 여전히 제안이다.** 재추정된 경로도 RMF와 Safety Supervisor를 거친다. `vision` 컨테이너가 DB에 명령을 쓰지 않는다 (1.1, 2.2).

### 10.7 VLM/RL 복구 Memory 데이터 경계

v4의 `trihouse_fms`는 입고·출고·재고·예약의 운영 원장이며 검증된 복구 기준점의
Reference Memory를 함께 관리한다. 실제 복구 경험은 별도 `trihouse_recovery`에
Episodic Memory로 저장한다. 후보 rollout과 학습 중 replay buffer 때문에 운영
원장의 테이블 역할을 바꾸지 않는다.

```text
RTX 4060 / MySQL 8.4
├─ trihouse_fms
│  └─ locations + location_recovery_profiles
│     = 기본 주행 기준점과 Reference Memory
└─ trihouse_recovery
   └─ recovery_episodes + recovery_steps
      = 실제 복구 경험과 결과인 Episodic Memory

RTX 5080 RAM/NVMe
├─ SAC replay buffer와 TGRPO 임시 trajectory group
└─ Gateway ACK 전까지 보존하는 미전송 record queue
```

- `locations`는 좌표와 현재 운영 점유 상태의 원본이다.
- `location_recovery_profiles`는 일부 `safe_node` location이 복구 목표로
  현재 사용 가능한지와 신뢰도만 기록한다. 좌표를 복제하지 않는다.
- `recovery_steps`에는 실제로 실행된 복구 행동만 남긴다. VLM이 제안했지만
  실행되지 않은 후보와 Safety의 승인·거부는 기존 `operation_events`에 남긴다.
- 5080은 record를 로컬 queue에 먼저 기록하고, Gateway ACK까지 같은
  `message_id`로 재전송한다. Gateway는 idempotent하게 한 번만 반영한다.
- SAC replay buffer는 `recovery_steps` export로 구성하는 학습용 임시 메모리다.
  학습이 끝난 buffer 자체는 운영 원장으로 보존하지 않는다.
- `safe_buffer`, `critical_buffer`, `candidate_rollouts`, `reference_edges`,
  `policy_bundles`, `recovery_assessments` 같은 별도 DB 테이블을 만들지 않는다.
- VLM/RL은 MySQL 계정을 갖거나 어떤 DB에도 직접 쓰지 않는다. Gateway API와
  export artifact만 사용한다.
- 복구 행동과 local safety는 DB 왕복을 기다리지 않는다. 즉시 안전 판단은 로봇의
  로컬 계층에서 수행하고, 결과 기록은 비동기로 Gateway에 전달한다.

---

## 11. 금지 사항과 안티패턴

### 11.1 절대 하지 않는 것

| 금지 | 이유 |
| --- | --- |
| `gateway` 외의 컨테이너를 `fms_internal` 네트워크에 넣기 | 쓰기 주체가 여러 개가 되면 트랜잭션 경계가 무너진다 (2.2) |
| `web` / `vision` 이미지에 MySQL 드라이버 포함 | 네트워크로 막혀 있어도 의도를 흐린다 |
| 컨테이너에 `TZ` 미설정 | 로그와 DB 시각이 9시간 어긋난다 (2.3) |
| `inventory_moves` / `operation_events` UPDATE·DELETE | 추가 전용 원장이다. 감사와 학습 근거가 사라진다 |
| `inventory_lots` 수량 변경 시 원장 미기록 | 수량과 근거가 어긋난다 |
| `priority_rank`, `active_resource_key`, `storage_uri_hash` 직접 쓰기 | 생성 컬럼이다. MySQL이 거부한다 |
| `revision` 조건 없는 `jobs` 상태 갱신 | 경쟁 갱신이 조용히 덮어써진다 |
| 세션 시간대 미설정 커넥션 사용 | 서버 설정이 있어도 드라이버가 UTC로 되돌릴 수 있다 |
| `SELECT *` | 컬럼 추가 시 애플리케이션이 깨지고 커버링 인덱스를 못 쓴다 |
| 파일 바이너리를 DB에 저장 | `artifacts`는 위치·해시만 관리한다 |
| `artifacts`에 `job_step_id`/`event_id` 없이 원본 등록 | 라벨과 연결되지 않아 학습에 못 쓴다 |
| `arm` 단계에 `rmf_task_id` 채우기 | OMX는 RMF를 거치지 않는다 (1.2) |
| `ENUM` 타입 추가 | 값 추가 시 테이블 재작성이 발생한다 |
| 트랜잭션 안에서 외부 네트워크 호출 | 잠금을 붙잡은 채 대기한다 |

### 11.2 흔한 실수

**`available_qty`를 가용 수량으로 오해**
`available_qty`는 총 보유 수량이고 `reserved_qty`가 그 부분집합이다. 할당 가능 수량은 `available_qty - reserved_qty`다.

**`jobs.state`와 `job_steps.state`를 같은 집합으로 취급**
job은 `completed`, step은 `succeeded`다. 공용 상태 매핑 함수를 만들면 조용히 틀린다.

**`omx_fleet`을 RMF fleet으로 취급**
`devices.fleet_name`에 두 값이 다 들어 있지만 `omx_fleet`은 논리적 그룹 라벨일 뿐 RMF와 무관하다. RMF에 넘길 때는 `device_type = 'mobile'`로 걸러낸다.

**`REPLACE INTO device_states`**
`REPLACE`는 DELETE + INSERT다. FK `ON DELETE` 동작이 함께 발동한다. `INSERT ... ON DUPLICATE KEY UPDATE`를 쓴다.

**늦게 도착한 상태 메시지로 최신 상태 덮어쓰기**
`device_states` 갱신 시 `observed_at` 비교 조건을 넣고, `observed_at` 자체는 절 마지막에 갱신한다 (5.5).

**`time_slot` 겹침을 DB가 막아줄 거라 기대**
`time_slot`은 `in_use`일 때만 유니크 키가 걸린다. 계획 구간의 겹침은 Gateway가 기준 행 잠금으로 막아야 한다.

**낙관적 락 0행을 성공으로 처리**
`UPDATE` 영향 행이 0이면 충돌이다. 반드시 재조회 후 충돌 응답을 반환한다.

**`confidence`에 퍼센트 넣기**
`confidence`는 0~1, `progress`도 0~1, `battery_pct`만 0~100이다.

**지도 개정 시 `map_features` 행 덮어쓰기**
`map_revision`을 올려 새 행을 추가하고 이전 행은 `active = 0`으로 둔다. 과거 사건의 위치 근거를 보존해야 한다.

**`policy_version` 없이 모델을 투입**
성과를 버전별로 나눌 수 없게 되어, 그 기간의 데이터는 학습 계보에서 사실상 버려진다.

**`started_at`/`completed_at`을 비워둔 채 단계 종료**
소요 시간을 계산할 수 없어 해당 단계가 학습 데이터에서 통째로 빠진다.

---

## 12. 스키마 변경 절차

### 12.1 원칙

- **현재 FMS 17개 운영 도메인 테이블을 유지한다.** 입고·출고·재고·예약·관제의
  새 요구는 먼저 기존 테이블의 컬럼·JSON·열거값으로 표현할 수 있는지 검토한다.
  정상 작업의 세밀한 실행 이력은 `job_step_attempts`, 원본 파일은 `artifacts`로 해결한다 (10.4).
- VLM/RL 복구 데이터는 v4의 세 테이블로 역할을 분리한다.
  `location_recovery_profiles`는 Reference Memory이고,
  `recovery_episodes`와 `recovery_steps`는 Episodic Memory다. replay buffer는
  이 데이터를 export해 만든 임시 학습 메모리이며 DB 테이블로 추가하지 않는다.
- 기준 스키마 파일은 [db/schema_mysql.sql](../../db/schema_mysql.sql) 하나다.
- [control_system/db/schema.sql](../../control_system/db/schema.sql)은 기존 SQLite v2에 대응하는 **별도 스키마**다. 새 연동에 사용하지 않는다.
- [control_system/db/migrate_sqlite_to_mysql.py](../../control_system/db/migrate_sqlite_to_mysql.py)는 `robosapiens` 스키마 전용이다. `trihouse_fms`에 실행하지 않는다.

### 12.2 열거값 추가

`CHECK` 제약은 이름으로 삭제 후 재생성한다.

```sql
ALTER TABLE jobs DROP CHECK chk_jobs_state;
ALTER TABLE jobs ADD CONSTRAINT chk_jobs_state CHECK (state IN
  ('pending','planned','running','waiting','blocked','completed','failed',
   'cancelled','safety_hold','new_value'));
```

기존 값을 **제거**하는 변경은 데이터 마이그레이션이 먼저다. 남아 있는 행이 새 CHECK를 위반하면 `ALTER`가 실패한다.

### 12.3 컬럼 추가

- 새 컬럼은 `NULL` 허용 또는 `DEFAULT`를 가져야 한다. 기존 행이 있는 상태에서 `NOT NULL` + 기본값 없음은 실패한다.
- 대용량 테이블(`operation_events`, `inventory_moves`, `integration_messages`)은 `ALGORITHM=INPLACE, LOCK=NONE`이 가능한지 먼저 확인한다.

### 12.4 변경 시 함께 해야 할 일

| 대상 | 내용 |
| --- | --- |
| [db/schema_mysql.sql](../../db/schema_mysql.sql) | DDL 갱신 + 주석 갱신 |
| `db/migrations/` | 이미 데이터가 있는 DB에 적용할 비파괴 변경 SQL 추가 |
| [db/seed_dev.sql](../../db/seed_dev.sql) | 개발 시드 데이터 정합성 확인 |
| [data_dictionary.xlsx](data_dictionary.xlsx) | 컬럼·테이블 영문 설명 동기화 |
| [schema_diagram.drawio](schema_diagram.drawio) | 영문 물리명과 영문 논리명 동기화 |
| 이 문서 | 열거값 표, 테이블 가이드, 안티패턴 갱신 |
| [Recovery Memory](../architecture/recovery_memory.md) | Memory 의미가 바뀌면 함께 갱신 |
| `compose.db.yaml` / `compose.db_test.yaml` | 초기화 스크립트는 **최초 볼륨 생성 시에만** 실행된다 |
| Gateway 타입 정의 | JSON 키·열거값 타입 동기화 |
| 학습 파이프라인 | 10절의 쿼리와 export 스키마 영향 확인 |

> `docker-entrypoint-initdb.d` 마운트는 **데이터 볼륨이 비어 있을 때만** 동작한다. 이미 데이터가 있는 개발 환경에 스키마 변경을 반영하려면 migration을 실행한다. `compose.db_test.yaml`은 `/var/lib/mysql`을 tmpfs로 두어 매 기동마다 스키마가 새로 적용된다.

테이블·컬럼 설명을 바꿀 때는 물리 이름과 코드 값을 변경하지 않는다. 웹 표시 호환성을
위해 설명은 ASCII 영문으로 작성한 뒤 다음 명령으로 SQL, migration, XLSX, draw.io의
일치 여부를 확인한다.

```bash
python3 db/tools/sync_schema_comments.py --check
```

### 12.5 테스트

스키마를 건드리면 최소한 다음을 확인한다.

- **스키마 테스트** — MySQL 8에서 DDL이 적용되고 CHECK/unique/FK가 의도대로 거부하는가
- **예약 단위 테스트** — 단일 충돌, 연속 충돌, 경계가 맞닿은 구간, 동시 요청, due/expiry 초과
- **재고 통합 테스트** — 정상 조정, 예약 초과 거부, 롤백 시 원장 미기록
- **메시지 통합 테스트** — 동일 key 재전송, timeout 재전송, ACK 후 재전송 금지
- **API 테스트** — revision 충돌, 외부 참조 중복, Seoul offset 입출력

```bash
set -euo pipefail
cleanup_test_db() {
  docker compose -f compose.db_test.yaml down
}
trap cleanup_test_db EXIT
docker compose -f compose.db_test.yaml up -d --wait mysql_test
test "$(docker compose -f compose.db_test.yaml port mysql_test 3306)" = 127.0.0.1:3307
FMS_DB_HOST=127.0.0.1 \
FMS_DB_PORT=3307 \
FMS_DB_ADMIN_USER=root \
FMS_DB_ADMIN_PASSWORD=test_root_password \
FMS_DB_USER=fms_gateway \
FMS_DB_PASSWORD=test_gateway_password \
FMS_DB_DATABASE=trihouse_fms \
PYTHONPATH= \
python -m pytest -c fms_gateway/pytest.ini fms_gateway/tests -v
trap - EXIT
cleanup_test_db
```

테스트 fixture는 `trihouse_fms`를 삭제하고 재생성하므로 이 명령의 포트를 개발 DB
`3306`으로 바꾸면 안 된다.

---

## 13. 리뷰 체크리스트

DB를 건드리는 PR을 리뷰할 때 확인한다.

**컨테이너 경계**

- [ ] `fms_internal` 네트워크에 `gateway`와 `mysql`만 있는가
- [ ] `web` / `vision` 이미지에 DB 드라이버가 없는가
- [ ] 모든 서비스에 `TZ: Asia/Seoul`이 설정되어 있는가
- [ ] MySQL 포트가 불필요하게 외부에 노출되지 않았는가

**쓰기 경로**

- [ ] 쓰기가 FMS Gateway 안에서만 일어나는가
- [ ] 7절의 트랜잭션 경계 중 하나에 정확히 대응하는가
- [ ] 트랜잭션 안에서 외부 네트워크 호출을 하지 않는가
- [ ] Deadlock / lock timeout에 대한 전체 재시도가 있는가

**재고**

- [ ] `inventory_lots` 변경이 `inventory_moves` INSERT와 같은 트랜잭션인가
- [ ] `quantity_after` / `reserved_after`가 갱신된 lot 값과 일치하는가
- [ ] 할당 가능 수량을 `available_qty - reserved_qty`로 계산했는가
- [ ] `operation_events`에도 기록했는가

**업무 상태**

- [ ] `jobs` 갱신에 `revision` 조건이 있는가
- [ ] 영향 행 0을 충돌로 처리하는가
- [ ] `jobs.state`와 `job_steps.state`를 혼동하지 않았는가
- [ ] `started_at` / `completed_at`을 빠짐없이 채우는가

**예약**

- [ ] 기준 행(`locations` / `devices` / `map_features`)을 `FOR UPDATE`로 먼저 잠갔는가
- [ ] `uq_reservations_active_resource` 충돌 시 재계산하는가
- [ ] `expires_at`을 `planned_end_at` 이동에 맞춰 재계산하는가
- [ ] `reservation_id`를 fencing token으로 명령에 실었는가

**어댑터 경계**

- [ ] `channel`이 계층과 맞는가 (`rmf` = 함대, `pinky`/`omx` = 장비)
- [ ] `rmf_task_id`가 `executor_type = 'mobile'` 단계에만 채워지는가
- [ ] RMF에 fleet 이름을 넘길 때 `device_type = 'mobile'`로 걸렀는가
- [ ] `idempotency_key`가 채널 안에서 유일한가
- [ ] `FOR UPDATE SKIP LOCKED`로 선점하는가
- [ ] 전송 **전에** `attempts` / `next_attempt_at`을 갱신하는가
- [ ] 한도 초과 시 `dead_letter`로 남기는가

**안전·감사**

- [ ] 안전 관련 변경에 `operation_events`가 남는가
- [ ] `safety_decision`에 `actor_worker_id`가 함께 기록되는가
- [ ] VLM/RL 제안이 승인 전에 실행되지 않는가

**학습 데이터**

- [ ] 모델이 개입한 단계에 `policy_name` / `policy_version`이 있는가
- [ ] `artifacts`에 `job_step_id` 또는 `event_id`가 연결되어 있는가
- [ ] 데이터셋·모델 스냅샷을 `artifacts` 행으로 남겼는가 (이미지 다이제스트 포함)
- [ ] 대량 조회가 Gateway export 경로에서 실행되는가

**복구 Memory**

- [ ] `location_recovery_profiles.map_revision`이 현재 RMF/Nav2 지도와 일치하는가
- [ ] `recovery_steps`에 실제 실행한 행동만 기록했는가
- [ ] 실행하지 않은 후보와 Safety 결정은 `operation_events`에 기록했는가
- [ ] VLM 이름·버전과 복구 정책 이름·버전의 계보가 완전한가
- [ ] 관측 파일 URI와 SHA-256이 항상 한 쌍으로 기록되는가
- [ ] `trihouse_fms`와 `trihouse_recovery` 사이에 FK를 추가하지 않았는가
- [ ] 5080이 MySQL에 직접 접속하지 않고 Gateway API를 사용하는가

**쿼리**

- [ ] `SELECT *`를 쓰지 않았는가
- [ ] WHERE / ORDER BY가 9절의 인덱스 순서와 맞는가
- [ ] 생성 컬럼을 직접 쓰지 않았는가
