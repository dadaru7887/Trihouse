# FMS Gateway Development Setup

이 문서는 빈 Ubuntu 24.04 ARM64 환경에서 Trihouse의 MySQL, FMS Gateway,
Flutter 관제 UI 개발 환경을 동일하게 구성하기 위한 기록이다. 업무 시각은
`Asia/Seoul`, MySQL 세션은 `+09:00`을 사용한다.

DB만 새 서버에 재현하려면 설치·생성·검증 순서가 한 문서로 정리된
[서버 PC 데이터베이스 재현 가이드](server-db-reproduction-guide.md)를 먼저 따른다.

## 1. 확인된 시작 상태

2026-08-03에 `/home/luna/trihouse/Trihouse`에서 확인했다.

```text
Architecture: aarch64 / arm64
OS: Ubuntu 24.04.4 LTS (Noble)
Python: 3.12.3
pip: 26.1.2
Flutter: 설치되지 않음
Dart: 설치되지 않음
Docker: 설치되지 않음
MySQL client/server: 설치되지 않음
CMake: 3.28.3
pkg-config: 1.8.1
```

확인에 사용한 명령:

```bash
uname -m
dpkg --print-architecture
sed -n '1,12p' /etc/os-release
python3 --version
python3 -m pip --version
flutter --version || true
dart --version || true
docker --version || true
docker compose version || true
mysql --version || true
cmake --version
pkg-config --version
```

## 2. 저장소 준비

```bash
git clone --recurse-submodules https://github.com/dadaru7887/Trihouse.git
cd Trihouse
git switch dev_db
git submodule sync --recursive
git submodule update --init --recursive
```

기존 clone이라면:

```bash
git fetch origin
git switch dev_db
git pull --ff-only origin dev_db
git submodule sync --recursive
git submodule update --init --recursive
```

## 3. Ubuntu 시스템 패키지

Flutter Linux desktop과 Docker 설치에 관리자 권한이 필요하다.

```bash
sudo apt-get update
sudo apt-get install -y \
  ca-certificates curl git unzip xz-utils zip libglu1-mesa \
  clang cmake ninja-build pkg-config libgtk-3-dev libstdc++-12-dev
```

현재 작업 환경에서는 `sudo -n true`가 `sudo: a password is required`로
실패하여 이 단계는 실행하지 못했다. 다른 환경에서는 관리자에게 위 패키지 설치를
요청하거나 직접 실행해야 한다.

### 관리자 권한이 없는 현재 환경의 MySQL 테스트 대안

현재 환경에서는 Ubuntu MySQL 8.0.46 ARM64 패키지를 설치하지 않고 사용자
디렉터리에 추출했다. 일반 개발 환경에서는 Docker Compose가 기본 경로이며, 아래는
CI 또는 제한된 개발 계정에서만 사용하는 대안이다.

```bash
mkdir -p /tmp/trihouse-mysql-debs /home/luna/develop/mysql-local
cd /tmp/trihouse-mysql-debs
apt-get download \
  mysql-server-core-8.0 \
  mysql-client-core-8.0 \
  libaio1t64
for package_file in *.deb; do
  dpkg-deb -x "$package_file" /home/luna/develop/mysql-local
done
```

테스트 데이터 디렉터리 초기화:

```bash
mkdir -p \
  /tmp/trihouse-mysql-test-data \
  /tmp/trihouse-mysql-test-run \
  /tmp/trihouse-mysql-test-files
LD_LIBRARY_PATH=/home/luna/develop/mysql-local/usr/lib/aarch64-linux-gnu \
  /home/luna/develop/mysql-local/usr/sbin/mysqld \
  --no-defaults \
  --initialize-insecure \
  --basedir=/home/luna/develop/mysql-local/usr \
  --datadir=/tmp/trihouse-mysql-test-data \
  --log-error=/tmp/trihouse-mysql-test-run/init.log
```

테스트 서버 기동:

```bash
LD_LIBRARY_PATH=/home/luna/develop/mysql-local/usr/lib/aarch64-linux-gnu \
  /home/luna/develop/mysql-local/usr/sbin/mysqld \
  --no-defaults --daemonize \
  --basedir=/home/luna/develop/mysql-local/usr \
  --datadir=/tmp/trihouse-mysql-test-data \
  --socket=/tmp/trihouse-mysql-test-run/mysql.sock \
  --pid-file=/tmp/trihouse-mysql-test-run/mysql.pid \
  --log-error=/tmp/trihouse-mysql-test-run/mysql.log \
  --secure-file-priv=/tmp/trihouse-mysql-test-files \
  --port=3307 --bind-address=127.0.0.1 --mysqlx=0 \
  --default-time-zone=+09:00
```

