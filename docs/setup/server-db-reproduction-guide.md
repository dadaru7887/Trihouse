# Trihouse 서버 PC 데이터베이스 재현 가이드

이 문서는 새 Ubuntu 서버 PC에서 저장소를 내려받아 `trihouse_fms` 개발 DB를 만들고,
스키마·시드·제약조건이 기준 파일과 일치하는지 확인하는 절차다. Open-RMF와
`control_system` 실행은 범위에 포함하지 않는다.

기준 파일:

- [MySQL 스키마](../../db/schema_mysql.sql) — FMS MySQL v3, 15개 테이블
- [개발 시드](../../db/seed_dev.sql) — 위치·작업자·장비·재고·작업 예제
- [DB 사용 규약](../db_schema/db_guideline.md)
- [Compose 개발 DB](../../compose.yaml) — `127.0.0.1:3306`, 영구 볼륨
- [Compose 테스트 DB](../../compose.test.yaml) — `127.0.0.1:3307`, tmpfs

> `control_system/db/schema.sql`과
> `control_system/db/migrate_sqlite_to_mysql.py`는 기존 `robosapiens`용이다.
> 이 가이드의 `trihouse_fms`에 사용하지 않는다.

---

## 0. 완료 기준

다음 결과가 모두 확인되면 DB 재현이 완료된 것이다.

| 확인 항목 | 기대 결과 |
| --- | --- |
| MySQL | `8.4.x` (`8.0` 이상 지원) |
| DB | `trihouse_fms` |
| 시간대 | `+09:00` |
| 문자셋 | `utf8mb4` |
| 테이블 | 15개 |
| 개발 시드 | 위치 4, 작업자 2, 장비 4, 재고 lot 2, 작업 1 |
| 자동 검증 | 종료 코드 0 (현재 테스트 수는 `35 passed`) |

개발 DB와 테스트 DB는 반드시 분리한다.

| 용도 | 포트 | 저장 방식 | 주의 |
| --- | ---: | --- | --- |
| 개발 DB | `3306` | Docker named volume | 데이터를 유지한다 |
| 테스트 DB | `3307` | tmpfs | pytest가 DB를 삭제하고 재생성한다 |

> **pytest를 `FMS_DB_PORT=3306`으로 실행하지 않는다.** 테스트 fixture가
> `trihouse_fms` 데이터베이스를 `DROP DATABASE`한 뒤 다시 생성한다.

---

## 1. 서버 사전 확인

검증 기준 환경은 Ubuntu 24.04 LTS다. `amd64`와 `arm64` 모두 MySQL 공식 이미지가
지원하지만, 현재 개발 환경의 확인된 아키텍처는 `arm64`다.

```bash
uname -m
dpkg --print-architecture
sed -n '1,12p' /etc/os-release
df -h /
free -h
ss -ltn | grep -E ':(3306|3307)\b' || true
```

권장 여유 공간은 Docker 이미지·볼륨을 포함해 10 GB 이상이다. `3306` 또는 `3307`이
이미 사용 중이면 10장의 포트 충돌 절차를 먼저 확인한다.

기본 패키지를 설치한다.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git python3 python3-venv
```

---

## 2. 저장소 준비

새로 clone할 때:

```bash
cd "$HOME"
mkdir -p trihouse
cd trihouse
git clone --recurse-submodules https://github.com/dadaru7887/Trihouse.git
cd Trihouse
git switch dev_db
git submodule sync --recursive
git submodule update --init --recursive
```

이미 clone한 저장소를 갱신할 때:

```bash
cd "$HOME/trihouse/Trihouse"
git fetch origin
git switch dev_db
git pull --ff-only origin dev_db
git submodule sync --recursive
git submodule update --init --recursive
```

DB 기준 파일이 모두 있는지 확인한다.

```bash
test -f compose.yaml
test -f compose.test.yaml
test -f db/schema_mysql.sql
test -f db/seed_dev.sql
test -f fms_gateway/requirements-dev.txt
git status --short
```

`git status`에 예상하지 않은 수정 파일이 있으면 DB를 만들기 전에 원인을 확인한다.

---

## 3. Docker Engine과 Compose 설치

이미 `docker version`과 `docker compose version`이 모두 성공하면 4장으로 간다.

```bash
docker version || true
docker compose version || true
```

충돌 가능한 기존 패키지를 제거한다. 설치된 적이 없는 패키지의 제거 오류는 무시할
수 있다.

> 기존 Docker, containerd, Kubernetes workload가 있는 서버에서는 아래 제거 명령을
> 바로 실행하지 않는다. 먼저 `docker ps -a`, `sudo ctr containers list`,
> `kubectl get nodes`로 사용 여부를 확인하고, 운영 workload가 있으면 서버 관리자와
> 별도 마이그레이션 계획을 세운다.

```bash
docker ps -a 2>/dev/null || true
sudo ctr containers list 2>/dev/null || true
kubectl get nodes 2>/dev/null || true
```

```bash
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
  sudo apt-get remove -y "$pkg"
