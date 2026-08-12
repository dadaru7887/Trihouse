# Docker 계정 권한 부여 및 MySQL 스키마 수동 검증 가이드

이 문서는 현재 로그인한 계정에 Docker 사용 권한을 부여하고, Trihouse의 일회용 MySQL 8.4 컨테이너에서 스키마와 개발 seed를 검증하는 절차다.

> [!WARNING]
> `docker` 그룹에 속한 사용자는 컨테이너의 볼륨 마운트 등을 통해 호스트의 root 권한에 준하는 작업을 수행할 수 있다. 개인 개발 PC에서만 적용하고, 공동 서버나 운영 장비에서는 시스템 관리자의 권한 정책을 따른다.

## 1. 이 절차가 건드리는 범위

- 사용자 계정은 특정 이름을 쓰지 않고 현재 로그인 계정인 `"$USER"`로 참조한다.
- 저장소 경로는 `/home/syw/Trihouse`를 사용한다.
- 테스트에는 [compose.db_test.yaml](../../compose.db_test.yaml)만 사용한다.
- 테스트 DB의 데이터는 컨테이너 내부 `tmpfs`에 저장되므로 컨테이너를 내리면 사라진다.
- 영구 개발 DB인 `compose.db.yaml`과 기존 데이터는 건드리지 않는다.
- `control_system`과 `pinky_pro`의 코드 및 Docker 구성은 변경하지 않는다.

## 2. 현재 계정과 Docker 상태 확인

먼저 현재 로그인 계정과 그룹을 확인한다.

```bash
whoami
id -nG "$USER"
```

첫 번째 명령은 현재 계정명을 출력한다. 두 번째 출력에 `docker`가 없다면 아직 Docker 소켓 권한이 없는 상태다.

Docker Engine과 Compose plugin 설치 여부를 확인한다.

```bash
command -v docker
docker --version
docker compose version
```

예상 결과:

- `command -v docker`: 일반적으로 `/usr/bin/docker`
- `docker --version`: `Docker version ...`
- `docker compose version`: `Docker Compose version ...`

명령 자체가 없다면 Docker 권한 문제가 아니라 Docker Engine 또는 Compose plugin 설치 문제다. 이 경우 설치를 먼저 완료해야 한다.

Docker 서비스 상태도 확인한다.

```bash
systemctl is-active docker
```

정상이면 `active`가 출력된다. 비활성 상태라면 다음 명령으로 시작한다.

```bash
sudo systemctl enable --now docker
```

## 3. 현재 계정에 Docker 그룹 권한 부여

Docker 그룹이 있는지 확인한다.

```bash
getent group docker
```

출력이 없다면 그룹을 만든다. 이미 존재할 때 `groupadd`를 다시 실행하지 않는다.

```bash
getent group docker >/dev/null || sudo groupadd docker
```

현재 로그인 계정을 Docker 그룹에 추가한다.

```bash
sudo usermod -aG docker "$USER"
```

여기서 `-aG`의 의미는 다음과 같다.

- `-G docker`: 보조 그룹 목록에 `docker`를 지정한다.
- `-a`: 기존 보조 그룹을 지우지 않고 새 그룹을 추가한다.

`-a`를 빼면 기존 보조 그룹이 제거될 수 있으므로 반드시 `-aG`를 함께 사용한다.

Docker 서비스와 소켓 정보를 확인한다.

```bash
sudo systemctl restart docker
stat -c '%U %G %a %n' /var/run/docker.sock
```

일반적인 소켓 출력은 다음과 같다.

```text
root docker 660 /var/run/docker.sock
```

소켓 그룹이 `docker`가 아니라면 10절의 문제 해결 절차를 확인한다. 소켓에 임의로 `chmod 666`을 적용하면 모든 로컬 사용자가 root급 Docker 권한을 갖게 되므로 사용하지 않는다.

## 4. 새 그룹 권한을 로그인 세션에 반영

가장 확실한 방법은 다음 순서다.

1. 현재 작업을 저장한다.
2. Ubuntu 사용자 세션에서 로그아웃한다.
3. 같은 계정으로 다시 로그인한다.
4. 새 터미널을 연다.

