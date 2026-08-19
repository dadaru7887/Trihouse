#!/usr/bin/env bash
# P0 시뮬레이션을 **매번 같은 상태**에서 시작하기 위한 초기화.
#
# 회차를 거듭하면 상태가 쌓여 다음 회차가 앞 회차와 달라진다. 특히:
#
#   - job 을 취소해도 **재고 예약이 돌아오지 않는다**(D2, 미수정). 두 번 취소하면
#     SKU-PORKBELLY 재고 2 개가 모두 잠겨 새 주문이 배정될 로봇도 물건도 없다.
#   - 실패한 step 을 가진 job 이 `assigned` 로 남아 로봇을 쥔다.
#   - RMF dispatcher 에 살아 있는 task 는 FMS job 을 취소해도 남아, fleet adapter 가
#     `FMS command claim 실패: 409` 를 초당 수백 번 반복한다.
#
# 그래서 DB 를 schema + seed 로 되돌린다. 지도 revision 도 함께 사라지므로 다시
# 발행한다. 이 스크립트가 끝나면 어느 회차든 같은 출발선이다.
#
# 사용법
#   scripts/p0_reset.sh              기본 지도(trihouse_map_01)
#   scripts/p0_reset.sh new_map_2    다른 SLAM 지도로
#
# 고른 지도의 yaml 경로는 `.trihouse/map_yaml` 에 적힌다. `scripts/p0_up.sh` 가 그것을
# 읽어 Nav2 에 같은 지도를 준다 — **발행한 지도와 로봇이 도는 지도가 갈라지면**
# 좌표 프레임이 어긋나 도착 판정이 구조적으로 실패한다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "[reset] .env 가 없습니다. .env.example 을 복사해 값을 채우세요." >&2
  exit 1
fi
MYSQL_PW="$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)"

# 지도는 이름으로도, yaml 경로로도 지정한다.
#   scripts/p0_reset.sh                                  기본 trihouse_map_01
#   scripts/p0_reset.sh new_map_2                        이름
#   scripts/p0_reset.sh /절대/경로/my_map.yaml            경로
SELECTOR="${1:-${P0_MAP:-trihouse_map_01}}"
if [[ "$SELECTOR" == *.yaml || "$SELECTOR" == */* ]]; then
  MAP_YAML="$(readlink -f "$SELECTOR" 2>/dev/null || echo "$SELECTOR")"
else
  MAP_YAML="$ROOT/control_ui/rmf_control_ui/data/rmf_maps/${SELECTOR}.yaml"
fi
if [[ ! -f "$MAP_YAML" ]]; then
  echo "[reset] SLAM 지도가 없습니다: $MAP_YAML" >&2
  echo "[reset] 저장소에 있는 지도:" >&2
  ls "$ROOT"/control_ui/rmf_control_ui/data/rmf_maps/*.yaml \
    | xargs -n1 basename | sed 's/\.yaml$//;s/^/          /' >&2
  exit 1
fi
MAP_NAME="$(basename "$MAP_YAML" .yaml)"
echo "[reset] 지도: $MAP_NAME  ($MAP_YAML)"

echo "[reset] 1/5 시뮬레이션을 내립니다"
scripts/sim_teardown.sh >/dev/null 2>&1 || true

# teardown 은 pytest 를 일부러 살려 두므로 남는 것이 생긴다. 나이를 보고 오래된
# 것만 고른다 — 일괄로 죽이면 방금 띄운 것까지 함께 죽는다.
leftover="$(ps -eo pid,etimes,args | grep -E 'trihouse|gz sim' | grep -v grep \
  | awk '$2 > 120 {print $1}' || true)"
if [[ -n "$leftover" ]]; then
  echo "[reset]     잔류 프로세스 정리: $(echo "$leftover" | tr '\n' ' ')"
  echo "$leftover" | xargs -r kill 2>/dev/null || true
  sleep 3
fi

echo "[reset] 2/5 런타임 큐를 비웁니다"
rm -f .trihouse/p0/pinky_0*_task_events.sqlite3

echo "[reset] 3/5 컨테이너 6 개를 확인합니다"
running="$(docker ps --format '{{.Names}}' | grep -cE 'trihouse-mysql|trihouse_p0-' || true)"
if [[ "$running" -lt 6 ]]; then
  echo "[reset]     $running 개만 떠 있습니다. 올립니다."
  docker compose -p trihouse_p0 \
    -f compose.yaml -f compose.control.yaml \
    -f compose.edge_4060.yaml -f compose.simulation.yaml up -d
fi
until curl -fsS -m 2 http://127.0.0.1:8080/ready >/dev/null 2>&1; do
  echo "[reset]     gateway 를 기다립니다..."; sleep 3
done

echo "[reset] 4/5 DB 를 schema + seed 로 되돌립니다"
docker exec -i trihouse-mysql mysql -uroot -p"$MYSQL_PW" \
  -e "DROP DATABASE IF EXISTS trihouse_fms; CREATE DATABASE trihouse_fms
      CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>/dev/null
docker exec -i trihouse-mysql mysql -uroot -p"$MYSQL_PW" trihouse_fms \
  < db/schema_mysql.sql 2>/dev/null
docker exec -i trihouse-mysql mysql -uroot -p"$MYSQL_PW" trihouse_fms \
  < db/seed_dev.sql 2>/dev/null

# Gateway 는 기동 때 스키마를 확인하고 연결 풀을 잡는다. DB 를 갈아 끼웠으므로
# 다시 띄워 예전 연결을 버리게 한다.
docker restart trihouse_p0-fms_gateway-1 >/dev/null
until curl -fsS -m 2 http://127.0.0.1:8080/ready >/dev/null 2>&1; do sleep 2; done

echo "[reset] 5/5 지도를 다시 발행합니다"
revision="$(python3 scripts/p0_publish_map.py "$MAP_YAML" | tail -1)"
if [[ "$revision" != trihouse_test_01:* ]]; then
  echo "[reset] 지도 발행에 실패했습니다: $revision" >&2
  exit 1
fi
mkdir -p .trihouse
printf '%s\n' "$revision" > .trihouse/map_revision
printf '%s\n' "$MAP_YAML" > .trihouse/map_yaml

echo
echo "[reset] 완료."
echo "         지도     : $MAP_NAME"
echo "         yaml     : $MAP_YAML"
echo "         revision : $revision"
echo "[reset] 이어서: scripts/p0_up.sh"