done
```

Docker 공식 Ubuntu 저장소를 등록한다.

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu \
$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y \
  docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
```

Docker 서비스를 시작하고 현재 사용자를 `docker` 그룹에 넣는다.

```bash
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

그룹 변경은 새 로그인부터 적용된다. 로그아웃 후 다시 로그인하는 것이 가장 확실하다.
현재 셸만 갱신하려면 `newgrp docker`를 실행한다. `docker` 그룹은 호스트의 root와
사실상 같은 권한을 가지므로 서버 보안 정책을 먼저 확인한다.

재로그인 후 검증한다.

```bash
systemctl is-active docker
docker version
docker compose version
docker run --rm hello-world
docker info --format '{{.Driver}} {{.CgroupVersion}} {{.Architecture}}'
```

더 자세한 Docker/Open-RMF 설치 조건은
[Docker · Open-RMF 설치 가이드](docker-openrmf-setup.md)를 참조한다. DB만 재현할
때는 Open-RMF 빌드가 필요 없다.

---

## 4. 비밀값과 환경 변수 설정

저장소 루트에서 예시 파일을 복사한다.

```bash
cd "$HOME/trihouse/Trihouse"
if [ -e .env ]; then
  echo "STOP: 기존 .env가 있습니다. 덮어쓰지 않습니다." >&2
else
  cp .env.example .env
  chmod 600 .env
fi
```

`.env`에서 최소한 다음 두 비밀번호를 충분히 긴 임의 값으로 바꾼다. 이 가이드의
검증 명령과 Compose dotenv 문법을 모두 안전하게 통과하도록 영문자와 숫자로만
32자 이상 생성한다. 예를 들어 `python3 -c 'import secrets; print(secrets.token_hex(24))'`를
두 번 실행해 서로 다른 값을 사용할 수 있다.

```dotenv
MYSQL_ROOT_PASSWORD=change_me_root
FMS_DB_DATABASE=trihouse_fms
FMS_DB_USER=fms_gateway
FMS_DB_PASSWORD=change_me_gateway
FMS_DB_HOST=127.0.0.1
FMS_DB_PORT=3306
```

위 블록은 키 이름 예시다. `change_me_root`와 `change_me_gateway`를 실제로 사용하면
안 된다. 비밀번호를 화면에 출력하지 않고 변경 여부를 확인한다.

```bash
! grep -qx 'MYSQL_ROOT_PASSWORD=change_me_root' .env
! grep -qx 'FMS_DB_PASSWORD=change_me_gateway' .env
grep -qx 'FMS_DB_DATABASE=trihouse_fms' .env
grep -qx 'FMS_DB_PORT=3306' .env
```

`.env`는 `.gitignore` 대상이다. 다음 명령에 `.env`가 출력되면 커밋하지 말고
`.gitignore`를 먼저 확인한다.

```bash
git status --short
git check-ignore -v .env
```

---

## 5. 개발 DB 생성

Compose 문법과 최종 설정을 먼저 검사한다. `config` 출력에는 환경 변수가 전개될 수
있으므로 서버 로그나 채팅에 그대로 붙여 넣지 않는다.

```bash
docker compose config --quiet
```

새 서버에서 개발 DB를 처음 시작한다.

```bash
docker compose pull mysql
docker compose up -d --wait mysql
docker compose ps
```

기대 상태는 `trihouse-mysql` 컨테이너의 `healthy`다. 초기화 로그를 확인한다.

```bash
docker compose logs --tail=200 mysql
```

최초 빈 볼륨에서는 다음 파일이 파일명 순서대로 한 번 적용된다.

```text
db/schema_mysql.sql  -> /docker-entrypoint-initdb.d/001-schema.sql
db/seed_dev.sql      -> /docker-entrypoint-initdb.d/002-seed.sql
```

`docker-entrypoint-initdb.d`는 데이터 볼륨이 비어 있을 때만 실행된다. SQL 파일을
바꾼 뒤 `docker compose restart`만 해서는 기존 DB 스키마가 갱신되지 않는다.

---

## 6. 서버와 스키마 확인

아래 명령은 컨테이너 내부 환경 변수로 Gateway 계정에 접속한다. 비밀번호를 호스트
명령줄에 직접 넣지 않는다.

```bash
docker compose exec -T mysql sh -lc '
  MYSQL_PWD="$MYSQL_PASSWORD" mysql \
    --user="$MYSQL_USER" \
    --database="$MYSQL_DATABASE" \
    --batch --raw \
    --execute="
      SELECT VERSION() AS mysql_version,
             DATABASE() AS current_database,
             @@session.time_zone AS session_timezone,
             @@character_set_server AS charset;
    "
