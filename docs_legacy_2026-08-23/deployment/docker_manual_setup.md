# Docker 수동 설치 가이드

이 문서는 Ubuntu 24.04 사용자가 자동화 스크립트를 실행하기 전에 Docker 설치가
무엇을 바꾸는지 이해하도록 돕는다. Docker는 시스템에 설치되므로 설치 명령은 어느
경로에서도 실행할 수 있다. Compose 명령은 저장소 루트 `/home/syw/Trihouse`에서
실행한다.

## 개념

- Engine: 컨테이너를 생성·실행하는 호스트 서비스
- image: 애플리케이션과 의존성을 묶은 읽기 전용 원본
- container: image에서 생성된 실행 인스턴스
- volume: 컨테이너를 다시 만들어도 남는 데이터
- Compose: 여러 container·network·volume 선언을 YAML로 관리하는 기능

GPU가 없어도 DB/control Compose 작성과 정적 검증은 가능하다. GPU 컨테이너를
실행하는 4060·5080에는 별도로 NVIDIA driver와 NVIDIA Container Toolkit이 필요하다.

## Ubuntu 24.04 설치

```bash
# 운영체제와 충돌 패키지 확인
lsb_release -a
dpkg --print-architecture
dpkg -l | grep -E 'docker|containerd|runc|podman' || true

# HTTPS 도구와 Docker 서명키 준비
sudo apt update
sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

```bash
# Docker 공식 stable 저장소 등록
sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
apt-cache policy docker-ce
```

```bash
# Engine, CLI, runtime, build 및 Compose V2 설치
sudo apt install docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin

# 서비스와 실제 container 실행 검증
sudo systemctl status docker --no-pager
sudo docker version
sudo docker compose version
sudo docker run --rm hello-world
```

## 일반 사용자 권한

```bash
sudo usermod -aG docker "$USER"
newgrp docker
groups
docker version
docker compose version
docker ps
```

`docker` 그룹은 사실상 관리자 권한이다. 공유 서버에서는 배포 담당 계정만 그룹에
넣고, 일반 사용자는 실행된 UI/API에 접속한다.

## 프로젝트 실행 전 확인

```bash
cd /home/syw/Trihouse
cp --update=none .env.example .env
chmod 600 .env
docker compose -f compose.db.yaml config --quiet
docker compose -f compose.db_test.yaml config --quiet
docker compose -f compose.control.yaml config --quiet
docker compose -f compose.simulation.yaml config --quiet
docker compose -f compose.edge_4060.yaml config --quiet
docker compose -f compose.ai_5080.yaml config --quiet
```

비밀번호는 `.env`에만 두고 Git에 올리지 않는다. `docker compose down`은 container와
network만 내리며 named volume은 보존한다. `down --volumes`는 DB 초기화를 명시적으로
승인했을 때만 사용한다.

## 롤백

Docker를 중지하려면 `sudo systemctl stop docker`를 사용한다. 패키지 제거와
`/var/lib/docker` 삭제는 서로 다른 작업이다. volume 삭제는 DB 복구가 어려우므로
목록과 백업을 확인하지 않고 수행하지 않는다.
