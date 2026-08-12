# Docker 계정 권한 및 MySQL 검증 가이드 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현재 로그인 계정에 Docker 권한을 부여하고 Trihouse 일회용 MySQL 8.4 스키마를 수동 검증하는 한국어 가이드를 작성한다.

**Architecture:** 하나의 독립 문서가 사전 점검, 권한 부여, 세션 반영, Docker 확인, 일회용 DB 검증, 정리, 장애 대응 순서를 제공한다. 계정은 특정 이름 대신 `"$USER"`로 참조하고, 영구 DB가 아닌 `compose.db_test.yaml`만 사용한다.

**Tech Stack:** Ubuntu 24.04, Bash, Docker Engine, Docker Compose plugin, MySQL 8.4

## Global Constraints

- 최종 문서는 `docs/guideline/docker_permission_and_mysql_verification.md`에 작성한다.
- 모든 사용자 계정 참조는 `"$USER"`를 사용한다.
- 저장소 경로는 `/home/syw/Trihouse`를 사용한다.
- 검증 환경은 tmpfs 기반 `compose.db_test.yaml`만 사용한다.
- `control_system`과 `pinky_pro`는 읽거나 수정하지 않는다.
- Docker 그룹이 사실상 root급 권한이라는 경고를 첫 부분에 표시한다.
- 컨테이너 정리는 `docker compose -f compose.db_test.yaml down`으로 범위를 제한한다.

---

### Task 1: 수동 권한 부여 및 일회용 MySQL 검증 가이드

**Files:**
- Create: `docs/guideline/docker_permission_and_mysql_verification.md`

**Interfaces:**
- Consumes: `compose.db_test.yaml`, `db/schema_mysql.sql`, `db/seed_dev.sql`
- Produces: 운영자가 위 파일을 변경하지 않고 실행할 수 있는 단계별 터미널 명령과 예상 결과

- [ ] **Step 1: 문서가 아직 없음을 확인한다**

Run:

```bash
test ! -e docs/guideline/docker_permission_and_mysql_verification.md
```

Expected: exit 0.

- [ ] **Step 2: 승인된 목차와 정확한 명령을 포함한 문서를 작성한다**

문서에는 다음 명령을 실행 순서대로 넣는다.

```bash
whoami
id -nG "$USER"
command -v docker
docker --version
docker compose version
systemctl is-active docker
getent group docker
sudo groupadd docker
sudo usermod -aG docker "$USER"
newgrp docker
id -nG "$USER"
docker version
docker run --rm hello-world
cd /home/syw/Trihouse
docker compose -f compose.db_test.yaml config
docker compose -f compose.db_test.yaml up -d --wait
docker compose -f compose.db_test.yaml ps
docker compose -f compose.db_test.yaml logs --no-color mysql_test
docker compose -f compose.db_test.yaml exec -T mysql_test mysql -uroot -ptest_root_password -e "SHOW DATABASES;"
docker compose -f compose.db_test.yaml exec -T mysql_test mysql -uroot -ptest_root_password trihouse_fms -e "SHOW TABLES LIKE 'job_step_attempts';"
docker compose -f compose.db_test.yaml exec -T mysql_test mysql -uroot -ptest_root_password trihouse_fms -e "SHOW CREATE TABLE job_step_attempts\G"
docker compose -f compose.db_test.yaml exec -T mysql_test mysql -uroot -ptest_root_password trihouse_fms -e "SELECT job_code, state FROM jobs WHERE job_code='JOB-DEV-001';"
docker compose -f compose.db_test.yaml down
docker compose -f compose.db_test.yaml ps -a
```

`sudo groupadd docker`는 그룹이 없을 때만 실행하도록 분기하고, 권한 반영의 권장 방법은 로그아웃 후 로그인으로 설명한다. `newgrp docker`는 현재 터미널에서 즉시 확인할 대안으로 표시한다. MySQL CLI의 비밀번호 경고는 일회용 테스트 계정에 한정된 정상 경고임을 설명한다.

- [ ] **Step 3: 필수 보안·범위 문구를 검증한다**

Run:

```bash
rg -n '\$USER|root급 권한|compose\.db_test\.yaml|tmpfs|job_step_attempts|3307|permission denied|unhealthy' docs/guideline/docker_permission_and_mysql_verification.md
```

Expected: 각 검색어가 보안 경고, 명령, 검증 또는 장애 대응 절에서 한 번 이상 출력된다.

- [ ] **Step 4: 특정 계정명이 권한 명령에 하드코딩되지 않았는지 확인한다**

Run:

```bash
rg -n 'usermod|id -nG' docs/guideline/docker_permission_and_mysql_verification.md
```

Expected: 모든 `usermod`와 `id -nG` 명령이 `"$USER"`를 사용한다.

- [ ] **Step 5: Markdown과 Git 변경 범위를 확인한다**

Run:

```bash
git diff --check -- docs/guideline/docker_permission_and_mysql_verification.md
git status --short -- docs/guideline/docker_permission_and_mysql_verification.md
```

Expected: `git diff --check` exit 0, status에는 새 guideline 문서 한 건만 출력된다.

- [ ] **Step 6: 문서를 커밋한다**

```bash
git add docs/guideline/docker_permission_and_mysql_verification.md
git commit -m "docs: add Docker permission and MySQL verification guide"
```
