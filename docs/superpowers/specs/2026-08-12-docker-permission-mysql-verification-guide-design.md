# Docker 계정 권한 및 MySQL 검증 가이드 설계

## 목적

Docker 소켓 접근 권한이 없는 사용자가 자신의 계정에 권한을 부여한 뒤, Trihouse의 일회용 MySQL 8.4 환경에서 `db/schema_mysql.sql`과 `db/seed_dev.sql`을 수동 검증할 수 있게 한다.

## 산출물

- 최종 문서: `docs/guideline/docker_permission_and_mysql_verification.md`
- 작성 언어: 한국어
- 계정 표기: 특정 사용자명 대신 셸의 현재 로그인 계정인 `"$USER"` 사용
- 대상 환경: Ubuntu 24.04 계열, Docker Engine 및 Compose plugin

## 선택한 접근법

기본 절차는 현재 로그인 계정을 `docker` 그룹에 추가하는 방식으로 한다.

```bash
sudo usermod -aG docker "$USER"
```

매 명령마다 `sudo docker`를 쓰는 방식과 Rootless Docker는 대안으로만 설명한다. POC PC에서 반복적으로 Compose 검증을 수행해야 하므로 Docker 그룹 방식이 가장 단순하다. 단, Docker 그룹 권한은 사실상 root급 권한이므로 개인 개발 PC에서만 적용하고 공동 서버에서는 관리자 정책을 따르도록 명시한다.

## 문서 구성

1. 적용 범위와 보안 주의사항
2. 현재 계정과 Docker 설치·서비스 상태 확인
3. `docker` 그룹 생성 및 `"$USER"` 권한 추가
4. 로그아웃·로그인 또는 `newgrp docker`를 이용한 그룹 반영
5. `docker run --rm hello-world`와 소켓 권한 확인
6. `compose.db_test.yaml` 기반 일회용 MySQL 8.4 기동
7. 컨테이너 상태·초기화 로그·스키마 및 seed 확인
8. `jobs`, `job_steps`, `job_step_attempts` 상태와 제약 확인
9. 일회용 컨테이너와 tmpfs 데이터 정리
10. 권한 거부, sudo 비밀번호, 포트 3307 충돌, unhealthy, SQL 초기화 실패 대응

## 명령 원칙

- 저장소 위치는 `/home/syw/Trihouse`로 안내한다. 이 PC에서 실제 작업 경로가 고정되어 있기 때문이다.
- 사용자 계정은 항상 `"$USER"`로 표기한다.
- 권한 반영 전 명령과 반영 후 명령을 분리한다.
- 영구 개발 DB인 `compose.db.yaml`이 아니라 tmpfs를 쓰는 `compose.db_test.yaml`만 검증에 사용한다.
- 정리 명령은 대상 Compose 파일과 project를 명시해 다른 컨테이너를 건드리지 않게 한다.
- 예상 결과와 실패 시 확인 명령을 각 단계 바로 아래에 둔다.

## 성공 기준

- `id -nG "$USER"` 출력에 `docker`가 포함된다.
- 비밀번호 없이 `docker version`과 `docker run --rm hello-world`가 성공한다.
- `docker compose -f compose.db_test.yaml up -d --wait`가 성공한다.
- MySQL 초기화 로그에 SQL 오류가 없다.
- `trihouse_fms.job_step_attempts`가 존재하고 주요 CHECK/unique 제약을 조회할 수 있다.
- `docker compose -f compose.db_test.yaml down` 후 테스트 컨테이너가 남지 않는다.

## 범위 밖

- Docker Engine 설치 자체를 자동 수행하지 않는다. 설치가 안 된 경우 공식 설치 문서를 확인할 진단 지점만 제공한다.
- 영구 개발 DB 데이터 migration은 수행하지 않는다.
- `control_system`과 `pinky_pro`의 코드나 Docker 구성을 수정하지 않는다.
- 방화벽, 원격 Docker daemon, Kubernetes, Rootless Docker의 상세 설치는 다루지 않는다.
