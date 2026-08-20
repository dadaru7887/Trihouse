# docker 에 말을 걸 수 있는지 확인한다. 없으면 왜 안 되는지까지 말하고 끝낸다.
#
# `docker` 명령이 실패하는 것과 "컨테이너가 안 떠 있는 것"은 전혀 다른 상황이다.
# 구분하지 않으면 권한 오류가 "지도가 발행 안 됨" 이나 "0 개 떠 있음" 으로 둔갑해
# 엉뚱한 곳을 고치게 된다(2026-08-19 실제로 그랬다).
#
#   source "$(dirname "${BASH_SOURCE[0]}")/lib/require_docker.sh"
require_docker() {
  if docker ps >/dev/null 2>&1; then
    return 0
  fi
  echo "[docker] docker 에 접근할 수 없습니다." >&2
  if ! command -v docker >/dev/null 2>&1; then
    echo "[docker] docker 가 설치돼 있지 않습니다." >&2
    return 1
  fi
  if id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
    echo "[docker] 계정은 docker 그룹에 있지만 **이 로그인 세션이 그 그룹을 안 들고 있습니다.**" >&2
    echo "[docker] 그룹은 로그인할 때 붙습니다. 이 터미널에서 먼저:" >&2
    echo "[docker]     newgrp docker" >&2
    echo "[docker] 매번 하기 싫으면 로그아웃 후 다시 로그인하면 영구히 붙습니다." >&2
  else
    echo "[docker] 계정이 docker 그룹에 없습니다:" >&2
    echo "[docker]     sudo usermod -aG docker $USER" >&2
    echo "[docker] 그 뒤 로그아웃 후 다시 로그인하세요." >&2
  fi
  return 1
}