로그아웃하기 어려운 경우 현재 터미널에서만 다음 명령으로 새 그룹 셸을 열 수 있다.

```bash
newgrp docker
```

`newgrp docker`는 새로운 하위 셸을 연다. 검증을 마친 후 해당 셸에서 `exit`를 실행하면 원래 셸로 돌아간다.

새 세션에서 그룹이 반영됐는지 확인한다.

```bash
id -nG "$USER"
```

출력에 `docker`가 포함되어야 한다.

## 5. sudo 없이 Docker 사용 확인

Docker client가 daemon과 통신하는지 확인한다.

```bash
docker version
```

정상이면 `Client`와 `Server` 정보가 모두 출력된다. `Client`만 나오고 `permission denied`가 발생하면 그룹 또는 소켓 권한이 아직 반영되지 않은 것이다.

간단한 컨테이너 실행도 확인한다.

```bash
docker run --rm hello-world
```

처음 실행할 때는 `hello-world` 이미지를 인터넷에서 내려받는다. 네트워크가 차단된 환경에서는 image pull이 실패할 수 있으므로, 이 경우에도 `docker version`의 Server 정보가 정상이라면 계정 권한 자체는 확인된 것이다.

## 6. Trihouse 일회용 MySQL 구성 확인

저장소로 이동한다.

```bash
cd /home/syw/Trihouse
```

Compose 파일을 해석할 수 있는지 먼저 확인한다. 이 명령은 컨테이너를 만들지 않는다.

```bash
docker compose -f compose.db_test.yaml config
```

이 테스트 구성의 핵심 특성은 다음과 같다.

| 항목 | 값 |
| --- | --- |
| Compose project | `trihouse_db_test` |
| 서비스 | `mysql_test` |
| MySQL | `mysql:8.4` |
| 호스트 포트 | `127.0.0.1:3307` |
| 컨테이너 포트 | `3306` |
| 데이터 저장 | `/var/lib/mysql` tmpfs |
| 초기화 스키마 | `db/schema_mysql.sql` |
| 개발 seed | `db/seed_dev.sql` |

`config` 명령에서 파일 누락이나 YAML 오류가 나오면 컨테이너를 실행하지 말고 해당 오류부터 확인한다.

## 7. 일회용 MySQL 8.4 기동

MySQL 테스트 컨테이너를 시작하고 health check가 끝날 때까지 기다린다.

```bash
docker compose -f compose.db_test.yaml up -d --wait
```

상태를 확인한다.

```bash
docker compose -f compose.db_test.yaml ps
```

정상 예시:

```text
NAME                          SERVICE      STATUS
trihouse_db_test-mysql_test-1 mysql_test   Up ... (healthy)
```

초기화 로그를 확인한다.

```bash
docker compose -f compose.db_test.yaml logs --no-color mysql_test
```

다음 항목을 확인한다.

- MySQL server가 ready 상태가 되었는가
- `db/schema_mysql.sql` 실행 중 SQL syntax error가 없는가
- `db/seed_dev.sql` 실행 중 CHECK 또는 FK 위반이 없는가
- 컨테이너가 반복 재시작하거나 `unhealthy` 상태가 아닌가

## 8. 스키마와 seed 직접 확인

이 Compose 파일은 일회용 root 비밀번호로 `test_root_password`를 사용한다. 아래 MySQL CLI 명령에서 비밀번호가 명령행에 노출된다는 경고가 나올 수 있지만, 이 값은 테스트 컨테이너 전용 고정 값이다. 운영 비밀번호를 같은 방식으로 사용하면 안 된다.

데이터베이스 목록을 확인한다.

```bash
docker compose -f compose.db_test.yaml exec -T mysql_test \
  mysql -uroot -ptest_root_password -e "SHOW DATABASES;"
```

`trihouse_fms`와 `trihouse_recovery`가 출력되어야 한다.

`job_step_attempts` 테이블이 생성됐는지 확인한다.

```bash
docker compose -f compose.db_test.yaml exec -T mysql_test \
  mysql -uroot -ptest_root_password trihouse_fms \
  -e "SHOW TABLES LIKE 'job_step_attempts';"
```

