#!/usr/bin/env bash
# P0 시뮬레이션 기동 + 판정. `scripts/p0_reset.sh` 다음에 쓴다.
#
# 지도 revision 은 **DB 에 발행된 값을 직접 읽는다.** 손으로 export 하다가
# 자리표시자 문자열을 그대로 넘기거나, 파일에 적어 둔 값이 재발행 뒤 한 세대
# 뒤처져 bringup 이 `발행된 지도 revision 이 요청과 다릅니다` 로 죽는 사고가
# 반복됐다. 원장이 정본이므로 거기서 읽으면 어긋날 자리가 없다.
#
# bringup 은 `setsid` 로 띄워 이 창을 닫아도 살아 있게 한다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "[up] .env 가 없습니다." >&2
  exit 1
fi
MYSQL_PW="$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)"

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/require_docker.sh"
require_docker || exit 1

# EN: The reset marker binds the published revision to the exact Nav2 map source.
# KO: reset 마커를 먼저 읽어 발행 revision과 Nav2 지도 원본을 같은 지도에 묶는다.
if [[ ! -s .trihouse/map_yaml ]]; then
  echo "[up] .trihouse/map_yaml 이 없습니다. 먼저 scripts/p0_reset.sh 를 돌리세요." >&2
  exit 1
fi
NAV2_MAP="$(cat .trihouse/map_yaml)"
if [[ ! -f "$NAV2_MAP" ]]; then
  echo "[up] SLAM 지도가 없습니다: $NAV2_MAP" >&2
  exit 1
fi
MAP_NAME="$(basename "$NAV2_MAP" .yaml)"

REVISION="$(docker exec trihouse-mysql mysql -uroot -p"$MYSQL_PW" -N -B -e \
  "SELECT map_revision FROM trihouse_fms.map_revisions
   WHERE state='published' ORDER BY published_at DESC LIMIT 1;" 2>/dev/null || true)"

if [[ "$REVISION" != "$MAP_NAME":* ]]; then
  echo "[up] 발행된 지도 revision 이 없습니다. 먼저 scripts/p0_reset.sh 를 돌리세요." >&2
  exit 1
fi

# reset 이 적어 둔 값과 다르면 그 사이에 누가 다시 발행한 것이다. 원장을 따르되
# 어긋났다는 사실은 남긴다.
if [[ -s .trihouse/map_revision ]] && [[ "$(cat .trihouse/map_revision)" != "$REVISION" ]]; then
  echo "[up] 주의: .trihouse/map_revision 이 원장과 다릅니다. 원장 값을 씁니다."
fi
mkdir -p .trihouse && printf '%s\n' "$REVISION" > .trihouse/map_revision

if ps -eo args | grep -q '[p]0_simulation_bringup.sh'; then
  echo "[up] 이미 bringup 이 돌고 있습니다. scripts/p0_reset.sh 부터 하세요." >&2
  exit 1
fi

echo "[up] 지도 revision: $REVISION"

echo "[up] 지도: $MAP_NAME  ($NAV2_MAP)"

# Nav2 지도와 RMF graph waypoint는 반드시 같은 지도 좌표계여야 한다. 기본 파일은
# trihouse_map_01에서 측정한 값이므로 new_map_2를 선택했을 때 fallback하지 않는다.
FEATURES_FILE="control_ui/rmf_control_ui/data/import/trihouse_test_01_physical_features.${MAP_NAME}.jsonl"
if [[ ! -f "$FEATURES_FILE" ]]; then
  echo "[up] 지도 '$MAP_NAME' 전용 waypoint 파일이 없습니다: $FEATURES_FILE" >&2
  echo "     scripts/rebuild_new_map_2.py 등으로 해당 지도 좌표계를 준비하세요." >&2
  exit 1
fi

# 아래 줄 이음(\) 사이에 주석을 끼워 넣지 말 것. `\` 다음 줄이 `#` 로 시작하면
# 거기서 명령이 끝나 `env` 가 환경변수만 출력하고 bringup 이 실행되지 않는다.

setsid nohup env \
  TRIHOUSE_MAP_REVISION="$REVISION" \
  TRIHOUSE_ROBOTS=PK_01 \
  TRIHOUSE_NAV2_MAP="$NAV2_MAP" \
  PHYSICAL_FEATURES_FILE="$FEATURES_FILE" \
  ROS_DOMAIN_ID=0 \
  control_tower/bringup/p0_simulation_bringup.sh > /tmp/sim.log 2>&1 &
disown
echo "[up] 띄웠습니다. 진행은 tail -f /tmp/sim.log"

# bringup 의 "올라왔습니다" 는 하위 launch 가 죽어도 찍힌다. 측정값으로 판정한다.
echo "[up] 최대 180 초까지 Nav2 lifecycle 을 기다립니다"
for _ in $(seq 1 60); do
  [[ "$(grep -ac 'Managed nodes are active' /tmp/sim.log || true)" -ge 2 ]] && break
  sleep 3
done

active="$(grep -ac 'Managed nodes are active' /tmp/sim.log || true)"
aborted="$(grep -ac 'Failed to bring up all requested nodes' /tmp/sim.log || true)"
claim="$(grep -ac 'FMS command claim 실패' /tmp/sim.log || true)"

echo
printf '%-34s %s (기대 2)\n'  "Nav2 lifecycle 활성"        "$active"
printf '%-34s %s (기대 0)\n'  "lifecycle 중단"             "$aborted"
printf '%-34s %s (기대 0)\n'  "FMS command claim 실패"     "$claim"

# 라이다는 이 스택의 급소다. 센서가 없으면 AMCL 이 map->odom 을 못 내고
# global_costmap 이 활성화에 실패해 navigation lifecycle 전체가 주저앉는다.
scan="없음"
if command -v gz >/dev/null 2>&1; then
  gz topic -i -t /pinky_01/scan 2>/dev/null | grep -q 'Publishers' && scan="있음"
fi
printf '%-34s %s (기대 있음)\n' "라이다 발행자" "$scan"

echo
if [[ "$active" -ge 2 && "$aborted" -eq 0 && "$scan" == "있음" ]]; then
  echo "[up] 판정 PASS — 터미널 2(tf_relay), 3(rviz2) 로 넘어가세요."
else
  echo "[up] 판정 FAIL — 아래를 읽으세요."
  echo "     grep -aE '\[(ERROR|WARN)\]' /tmp/sim.log | tail -30 | cut -c1-200"
  exit 1
fi
