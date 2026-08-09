# Server DB Reproduction Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 다른 Ubuntu 24.04 서버 PC에서 Trihouse 저장소를 내려받아 MySQL 환경을 구성하고, `trihouse_fms` 스키마·개발 시드·제약조건을 재현 및 검증하는 단일 실행 가이드를 제공한다.

**Architecture:** `compose.yaml`과 `db/schema_mysql.sql`, `db/seed_dev.sql`을 재현의 기준으로 삼고 Docker Compose를 기본 실행 경로로 사용한다. Docker를 사용할 수 없는 경우에는 기존 로컬 MySQL 대체 절차로 연결하되, 운영 DB 확인과 파괴적인 테스트 DB 검증을 포트 `3306`/`3307`로 명확히 분리한다.

**Tech Stack:** Ubuntu 24.04, Git, Docker Engine, Docker Compose v2, MySQL 8.4 container, Python 3.12 virtual environment, pytest 9.1.1

## Global Constraints

- 기준 스키마는 `db/schema_mysql.sql` 하나이며 `control_system/db/schema.sql`은 사용하지 않는다.
- 개발 DB는 `127.0.0.1:3306`, 테스트 DB는 `127.0.0.1:3307`만 사용한다.
- `fms_gateway/tests`는 데이터베이스를 삭제하고 재생성하므로 운영 DB 포트 `3306`에서 실행하지 않는다.
- 모든 비밀번호는 `.env`에만 저장하고 Git에 커밋하지 않는다.
- 기존 `control_system` 작업 트리 변경은 수정하거나 커밋하지 않는다.

---

### Task 1: 서버 DB 재현 가이드 작성

**Files:**
- Create: `docs/setup/server-db-reproduction-guide.md`
- Reference: `.env.example`
- Reference: `compose.yaml`
- Reference: `compose.test.yaml`
- Reference: `db/schema_mysql.sql`
- Reference: `db/seed_dev.sql`
- Reference: `docs/db_schema/db_guideline.md`
- Reference: `docs/setup/docker-openrmf-setup.md`
- Reference: `docs/setup/fms-gateway-setup.md`

**Interfaces:**
- Consumes: GitHub 저장소 URL, `dev_db` 브랜치, Docker Compose 서비스 이름 `mysql`/`mysql-test`, `FMS_DB_*` 환경 변수
- Produces: 새 서버에서 복사해 순서대로 실행할 수 있는 설치·생성·검증·복구 명령

- [ ] **Step 1: 새 PC 사전 조건과 저장소 준비 절차를 문서화한다**

  Ubuntu 버전/아키텍처/디스크/포트 확인, 실제 저장소 URL clone, `dev_db` checkout, `.env` 생성과 권한 설정을 정확한 명령으로 작성한다.

- [ ] **Step 2: Docker 기반 개발 DB 생성 절차를 문서화한다**

  Docker 설치 문서 연결, Compose 설정 검증, `mysql` 기동, health 확인, 최초 빈 볼륨에서만 init SQL이 적용된다는 경고를 포함한다.

- [ ] **Step 3: 스키마와 시드 결과 확인 절차를 문서화한다**

  MySQL 버전·시간대·문자셋, 정확히 15개 테이블, 필수 제약조건, 주요 시드 행 수를 확인하는 SQL과 기대값을 포함한다.

- [ ] **Step 4: 격리된 전체 자동 테스트 절차를 문서화한다**

  `mysql-test`를 `3307`에서 기동하고 `FMS_DB_HOST`, `FMS_DB_PORT`, `FMS_DB_USER`, `FMS_DB_PASSWORD`, `PYTHONPATH`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD`를 명시해 35개 테스트를 실행한 뒤 종료하는 절차를 작성한다.

- [ ] **Step 5: 로컬 MySQL 대체 경로와 장애 복구 절차를 문서화한다**

  Docker 불가 시 기존 가이드의 로컬 설치 절차로 연결하고, 포트 충돌·기존 볼륨·초기화 실패·로그 확인·데이터 삭제 경고를 포함한다.

### Task 2: 문서와 실행 절차 검증

**Files:**
- Test: `docs/setup/server-db-reproduction-guide.md`
- Test: `docs/db_schema/db_guideline.md`
- Test: `docs/db_schema/db_guideline.html`
- Test: `docs/setup/docker-openrmf-setup.md`
- Test: `docs/setup/fms-gateway-setup.md`
- Test: `README.md`

**Interfaces:**
- Consumes: Task 1의 명령과 링크
- Produces: 누락 링크, 잘못된 파일명, 민감정보, 운영 DB 파괴 가능성이 없는 검증된 문서 묶음

- [ ] **Step 1: Markdown 링크와 참조 파일을 검사한다**

  저장소 내부 상대 링크의 대상이 존재하는지 확인하고, 새 가이드가 `control_system/db/schema.sql`을 실행 대상으로 제시하지 않는지 검사한다.

- [ ] **Step 2: 운영 DB를 읽기 전용으로 확인한다**

  `127.0.0.1:3306`에서 MySQL 버전, `+09:00`, `utf8mb4`, 15개 테이블과 주요 시드 행 수를 조회한다.

- [ ] **Step 3: 테스트 DB에서 전체 검증을 실행한다**

  Run: `FMS_DB_HOST=127.0.0.1 FMS_DB_PORT=3307 FMS_DB_USER=fms_gateway FMS_DB_PASSWORD=test_gateway_password FMS_DB_DATABASE=trihouse_fms PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 fms_gateway/.venv/bin/pytest -c fms_gateway/pytest.ini fms_gateway/tests -q`

  Expected: exit code `0` (현재 테스트 수는 `35 passed`).

- [ ] **Step 4: 문서 자체 검토를 수행한다**

  미완성 표식, 실제 비밀번호, 존재하지 않는 경로, `FMS_DB_PORT=3306`과 pytest가 결합된 명령이 없는지 검색한다.

### Task 3: 필요한 문서만 선별 커밋

**Files:**
- Add: `docs/setup/server-db-reproduction-guide.md`
- Add: `docs/db_schema/db_guideline.md`
- Add: `docs/db_schema/db_guideline.html`
- Add: `docs/setup/docker-openrmf-setup.md`
- Modify: `docs/setup/fms-gateway-setup.md`
- Modify: `README.md`
- Add: `docs/superpowers/plans/2026-08-03-server-db-reproduction-guide.md`

**Interfaces:**
- Consumes: 검증이 끝난 문서 파일
- Produces: 다른 PC가 checkout할 수 있는 단일 Git 커밋

- [ ] **Step 1: 커밋 범위를 확인한다**

  `git status --short`와 `git diff --cached --stat`으로 위 일곱 파일만 포함되고 `control_system`이 제외됐는지 확인한다.

- [ ] **Step 2: 문서를 커밋한다**

  ```bash
  git add docs/setup/server-db-reproduction-guide.md \
    docs/db_schema/db_guideline.md \
    docs/db_schema/db_guideline.html \
    docs/setup/docker-openrmf-setup.md \
    docs/setup/fms-gateway-setup.md \
    README.md \
    docs/superpowers/plans/2026-08-03-server-db-reproduction-guide.md
  git commit -m "docs: add reproducible server database setup guide"
  ```

- [ ] **Step 3: 커밋 결과와 남은 사용자 변경을 확인한다**

  `git show --stat --oneline HEAD`와 `git status --short`를 실행해 문서 커밋과 제외된 `control_system` 변경을 각각 확인한다.