실제 확인 결과:

```text
mysqld 8.0.46-0ubuntu0.24.04.3 for Linux on aarch64
TIMEDIFF(NOW(), UTC_TIMESTAMP()) = 09:00:00
```

이 방식은 `--initialize-insecure`를 사용하므로 localhost 테스트 전용이다. 외부에
노출하거나 운영 환경에서 사용하지 않는다.

## 4. Flutter 3.44.8 / Dart 3.12.2

Linux ARM64에서는 Flutter 저장소의 stable tag를 사용한다.

```bash
mkdir -p /home/luna/develop
git clone --depth 1 --branch 3.44.8 \
  https://github.com/flutter/flutter.git \
  /home/luna/develop/flutter
```

Bash PATH 등록:

```bash
echo 'export PATH="/home/luna/develop/flutter/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
flutter config --enable-linux-desktop
flutter --version
dart --version
flutter doctor -v
flutter devices
```

이 환경에서 실제로 사용한 clone 명령은 stable branch를 지정했으며, clone 결과
HEAD가 stable `3.44.8` tag임을 확인했다.

## 5. Docker Engine과 Compose

Docker 공식 Ubuntu 저장소를 등록한다.

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

```bash
printf '%s\n' \
  'Types: deb' \
  'URIs: https://download.docker.com/linux/ubuntu' \
  'Suites: noble' \
  'Components: stable' \
  'Architectures: arm64' \
  'Signed-By: /etc/apt/keyrings/docker.asc' \
  | sudo tee /etc/apt/sources.list.d/docker.sources
```

```bash
sudo apt-get update
sudo apt-get install -y \
  docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
newgrp docker
docker run --rm hello-world
docker compose version
```

`docker` 그룹은 호스트에서 관리자 수준 권한을 가질 수 있으므로 개발 머신의
보안 정책을 확인한다. 현재 작업 환경에서는 sudo 제약 때문에 Docker 설치와
Compose 실행을 수행하지 못했다.

## 6. Python Gateway 환경

```bash
python3 -m venv fms_gateway/.venv
fms_gateway/.venv/bin/python -m pip install --upgrade pip
fms_gateway/.venv/bin/python -m pip install \
  -r fms_gateway/requirements-dev.txt
fms_gateway/.venv/bin/python -m pip freeze
```

고정된 직접 의존성:

```text
fastapi==0.141.1
uvicorn==0.52.1
mysql-connector-python==26.7.0
pydantic-settings==2.14.2
httpx==0.28.1
pytest==9.1.1
pytest-cov==7.1.0
```

Flutter Gateway 클라이언트 의존성은 다음 명령으로 추가했으며 lock 파일에
`http 1.6.0`, `http_parser 4.1.2`가 고정되어 있다. 새 환경에서는 `pub add`를
반복하지 말고 커밋된 lock 파일을 사용해 `flutter pub get`만 실행한다.

```bash
cd control_system/robo_control
flutter pub add http
flutter pub get
cd ../..
```

## 7. MySQL 개발 환경 시작

비밀값 파일을 만들고 Git에 커밋하지 않는다.

```bash
if [ -e .env ]; then
  echo "STOP: 기존 .env가 있습니다. 덮어쓰지 않습니다." >&2
else
  cp .env.example .env
  chmod 600 .env
fi
```

`.env`의 `MYSQL_ROOT_PASSWORD`와 `FMS_DB_PASSWORD`를 변경한 뒤:

```bash
docker compose config
docker compose up -d --wait mysql
docker compose ps
docker compose logs mysql
```

초기화 시 다음 파일이 순서대로 적용된다.

```text
db/schema_mysql.sql
db/seed_dev.sql
```

이미 만들어진 volume에는 init SQL이 다시 적용되지 않는다. 개발 데이터를 완전히
초기화할 때만 다음 명령을 사용한다. 이 명령은 MySQL 개발 volume을 삭제한다.

```bash
docker compose down -v
docker compose up -d --wait mysql
```

## 8. 테스트 MySQL

테스트 DB는 포트 3307과 tmpfs를 사용하며 운영 volume을 건드리지 않는다.