예상 결과:

```text
Tables_in_trihouse_fms (job_step_attempts)
job_step_attempts
```

테이블의 컬럼, unique key, CHECK와 FK를 확인한다.

```bash
docker compose -f compose.db_test.yaml exec -T mysql_test \
  mysql -uroot -ptest_root_password trihouse_fms \
  -e "SHOW CREATE TABLE job_step_attempts\G"
```

출력에서 최소한 다음 제약을 확인한다.

- `PRIMARY KEY (attempt_uuid)`
- `UNIQUE KEY uq_attempts_event (event_uuid)`
- `UNIQUE KEY uq_attempts_command (command_uuid)`
- `UNIQUE KEY uq_attempts_sequence`
- `CHECK` 제약 `chk_attempts_terminal`
- `CHECK` 제약 `chk_attempts_success_outcome`
- `FOREIGN KEY (job_step_id)`

현재 작업·단계 상태 제약도 확인한다.

```bash
docker compose -f compose.db_test.yaml exec -T mysql_test \
  mysql -uroot -ptest_root_password trihouse_fms \
  -e "SHOW CREATE TABLE jobs\G; SHOW CREATE TABLE job_steps\G;"
```

허용 상태는 다음과 같아야 한다.

| 대상 | 허용 상태 |
| --- | --- |
| `jobs.state` | `queued`, `assigned`, `running`, `held`, `completed`, `failed`, `cancelled` |
| `job_steps.state` | `pending`, `running`, `succeeded`, `failed`, `cancelled` |

개발 seed가 새 job 상태 계약으로 들어갔는지 확인한다.

```bash
docker compose -f compose.db_test.yaml exec -T mysql_test \
  mysql -uroot -ptest_root_password trihouse_fms \
  -e "SELECT job_code, state FROM jobs WHERE job_code='JOB-DEV-001';"
```

예상 결과:

```text
JOB-DEV-001  queued
```

필요하면 테이블 개수도 확인한다.

```bash
docker compose -f compose.db_test.yaml exec -T mysql_test \
  mysql -uroot -ptest_root_password -N -e \
  "SELECT table_schema, COUNT(*) FROM information_schema.tables WHERE table_schema IN ('trihouse_fms','trihouse_recovery') GROUP BY table_schema ORDER BY table_schema;"
```

현재 기준 스키마의 예상 결과는 다음과 같다.

```text
trihouse_fms       17
trihouse_recovery  2
```

## 9. 테스트 컨테이너 정리

검증이 끝나면 해당 Compose project의 컨테이너와 네트워크를 내린다.

```bash
docker compose -f compose.db_test.yaml down
```

> [!CAUTION]
> `mysql_test`는 `/var/lib/mysql`을 tmpfs로 사용한다. `down` 또는 컨테이너 제거 후 테스트 데이터는 복구되지 않는다. 일회용 검증 데이터이므로 의도된 동작이다.

컨테이너가 남지 않았는지 확인한다.

```bash
docker compose -f compose.db_test.yaml ps -a
```

서비스 목록이 비어 있으면 정리가 완료된 것이다. 다른 Compose 파일에 `down`을 실행하지 않는다.

`newgrp docker`로 하위 셸을 열었다면 마지막에 원래 셸로 돌아간다.

```bash
exit
```

## 10. 문제 해결

### 10.1 Docker 소켓 permission denied

증상 예시:

```text
permission denied while trying to connect to the docker API at unix:///var/run/docker.sock
```

현재 셸과 로그인 계정의 그룹을 각각 확인한다.

```bash
id
id -nG "$USER"
stat -c '%U %G %a %n' /var/run/docker.sock
```

확인 순서:

1. `id -nG "$USER"`에 `docker`가 있는지 확인한다.
2. 현재 셸의 `id` 출력에도 `docker`가 있는지 확인한다.
3. 없다면 완전히 로그아웃한 뒤 다시 로그인한다.
4. 소켓 그룹이 `docker`인지 확인한다.
5. 소켓 그룹이 다르면 `sudo systemctl restart docker` 후 다시 확인한다.

