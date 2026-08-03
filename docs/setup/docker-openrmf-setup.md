# Docker · Open-RMF 설치 가이드

> **이 문서는 신규 작성분이다.**
> `control_system/openrmf`에는 Docker와 Open-RMF의 **설치 절차가 없다.**
> [OPENRMF_APP_RUN_GUIDE.md](../../control_system/openrmf/docs/OPENRMF_APP_RUN_GUIDE.md)와
> [openrmf/README.md](../../control_system/openrmf/README.md)는 "Ubuntu 24.04, ROS 2 Jazzy,
> 빌드된 `~/rmf_ws`, Docker"를 **이미 갖춰진 전제 조건으로 나열**할 뿐이며, 저장소가 제공하는
> 설치 관련 명령은 권한 오류 대응용 `sudo usermod -aG docker "$USER"` 한 줄뿐이다.
> 따라서 아래 설치 절차는 기존 문서를 옮긴 것이 아니라 이 문서에서 새로 정의한 것이다.
> 저장소가 이미 정의한 것은 **실행 방법**(3장)과 **경로 규약**뿐이며, 그 부분은 원문을 따른다.

대상 장비: **Ubuntu 24.04.4 LTS (noble) / aarch64 / QEMU 게스트 / 4 vCPU / RAM 3.8 GiB**
관련 문서: [openrmf_app 실행 가이드](../../control_system/openrmf/docs/OPENRMF_APP_RUN_GUIDE.md) · [FMS Gateway Setup](fms-gateway-setup.md) · [DB 가이드라인](../db_schema/db_guideline.md)

모든 `sudo` 명령은 비밀번호 입력이 필요하다.

---

## 0. Docker만으로는 Open-RMF가 실행되지 않는다

Docker가 담당하는 것은 웹 계층뿐이다. Open-RMF 본체는 호스트의 ROS 2에서 돈다.

| 구성요소 | 실행 위치 | 조달 방법 | 현재 상태 |
| --- | --- | --- | --- |
| rmf-web API 서버 | **Docker** | `ghcr.io/open-rmf/rmf-web/api-server:jazzy` pull | Docker 미설치 |
| rmf-web 대시보드 | **Docker** | [Dockerfile](../../control_system/openrmf/docker/rmf-web-dashboard/Dockerfile)로 로컬 빌드 | Docker 미설치 |
| Open-RMF 전체 (traffic, task, fleet adapter, demos) | **호스트 ROS 2 Jazzy** | `~/rmf_ws` 소스 빌드 | 미설치 |
| Gazebo Harmonic + ros_gz | 호스트 | apt | **설치됨** |
| Flutter Linux desktop | 호스트 | — | **설치됨** (3.44.8) |
| Trihouse FMS MySQL | Docker (`compose.yaml`) | 이미지 pull | 현재 로컬 mysqld로 대체 운영 중 |

