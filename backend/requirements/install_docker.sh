#!/bin/bash
set -e

# 1. 기존 충돌 패키지 제거 (있다면, 없어도 에러 무시)
sudo apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

# 2. 필요한 패키지 설치
sudo apt-get update
sudo apt-get install -y ca-certificates curl

# 3. Docker 공식 GPG 키 추가
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# 4. Docker apt 저장소 추가
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 5. 설치
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 6. sudo 없이 docker 쓸 수 있게 현재 유저를 docker 그룹에 추가
sudo usermod -aG docker "$USER"

# 7. 확인
sudo docker run hello-world

echo ""
echo "설치 완료! 지금 로그인된 셸에는 docker 그룹 권한이 아직 안 붙어있어서,"
echo "터미널을 새로 열거나 로그아웃/로그인 해야 'sudo' 없이 docker 명령어를 쓸 수 있어요."