'
```

기대값은 MySQL `8.4.x`, DB `trihouse_fms`, 시간대 `+09:00`, 문자셋 `utf8mb4`다.

### 6.1 테이블 15개 확인

```bash
docker compose exec -T mysql sh -lc '
  MYSQL_PWD="$MYSQL_PASSWORD" mysql \
    --user="$MYSQL_USER" \
    --database="$MYSQL_DATABASE" \
    --batch --skip-column-names \
    --execute="SHOW TABLES;"
'
```

다음 15개가 출력되어야 한다.

```text
artifacts
device_states
devices
incidents
integration_messages
inventory_lots
inventory_moves
job_items
job_steps
jobs
locations
map_features
operation_events
reservations
workers
```

정확한 개수:

```bash
docker compose exec -T mysql sh -lc '
  MYSQL_PWD="$MYSQL_PASSWORD" mysql \
    --user="$MYSQL_USER" \
    --database="$MYSQL_DATABASE" \
    --batch --raw \
    --execute="
      SELECT COUNT(*) AS table_count
      FROM information_schema.tables
      WHERE table_schema = \"trihouse_fms\"
        AND table_type = \"BASE TABLE\";
    "
'
```

기대 결과는 `table_count = 15`다.

### 6.2 필수 컬럼과 인덱스 확인

```bash
docker compose exec -T mysql sh -lc '
  MYSQL_PWD="$MYSQL_PASSWORD" mysql \
    --user="$MYSQL_USER" \
    --database="$MYSQL_DATABASE" \
    --table \
    --execute="
      SELECT table_name, column_name, column_type
      FROM information_schema.columns
      WHERE table_schema = \"trihouse_fms\"
        AND (table_name, column_name) IN (
          (\"jobs\", \"parent_job_id\"),
          (\"jobs\", \"revision\"),
          (\"jobs\", \"priority_rank\"),
          (\"inventory_moves\", \"reserved_delta\"),
          (\"integration_messages\", \"next_attempt_at\"),
          (\"incidents\", \"acknowledged_at\")
        )
      ORDER BY table_name, column_name;

      SELECT table_name, index_name
      FROM information_schema.statistics
      WHERE table_schema = \"trihouse_fms\"
        AND index_name IN (
          \"uq_jobs_external_reference\",
          \"idx_jobs_dispatch\",
          \"idx_reservations_feature_expiry\",
          \"idx_messages_delivery\",
          \"idx_events_occurred_at\"
        )
      ORDER BY table_name, index_name;
    "
'
```

테이블 하나의 실제 DDL과 CHECK/FK를 자세히 보려면:

```bash
docker compose exec -T mysql sh -lc '
  MYSQL_PWD="$MYSQL_PASSWORD" mysql \
    --user="$MYSQL_USER" \
    --database="$MYSQL_DATABASE" \
    --execute="SHOW CREATE TABLE inventory_lots\\G"
'
```

---

## 7. 개발 시드 확인

정확한 시드 행 수를 확인한다. InnoDB의 `information_schema.tables.table_rows`는
추정치이므로 여기서는 각 테이블에 `COUNT(*)`를 실행한다.

```bash
docker compose exec -T mysql sh -lc '
  MYSQL_PWD="$MYSQL_PASSWORD" mysql \
    --user="$MYSQL_USER" \
    --database="$MYSQL_DATABASE" \
    --table \
    --execute="
      SELECT \"locations\" AS table_name, COUNT(*) AS row_count FROM locations
      UNION ALL SELECT \"workers\", COUNT(*) FROM workers
      UNION ALL SELECT \"devices\", COUNT(*) FROM devices
      UNION ALL SELECT \"device_states\", COUNT(*) FROM device_states
      UNION ALL SELECT \"inventory_lots\", COUNT(*) FROM inventory_lots
      UNION ALL SELECT \"jobs\", COUNT(*) FROM jobs
      UNION ALL SELECT \"job_items\", COUNT(*) FROM job_items
      UNION ALL SELECT \"job_steps\", COUNT(*) FROM job_steps;
    "
'
```

기대 결과:

| 테이블 | 행 수 |
| --- | ---: |
| `locations` | 4 |
| `workers` | 2 |
| `devices` | 4 |
| `device_states` | 4 |
| `inventory_lots` | 2 |
| `jobs` | 1 |
| `job_items` | 1 |
| `job_steps` | 1 |

대표 데이터도 확인한다.

```bash
docker compose exec -T mysql sh -lc '
  MYSQL_PWD="$MYSQL_PASSWORD" mysql \
    --user="$MYSQL_USER" \
    --database="$MYSQL_DATABASE" \
    --table \
    --execute="
      SELECT device_id, device_type, name, control_mode FROM devices ORDER BY device_id;
      SELECT lot_code, product_code, available_qty, reserved_qty, state
      FROM inventory_lots ORDER BY lot_id;
      SELECT job_code, operation_type, priority, state FROM jobs ORDER BY job_id;
    "
'
```

장비는 `PINKY-01`, `PINKY-02`, `OMX-01`, `OMX-02` 네 대가 출력되어야 한다.

---

## 8. 격리된 자동 검증

### 8.1 Python 환경

Gateway의 고정된 개발 의존성을 별도 가상환경에 설치한다.

```bash
cd "$HOME/trihouse/Trihouse"
python3 -m venv fms_gateway/.venv
fms_gateway/.venv/bin/python -m pip install --upgrade pip
fms_gateway/.venv/bin/python -m pip install \
  -r fms_gateway/requirements-dev.txt
```

### 8.2 테스트 DB 기동

테스트 DB는 `3307`과 tmpfs를 사용하므로 컨테이너를 내리면 데이터가 사라진다.

```bash
set -euo pipefail
docker compose -p trihouse-test -f compose.test.yaml up -d --wait mysql-test
test "$(docker inspect --format '{{.State.Health.Status}}' trihouse-mysql-test)" = healthy
test "$(docker compose -p trihouse-test -f compose.test.yaml port mysql-test 3306)" = 127.0.0.1:3307
docker compose -p trihouse-test -f compose.test.yaml ps
```

### 8.3 전체 테스트

다음 명령은 `3307` 테스트 DB에서만 실행한다.

```bash
set -euo pipefail

cleanup_test_db() {
  docker compose -p trihouse-test -f compose.test.yaml down -v
}
trap cleanup_test_db EXIT

test "$(docker inspect --format '{{.State.Health.Status}}' trihouse-mysql-test)" = healthy
test "$(docker compose -p trihouse-test -f compose.test.yaml port mysql-test 3306)" = 127.0.0.1:3307

FMS_DB_HOST=127.0.0.1 \
FMS_DB_PORT=3307 \
FMS_DB_USER=fms_gateway \
FMS_DB_PASSWORD=test_gateway_password \
FMS_DB_DATABASE=trihouse_fms \
PYTHONPATH= \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
fms_gateway/.venv/bin/pytest \
  -c fms_gateway/pytest.ini \
  fms_gateway/tests \
  -q

trap - EXIT
cleanup_test_db
```

기대 결과:

```text
35 passed  # 현재 커밋 기준; 이후에는 종료 코드 0을 성공 기준으로 삼는다.
```

이 테스트는 다음을 실제 MySQL에서 검증한다.

- DDL 15개 테이블 생성
- CHECK, UNIQUE, FK와 필수 인덱스
- 서울 시간대 세션
- 시드 스크립트의 멱등성과 행 수
- 예약 충돌 계산
- 재고 조정의 원자성·멱등성·감사 이력
- Gateway 읽기 API

정상 종료와 오류 종료 모두 `trap`이 테스트 DB만 정리한다. 개발 DB는 계속 사용할
것이므로 기본 `docker compose down`은 실행하지 않는다.

---

## 9. 재부팅·종료·백업

`compose.yaml`의 MySQL은 `restart: unless-stopped`로 설정되어 있다. 재부팅 후 상태를
확인한다.

```bash
cd "$HOME/trihouse/Trihouse"
docker compose ps
docker compose up -d --wait mysql
```

개발 DB 컨테이너만 종료하되 데이터는 유지한다.

```bash
docker compose down
```

다시 시작하면 기존 named volume을 그대로 사용한다.

```bash
docker compose up -d --wait mysql
```

초기화나 마이그레이션 전에 논리 백업을 만든다.

```bash
umask 077
mkdir -p "$HOME/trihouse/backups"
backup_file="$HOME/trihouse/backups/trihouse_fms_$(date +%Y%m%d_%H%M%S).sql"
backup_tmp=$(mktemp "$HOME/trihouse/backups/.trihouse_fms_XXXXXX.sql")
cleanup_backup() {
  rm -f "$backup_tmp"
}
trap cleanup_backup EXIT

docker compose exec -T mysql sh -lc '
  MYSQL_PWD="$MYSQL_PASSWORD" mysqldump \
    --user="$MYSQL_USER" \
    --single-transaction \
    --no-tablespaces \
    --routines --triggers \
    "$MYSQL_DATABASE"
' > "$backup_tmp"

test -s "$backup_tmp"
mv "$backup_tmp" "$backup_file"
trap - EXIT
ls -lh "$backup_file"
```

---

## 10. 문제 해결

### 10.1 Docker socket 권한 오류

증상:

```text
permission denied while trying to connect to the Docker daemon socket
```

조치:

```bash
sudo usermod -aG docker "$USER"
```

그다음 로그아웃·재로그인하고 `docker version`을 다시 실행한다.

### 10.2 `3306` 또는 `3307` 포트 충돌

```bash
ss -ltnp | grep -E ':(3306|3307)\b' || true
docker ps --format 'table {{.Names}}\t{{.Ports}}'
```

기존 로컬 mysqld나 다른 MySQL 컨테이너가 사용 중이면 해당 서비스가 보존해야 할
DB인지 먼저 확인한다. 확인 없이 프로세스를 종료하거나 데이터를 삭제하지 않는다.

### 10.3 컨테이너가 healthy가 되지 않음

```bash
docker compose ps
docker compose logs --tail=300 mysql
docker inspect trihouse-mysql --format '{{json .State.Health}}'
```

주요 원인은 비밀번호 누락, 포트 충돌, 디스크 부족, 과거 버전으로 만들어진 볼륨이다.

### 10.4 SQL을 수정했지만 스키마가 바뀌지 않음

init SQL은 빈 볼륨에서만 적용된다. 기존 데이터가 필요하면 먼저 9장의 `mysqldump`로
백업한 뒤 명시적인 migration SQL을 적용한다.

개발 데이터를 모두 버려도 되는 새 서버의 초기 구성에서만 다음 명령을 사용한다.

```bash
# 경고: 이 Compose 프로젝트가 선언한 trihouse_mysql_data 볼륨과 개발 DB를 삭제한다.
# 실제 Docker 볼륨 이름에는 프로젝트명 접두사가 붙을 수 있다.
docker compose down -v
docker compose up -d --wait mysql
```

### 10.5 pytest가 ROS 플러그인에서 실패함

`launch_testing`, `ament_*`, `yaml` 관련 오류가 DB 테스트 시작 전에 발생하면 8.3의
`PYTHONPATH=`와 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`이 빠졌는지 확인한다.

### 10.6 Docker를 설치할 수 없음

관리자 권한이나 서버 정책 때문에 Docker를 사용할 수 없다면
[FMS Gateway Development Setup §3](fms-gateway-setup.md#3-ubuntu-시스템-패키지)의
“관리자 권한이 없는 현재 환경의 MySQL 테스트 대안”을 사용한다.

이 대안은 **Ubuntu 24.04 ARM64에서만 검증됐다.** 문서의 `/home/luna`와
`aarch64-linux-gnu` 경로를 현재 사용자 홈과 실제 multiarch 경로에 맞춰야 한다.
Ubuntu MySQL 패키지를 사용자 디렉터리에 추출해 `127.0.0.1:3307`에서 실행하며,
`--initialize-insecure`를 사용한다. localhost 테스트에만 사용하고 다른 호스트에
포트를 공개하지 않는다. AMD64 서버나 지속 개발 DB에는 Docker Compose 경로를
권장한다.

---

## 11. 최종 체크리스트

- [ ] `git switch dev_db`와 `git pull --ff-only origin dev_db`를 완료했다.
- [ ] `.env`의 기본 비밀번호 두 개를 변경했고 파일 권한이 `600`이다.
- [ ] `docker version`에서 Client와 Server가 모두 출력된다.
- [ ] `docker compose version`이 v2다.
- [ ] `trihouse-mysql`이 `healthy`다.
- [ ] MySQL 시간대가 `+09:00`, 문자셋이 `utf8mb4`다.
- [ ] `trihouse_fms`에 정확히 15개 테이블이 있다.
- [ ] 개발 시드의 행 수가 7장의 기대값과 같다.
- [ ] 전체 테스트가 `3307`에서 종료 코드 0이다 (현재 `35 passed`).
- [ ] pytest를 개발 DB `3306`에서 실행하지 않았다.
- [ ] `.env`와 DB 백업 파일을 Git에 추가하지 않았다.