[run_office_web.sh:48](../../control_system/openrmf/scripts/run_office_web.sh#L48)은 `$RMF_WS/install/setup.bash`가 없으면 **즉시 중단**한다. Docker를 설치해도 workspace가 없으면 스크립트가 실행되지 않는다.

### 왜 apt 바이너리가 아니라 소스 빌드인가

저장소의 스크립트가 `$RMF_WS/install/` 아래의 **구체적인 경로로 프로세스를 식별**하기 때문이다.

| 위치 | 참조 경로 |
| --- | --- |
| [run_office_flutter.sh:102](../../control_system/openrmf/scripts/run_office_flutter.sh#L102) | `$RMF_WS/install/rmf_demos_fleet_adapter/lib/rmf_demos_fleet_adapter/fleet_manager.*` |
| [run_office_flutter.sh:107](../../control_system/openrmf/scripts/run_office_flutter.sh#L107) | `$RMF_WS/install/rmf_demos_fleet_adapter/lib/rmf_demos_fleet_adapter/fleet_adapter.*` |
| [stop_office.sh:108](../../control_system/openrmf/scripts/stop_office.sh#L108) | `gz sim.*$RMF_WS/install/rmf_demos_maps/share/rmf_demos_maps/maps/office/office.world` |

`ros-jazzy-rmf-demos-fleet-adapter`를 apt로 설치하면 프로세스가 `/opt/ros/jazzy/lib/...`에서 실행되어 이 패턴과 어긋난다. 그러면 [stop_office.sh](../../control_system/openrmf/scripts/stop_office.sh)가 fleet manager와 Gazebo를 **종료하지 못하고 남긴다.** 다음 실행에서 `127.0.0.1:22011 address already in use`가 발생한다.

또한 `rmf_demos`, `rmf_demos_gz`, `rmf_demos_maps`는 이 장비의 apt 인덱스에 **바이너리가 아예 없다**(확인함). office 시뮬레이션에 반드시 필요한 세 패키지다.

### 현재 장비의 확인된 상태

```text
OS            Ubuntu 24.04.4 LTS (noble), aarch64, QEMU 게스트, 4 vCPU
커널          6.17.0-40-generic  (overlay 모듈 존재, cgroup v2)
ROS 2         /opt/ros/jazzy 설치됨 (RMF 패키지는 없음)
Gazebo        gz-harmonic 1.0.0, ros-jazzy-ros-gz 1.0.22 설치됨
빌드 도구      colcon / rosdep(초기화됨) / vcs / git / wget / curl 모두 있음
Flutter       3.44.8 (/home/luna/develop/flutter)
Docker        미설치
~/rmf_ws      없음
메모리        RAM 3.8 GiB + swap 3.8 GiB (/swap.img, 약 2 GiB 사용 중)
디스크        루트 파티션 여유 약 30 GB
```

---

## 1. Docker Engine 설치

Ubuntu 저장소의 `docker.io`가 아니라 **Docker 공식 저장소**를 쓴다. `docker compose` v2 플러그인이 공식 저장소에만 있고, [run_office_web.sh](../../control_system/openrmf/scripts/run_office_web.sh)와 [compose.yaml](../../compose.yaml)이 모두 v2를 전제한다.

### 1.1 충돌 패키지 제거

```bash
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
  sudo apt-get remove -y "$pkg"
done
```

설치된 적이 없으면 "찾을 수 없음" 메시지가 나오는 것이 정상이다.

### 1.2 저장소 키 등록

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

### 1.3 저장소 추가

```bash
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu \
$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
```

이 장비에서 위 명령은 `arch=arm64`, 코드명 `noble`로 전개된다. `apt-get update` 출력에 `download.docker.com ... noble/stable arm64` 줄이 보이는지 확인한다.

### 1.4 설치

```bash
sudo apt-get install -y \
  docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
```

### 1.5 서비스 확인

```bash
sudo systemctl enable --now docker
systemctl is-active docker      # active
```

### 1.6 사용자 그룹 등록

저장소 문서가 지시하는 유일한 설치 관련 명령이다 ([OPENRMF_APP_RUN_GUIDE.md:39](../../control_system/openrmf/docs/OPENRMF_APP_RUN_GUIDE.md#L39)). 이 단계를 건너뛰면 [run_office_web.sh:52](../../control_system/openrmf/scripts/run_office_web.sh#L52)의 `docker info` 검사가 실패한다.

```bash
sudo usermod -aG docker "$USER"
```

**그룹 변경은 새 로그인 세션부터 적용된다.** 로그아웃 후 재로그인하거나, 현재 셸에만 즉시 적용하려면:

```bash
newgrp docker
```

> `docker` 그룹은 root 권한과 사실상 동등하다. 넣는 사용자를 최소로 유지한다.

### 1.7 검증

```bash
id -nG | tr ' ' '\n' | grep -x docker    # docker 가 출력되어야 한다
docker version                            # Client / Server 둘 다
docker compose version                    # v2.x
docker run --rm hello-world
docker info --format '{{.Driver}} {{.CgroupVersion}} {{.Architecture}}'
```

기대값: `overlay2 2 aarch64`.

`permission denied ... docker.sock`으로 실패하면 1.6의 재로그인이 안 된 것이다.

---

## 2. Open-RMF 설치 (`~/rmf_ws` 소스 빌드)

### 2.1 빌드 전 준비 — 이 장비에서는 필수

RAM 3.8 GiB에서 Open-RMF 전체를 빌드한다. `rmf_traffic`과 `rmf_fleet_adapter`는 C++ 템플릿이 무거워 컴파일 단위 하나가 GB 단위 메모리를 쓴다. **swap을 먼저 늘리지 않으면 OOM으로 중단될 가능성이 높다.**

현재 swap은 3.8 GiB이고 이미 약 2 GiB가 사용 중이다. 8 GiB로 늘린다.

```bash
sudo swapoff /swap.img
sudo fallocate -l 8G /swap.img
sudo chmod 600 /swap.img
sudo mkswap /swap.img
sudo swapon /swap.img
swapon --show          # SIZE 8G 확인
```

디스크 여유가 30 GB이므로 8 GiB swap 확보 후에도 빌드 공간이 남는다.

### 2.2 소스 내려받기

```bash
mkdir -p ~/rmf_ws/src
cd ~/rmf_ws
wget https://raw.githubusercontent.com/open-rmf/rmf/main/rmf.repos
```

**`rmf.repos`가 Jazzy 대상인지 먼저 확인한다.** `open-rmf/rmf` 저장소는 배포판별 브랜치를 두는 경우가 있고, `main`은 최신 개발 배포판을 향할 수 있다. 내려받은 파일의 `version:` 항목을 확인하고, Jazzy용 브랜치가 따로 있으면 그쪽을 쓴다.

```bash
grep -E "version:|url:" rmf.repos | head -20

# Jazzy 전용 브랜치가 있는 경우 예시
# wget https://raw.githubusercontent.com/open-rmf/rmf/jazzy/rmf.repos
```

```bash
vcs import src < rmf.repos
```

### 2.3 의존성 설치

```bash
source /opt/ros/jazzy/setup.bash
cd ~/rmf_ws

sudo rosdep init 2>/dev/null || true    # 이미 초기화되어 있으면 무시됨
rosdep update
rosdep install --from-paths src --ignore-src -y --rosdistro jazzy
```

`rosdep`은 이 장비에서 이미 초기화되어 있다(`/etc/ros/rosdep/sources.list.d/20-default.list` 존재).

### 2.4 빌드

**병렬도를 1로 낮춘다.** 4 vCPU가 있지만 기본 병렬 빌드는 이 메모리에서 확실히 실패한다.

```bash
cd ~/rmf_ws
source /opt/ros/jazzy/setup.bash

MAKEFLAGS="-j1" colcon build \
  --executor sequential \
  --parallel-workers 1 \
  --cmake-args -DCMAKE_BUILD_TYPE=Release
```

- `--executor sequential` — 패키지를 하나씩 빌드
- `MAKEFLAGS="-j1"` — 패키지 내부 컴파일도 단일 작업
- `-DCMAKE_BUILD_TYPE=Release` — 디버그 심볼을 만들지 않아 메모리와 디스크를 크게 아낀다

**수 시간이 걸린다.** 중단되면 이어서 다시 실행하면 완료된 패키지는 건너뛴다. 특정 패키지에서 반복 실패하면 그 패키지만 지정해 재시도한다.

```bash
MAKEFLAGS="-j1" colcon build --packages-select rmf_traffic \
  --cmake-args -DCMAKE_BUILD_TYPE=Release
```

빌드 중 메모리 상황은 다른 터미널에서 확인한다.

```bash
watch -n 5 free -h
```

### 2.5 검증

실행 가이드 1장이 확인하는 항목과 동일하다.

```bash
source /opt/ros/jazzy/setup.bash
source ~/rmf_ws/install/setup.bash

ros2 pkg prefix rmf_demos_gz
ros2 pkg prefix rmf_demos_fleet_adapter
```

두 명령이 `~/rmf_ws/install/...` 아래 경로를 출력해야 한다. `/opt/ros/jazzy/...`가 나오면 apt 바이너리가 잡힌 것이고, 0장에서 설명한 스크립트 경로 불일치가 발생한다.

스크립트가 실제로 참조하는 파일도 함께 확인한다.

```bash
ls ~/rmf_ws/install/rmf_demos_fleet_adapter/lib/rmf_demos_fleet_adapter/
ls ~/rmf_ws/install/rmf_demos_maps/share/rmf_demos_maps/maps/office/office.world
```

---

## 3. 실행

여기서부터는 저장소가 이미 정의한 절차다. 상세는 [OPENRMF_APP_RUN_GUIDE.md](../../control_system/openrmf/docs/OPENRMF_APP_RUN_GUIDE.md) 2장·3장을 따른다.

원문의 `/home/gyi/robosapiens`는 이전 장비 기준 경로다. 이 저장소에서는 스크립트가 `control_system/` 아래에 있다.

```bash
cd /home/luna/trihouse/Trihouse/control_system

./openrmf/scripts/run_office_web.sh        # 웹 대시보드 http://localhost:3000
./openrmf/scripts/run_office_flutter.sh    # Flutter 관제 앱
./openrmf/scripts/stop_office.sh           # 종료
```

스크립트는 자신의 위치를 기준으로 경로를 계산하므로(`ROOT_DIR = scripts/../..`) 저장소 위치가 달라도 동작한다. 확인 결과 `control_system/openrmf/docker/rmf-web-dashboard`를 정상적으로 가리킨다.

workspace가 `~/rmf_ws`가 아니면 넘긴다.

```bash
RMF_WS=/path/to/rmf_ws ./openrmf/scripts/run_office_web.sh
```

---

## 4. 이 장비에서 예상되는 제약

### 4.1 대시보드 이미지 빌드 (메모리)

`run_office_web.sh`는 첫 실행 때 [Dockerfile](../../control_system/openrmf/docker/rmf-web-dashboard/Dockerfile)로 대시보드를 빌드한다. pnpm + Node 20 번들링 단계가 메모리를 많이 쓴다.

실패 시 대응 순서:

1. 빌드 중 Gazebo·Flutter·브라우저를 모두 종료한다.
2. 2.1에서 늘린 swap이 적용됐는지 확인한다 (`swapon --show`).
3. Node 힙 상한을 낮춰 재시도한다. Dockerfile의 build 스테이지에 추가한다.
   ```dockerfile
   ENV NODE_OPTIONS=--max-old-space-size=2048
   ```
4. 그래도 실패하면 **메모리가 넉넉한 장비에서 만들어 옮긴다.**
   ```bash
   # 빌드 장비에서
   docker build -t robosapiens-rmf-dashboard:0.3.0 \
     control_system/openrmf/docker/rmf-web-dashboard
   docker save robosapiens-rmf-dashboard:0.3.0 | gzip > dashboard.tar.gz

   # 이 장비에서
   gunzip -c dashboard.tar.gz | docker load
   docker image inspect robosapiens-rmf-dashboard:0.3.0
   ```

이미지가 한 번 만들어지면 재사용하므로 이 부담은 최초 1회다. 원문 문서도 같은 확인 명령을 안내한다.

### 4.2 Gazebo 렌더링 (QEMU)

QEMU 게스트라 GPU 가속이 없다. Gazebo는 소프트웨어 렌더링으로 동작해 매우 느리다. 시뮬레이션 창이 꼭 필요하지 않으면 headless로 실행한다.

```bash
RMF_HEADLESS=true ./openrmf/scripts/run_office_web.sh
```

웹 대시보드 지도는 브라우저 WebGL을 쓰므로 Gazebo headless와 무관하게 표시된다.

### 4.3 디스크

여유 약 30 GB 기준 대략적인 소요량이다.

| 항목 | 대략 |
| --- | --- |
| swap 확장 (3.8 → 8 GiB) | +4 GB |
| Docker Engine + 기본 이미지 | 1 GB 미만 |
| `api-server:jazzy` 이미지 | 1~2 GB |
| 대시보드 빌드 (중간 레이어 포함) | 2~4 GB |
| `~/rmf_ws` 소스 + Release 빌드 | 3~6 GB |

정리 명령:

```bash
docker builder prune          # 빌드 캐시
docker image prune            # 태그 없는 이미지
rm -rf ~/rmf_ws/build         # colcon 중간 산출물 (install 은 유지)
```

### 4.4 포트

| 포트 | 용도 |
| --- | --- |
| 3000 | rmf-web 대시보드 |
| 8000 | rmf-web API |
| 8006 | trajectory server (선택) |
| 22011 | office fleet manager |
| 3306 / 3307 | Trihouse FMS MySQL (개발 / 테스트) |

MySQL 포트와 겹치지 않는다. 사용 중인지 확인:

```bash
ss -ltnp | grep -E ':(3000|8000|8006|22011)\b'
```

---

## 5. Docker 설치 후 FMS 쪽에서 달라지는 것

Docker가 준비되면 현재 로컬 mysqld로 대체 운영 중인 개발 DB를 [compose.yaml](../../compose.yaml) 경로로 되돌릴 수 있다.

```bash
cd /home/luna/trihouse/Trihouse
docker compose up -d --wait mysql
docker compose -p trihouse-test -f compose.test.yaml up -d --wait mysql-test
```

전환 시 확인할 것:

- `.env`의 `FMS_DB_PORT=3306`이 compose 노출 포트와 같다. **로컬 mysqld를 먼저 정지해야 충돌하지 않는다.**
  ```bash
  /home/luna/develop/mysql-local/usr/bin/mysqladmin \
    --socket=/home/luna/develop/trihouse-mysql/run/mysql.sock \
    -uroot -p shutdown
  ```
- compose의 초기화 스크립트는 **데이터 볼륨이 비어 있을 때만** 실행된다. 기존 데이터를 옮기려면 `mysqldump`로 내보내 적재한다.
- MySQL 버전이 로컬 8.0.46 → compose 8.4로 올라간다. 스키마가 쓰는 기능(CHECK, 생성 컬럼, 내림차순 인덱스, `SKIP LOCKED`)은 양쪽 모두 지원한다.
- [DB 가이드라인 §2.2](../db_schema/db_guideline.md)의 `fms_internal` / `fms_edge` 네트워크 분리를 이 시점에 적용한다.

---

## 6. 롤백

> 아래 절차는 DB만 재시작하거나 초기화하는 명령이 아니다.
> `docker system prune -a`, `/var/lib/docker` 삭제는 호스트의 **모든 Docker 프로젝트**에
> 영향을 주고, `~/rmf_ws` 삭제는 Open-RMF 빌드 작업 공간 전체를 제거한다. 다른
> 컨테이너·이미지·볼륨과 필요한 RMF 소스가 없는지 확인한 경우에만 항목별로 실행한다.

```bash
# 컨테이너/이미지 정리
docker compose down
docker system prune -a

# Docker 제거
sudo apt-get purge -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo rm -rf /var/lib/docker /var/lib/containerd
sudo rm -f /etc/apt/sources.list.d/docker.list /etc/apt/keyrings/docker.asc
sudo gpasswd -d "$USER" docker

# Open-RMF workspace 제거
rm -rf ~/rmf_ws

# swap 원복
sudo swapoff /swap.img
sudo fallocate -l 4G /swap.img
sudo chmod 600 /swap.img && sudo mkswap /swap.img && sudo swapon /swap.img
```