```bash
set -euo pipefail
cleanup_test_db() {
  docker compose -p trihouse-test -f compose.test.yaml down -v
}
trap cleanup_test_db EXIT

docker compose -p trihouse-test -f compose.test.yaml up -d --wait mysql-test
test "$(docker inspect --format '{{.State.Health.Status}}' trihouse-mysql-test)" = healthy
test "$(docker compose -p trihouse-test -f compose.test.yaml port mysql-test 3306)" = 127.0.0.1:3307

FMS_DB_HOST=127.0.0.1 \
FMS_DB_PORT=3307 \
FMS_DB_USER=fms_gateway \
FMS_DB_PASSWORD=test_gateway_password \
FMS_DB_DATABASE=trihouse_fms \
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
fms_gateway/.venv/bin/pytest -c fms_gateway/pytest.ini fms_gateway/tests -v

trap - EXIT
cleanup_test_db
```

이 머신에는 ROS 2의 `launch_testing` pytest 플러그인이 전역 자동 로드되며 Python
경로의 `yaml` 의존성이 맞지 않았다. 위의 `PYTHONPATH=`와
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`은 Gateway 자체에 필요 없는 ROS 플러그인을
격리하기 위해 실제 테스트에 사용한 값이다. ROS가 없는 깨끗한 환경에서도 같은
명령을 사용해도 된다.

## 9. Gateway 실행

```bash
fms_gateway/.venv/bin/uvicorn \
  fms_gateway.app.main:create_app --factory \
  --host 127.0.0.1 \
  --port 8080
```

다른 터미널에서:

```bash
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8080/ready
curl -fsS http://127.0.0.1:8080/api/v1/devices
curl -fsS http://127.0.0.1:8080/api/v1/inventory/lots
curl -fsS http://127.0.0.1:8080/api/v1/jobs
```

재고 조정 예시(같은 키를 다시 보내도 수량은 한 번만 반영된다):

```bash
curl -fsS -X POST \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: manual-adjust-001' \
  -d '{"quantity_delta":-1,"recorded_by":"W-OP-01","note":"연동 확인"}' \
  http://127.0.0.1:8080/api/v1/inventory/lots/1/adjust
```

## 10. Flutter 관제 UI 실행

SQLite 회귀 모드:

```bash
cd control_system/robo_control
flutter pub get
flutter run -d linux
```

FMS API 모드:

```bash
cd control_system/robo_control
flutter pub get
flutter run -d linux \
  --dart-define=FMS_BASE_URL=http://127.0.0.1:8080
```

API 모드에서도 아직 이전되지 않은 관제 화면은 로컬 엔진을 사용하지만, 재고 조회와
조정은 Gateway를 통해서만 MySQL에 접근한다. Flutter 앱에는 DB 계정이나 비밀번호를
전달하지 않는다.

현재 머신에서는 Flutter/Dart와 패키지 설치 및 테스트까지 완료했지만,
`clang++`, `ninja`, GTK 3 개발 헤더는 sudo 권한이 없어 설치하지 못했다. 따라서
Linux 창을 실제로 띄우려면 3절의 시스템 패키지를 먼저 설치해야 한다.

## 11. 종료

```bash
docker compose down
docker compose -p trihouse-test -f compose.test.yaml down -v
```

MySQL 개발 데이터는 `docker compose down`만으로 삭제되지 않는다.

## 12. 2026-08-03 실제 검증 기록

사용자 디렉터리 MySQL(3307)에서 아래 Gateway 명령을 실행했다. 빈 비밀번호는
`--initialize-insecure`로 만든 localhost 전용 테스트 서버에만 해당한다.

```bash
FMS_DB_HOST=127.0.0.1 \
FMS_DB_PORT=3307 \
FMS_DB_USER=root \
FMS_DB_PASSWORD= \
FMS_DB_DATABASE=trihouse_fms \
fms_gateway/.venv/bin/uvicorn \
  fms_gateway.app.main:create_app --factory \
  --host 127.0.0.1 --port 8080
```

검증 결과:

```text
Gateway pytest: 35 passed
Flutter test: 35 passed
Flutter analyze: No issues found
GET /health: 200
GET /ready: 200, database=ok
GET /api/v1/devices: Pinky 2대 + OMX 2대
GET /api/v1/inventory/lots: 개발 로트 2건
같은 Idempotency-Key로 POST 2회: available_qty 100 -> 99
inventory_moves: 1건
operation_events: 1건
```

마지막 세 줄은 재시도 요청이 재고·원장·감사 로그를 중복 생성하지 않았음을 실제
MySQL 조회로 확인한 결과다.
