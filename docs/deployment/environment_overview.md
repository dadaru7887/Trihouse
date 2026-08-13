# Robosapiens 환경 구성

## 상태

- 기준일: 2026-08-10
- 현재 PC: Docker·Compose 설치, 개발·테스트 DB 작성 및 로컬 실행 검증 완료
- RTX 4060·5080: 역할별 Compose 작성·정적 검증 완료, 실제 서버 검증 예정
- 보호 경로: `pinky_pro/**`, `control_system/**`는 읽기·실행만 허용

## 호스트별 역할

| 호스트 | 책임 | 데이터 소유 |
|---|---|---|
| 현재 PC | Compose 작성, 정적 테스트, 회의 시연 준비 | 개발용 로컬 볼륨만 |
| RTX 4060 | 관제, Task Manager, MySQL, QR, 영상 저장·중계 | `trihouse_fms`, `trihouse_recovery`, 영상 artifact |
| RTX 5080 | YOLO, VLM, RL 학습·복구 정책 | GPU replay buffer, NVMe cache, 미전송 queue |

MySQL 8.4 서버는 4060 한 곳에 둔다. 5080은 DB 자격증명을 갖지 않고 Gateway
API와 export artifact를 사용한다. 네트워크가 끊기면 고유 `message_id`가 있는
recovery record를 로컬 queue에 보관하고 ACK까지 재전송한다.

## 역할별 Compose

| 파일 | 역할 | 현재 상태 |
|---|---|---|
| `compose.db.yaml` | 보존되는 개발 MySQL | 작성·정적 검증·로컬 실행 검증 완료 (`schema_mysql.sql` 계약 기준) |
| `compose.db_test.yaml` | tmpfs 테스트 MySQL | 작성·정적 검증·로컬 실행 검증 완료 (창고·QR 재고 시드 포함) |
| `compose.control.yaml` | FMS Gateway backend/API | 작성·정적 검증·로컬 build/readiness 검증 완료 |
| `compose.simulation.yaml` | RMF API/dashboard 지원 stack | 작성·정적 검증 완료, ROS 2/Gazebo는 현재 호스트 실행 |
| `compose.edge_4060.yaml` | MediaMTX와 4060 application 계약 | 작성·정적 검증 완료, QR·catalog image 구현 필요 |
| `compose.ai_5080.yaml` | 5080 AI image 실행 계약 | 작성·정적 검증 완료, env image·GPU 서버 검증 필요 |

Docker Engine은 호스트마다 하나만 설치한다. Compose 파일을 역할별로 나눈다는
뜻은 Docker를 여러 번 설치한다는 뜻이 아니라, 같은 Engine 위에서 수명주기와
장애 범위가 다른 서비스를 별도로 실행한다는 뜻이다.

## Control Tower 경계

현재 시연에서는 기존 `control_system` UI와 자체 Open-RMF/Gazebo 구성을 변경 없이
사용한다. `control_tower`는 Task Manager, API, projection, adapter/backend를 맡는다.
장기적으로 `control_system/robo_control`의 화면·theme·widget만
`control_tower/ui/`로 선별 이식하며 FleetEngine, SQLite, TCP 8788 권한은 복제하지
않는다. 자세한 경계는 [Control Tower 경계](../architecture/control_tower_boundary.md)를
참조한다.

## 실행 원칙

1. 새 호스트는 Docker와 GPU runtime을 최초 1회 준비한다.
2. 저장소의 `.env.example`을 참고해 호스트별 비밀값을 로컬 `.env`에 둔다.
3. DB → control → simulation/edge/AI 순서로 healthcheck를 통과시킨다.
4. 팀원은 장기적으로 `scripts/*_up.sh`를 사용하고, 호스트 설정은 bootstrap
   스크립트로 분리한다.
5. DB 초기화 SQL은 빈 볼륨에서만 자동 실행한다. 기존 볼륨 갱신은 migration으로
   수행한다.

## 현재 구현 수준을 읽는 방법

- `compose.control.yaml`은 현재 코드로 실제 실행할 수 있다. `fms_gateway/Dockerfile`이
  Python 3.12 runtime을 만들고, `/ready`가 MySQL 연결까지 확인한다.
- `compose.simulation.yaml`은 기존 `run_office_web.sh`가 Docker로 실행하던 RMF API와
  dashboard를 Compose로 옮긴 대안이다. 둘을 동시에 실행하면 3000·8000 포트가
  충돌하므로 하나만 선택한다. Gazebo와 ROS 2 launch는 현재 호스트에서 실행한다.
- `compose.edge_4060.yaml`의 `mediamtx`는 기본 실행 대상이다. `qr_worker`와
  `recording_catalog`은 장기 실행 entrypoint를 가진 image가 생긴 뒤
  `--profile application_images`로 활성화한다.
- `compose.ai_5080.yaml`은 `origin/env`의 backend Docker 작업으로 만든
  `TRIHOUSE_AI_IMAGE`를 실행한다. 현재 branch에서 거대한 AI 환경을 중복 build하지
  않으며, 5080 서버에서 NVIDIA Container Toolkit 검증 후 실행한다.