소켓 권한을 임시로 `666`으로 바꾸지 않는다.

### 10.2 sudo가 비밀번호를 요구함

`groupadd`, `usermod`, `systemctl`은 시스템 변경이므로 sudo 비밀번호가 필요한 것이 정상이다. 현재 로그인 계정의 비밀번호를 터미널에 직접 입력한다. 비밀번호 입력 중에는 화면에 문자나 `*`가 표시되지 않는다.

현재 계정에 sudo 권한이 없다면 시스템 관리자에게 다음 작업을 요청한다.

```bash
sudo usermod -aG docker "$USER"
```

### 10.3 Docker 서비스가 active가 아님

```bash
systemctl status docker --no-pager
sudo journalctl -u docker --no-pager -n 100
```

서비스 설정과 최근 오류를 확인한 뒤 다음 명령으로 다시 시작한다.

```bash
sudo systemctl restart docker
```

### 10.4 포트 3307 충돌

다음과 같은 오류가 나오면 다른 프로세스나 컨테이너가 `127.0.0.1:3307`을 사용 중이다.

```text
Bind for 127.0.0.1:3307 failed: port is already allocated
```

사용 주체를 확인한다.

```bash
ss -ltnp | rg ':3307'
docker ps --filter publish=3307
```

출력된 프로세스나 컨테이너가 필요한 서비스인지 확인한 뒤 해당 서비스의 정상 종료 절차를 사용한다. 대상을 확인하지 않고 프로세스를 강제 종료하지 않는다.

### 10.5 MySQL 컨테이너가 unhealthy임

```bash
docker compose -f compose.db_test.yaml ps
docker compose -f compose.db_test.yaml logs --no-color mysql_test
docker inspect trihouse_db_test-mysql_test-1
```

컨테이너 이름은 Compose 버전에 따라 다를 수 있다. `ps` 출력의 실제 이름을 `docker inspect`에 사용한다.

주요 원인은 다음과 같다.

- MySQL image 최초 다운로드 또는 초기화가 아직 끝나지 않음
- SQL syntax error
- CHECK 또는 FK를 위반하는 seed
- 호스트 메모리 부족
- 포트 충돌

### 10.6 SQL 초기화 실패 후 다시 검증

먼저 로그에서 최초 SQL 오류를 확인한다. 뒤쪽 오류는 최초 실패의 연쇄 결과일 수 있다.

```bash
docker compose -f compose.db_test.yaml logs --no-color mysql_test
```

스키마나 seed를 수정한 뒤 일회용 환경을 완전히 내리고 다시 시작한다.

```bash
docker compose -f compose.db_test.yaml down
docker compose -f compose.db_test.yaml up -d --wait
```

tmpfs 데이터가 새로 만들어지므로 수정된 초기화 SQL이 처음부터 다시 실행된다.

### 10.7 과거 sudo 실행으로 `$HOME/.docker` 권한이 꼬임

다음 오류가 나올 수 있다.

```text
WARNING: Error loading config file: permission denied
```

소유자를 먼저 확인한다.

```bash
ls -ld "$HOME/.docker"
```

해당 디렉터리가 root 소유이고 본인의 Docker 설정 디렉터리가 맞을 때만 소유권을 복구한다.

```bash
sudo chown -R "$USER":"$(id -gn "$USER")" "$HOME/.docker"
sudo chmod -R u+rwX,go-rwx "$HOME/.docker"
```

## 11. 빠른 성공 판정표

| 검사 | 성공 기준 |
| --- | --- |
| `id -nG "$USER"` | `docker` 포함 |
| Docker 소켓 | 일반적으로 `root docker 660` |
| `docker version` | Client와 Server 모두 출력 |
| `hello-world` | 컨테이너 실행 성공 |
| Compose `config` | 오류 없이 해석 |
| MySQL 상태 | `healthy` |
| FMS 테이블 | 17개 |
| Recovery 테이블 | 2개 |
| 개발 seed | `JOB-DEV-001`, `queued` |
| attempt 이력 | `job_step_attempts` 존재 및 주요 제약 확인 |
| 정리 | `compose.db_test.yaml ps -a`가 비어 있음 |
