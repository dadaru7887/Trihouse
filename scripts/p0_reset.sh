#!/usr/bin/env bash
# P0 시뮬레이션을 **매번 같은 상태**에서 시작하기 위한 초기화.
#
# 회차를 거듭하면 상태가 쌓여 다음 회차가 앞 회차와 달라진다. 특히:
#
#   - 구버전 Gateway에서는 job 취소 뒤 재고 예약이 남았다. 현재 취소 경로는
#     `reservation_release` 원장과 함께 되돌리지만, 이미 남아 있는 과거 예약은
#     자동으로 복구하지 못한다.
#   - 실패한 step 을 가진 job 이 `assigned` 로 남아 로봇을 쥔다.
#   - RMF dispatcher 에 살아 있는 task 는 FMS job 을 취소해도 남아, fleet adapter 가
#     `FMS command claim 실패: 409` 를 초당 수백 번 반복한다.
#
# 그래서 DB 를 schema + seed 로 되돌린다. 지도 revision 도 함께 사라지므로 다시
# 발행한다. 이 스크립트가 끝나면 어느 회차든 같은 출발선이다.
#
# 사용법
#   scripts/p0_reset.sh              기본 지도(new_map_2)
#   scripts/p0_reset.sh new_map_2    이름으로 선택
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
FMS_DB_USER="$(grep -E '^FMS_DB_USER=' .env | cut -d= -f2- || true)"
FMS_DB_USER="${FMS_DB_USER:-fms_gateway}"
if [[ ! "$FMS_DB_USER" =~ ^[a-zA-Z0-9_]+$ ]]; then
  echo "[reset] FMS_DB_USER에는 영문, 숫자, 밑줄만 사용할 수 있습니다." >&2
  exit 1
fi

# 지도는 이름으로도, yaml 경로로도 지정한다.
#   scripts/p0_reset.sh                                  기본 new_map_2
#   scripts/p0_reset.sh new_map_2                        이름
#   scripts/p0_reset.sh /절대/경로/my_map.yaml            경로
SELECTOR="${1:-${P0_MAP:-new_map_2}}"
if [[ "$SELECTOR" == *.yaml || "$SELECTOR" == */* ]]; then
  MAP_YAML="$(readlink -f "$SELECTOR" 2>/dev/null || echo "$SELECTOR")"
else
  MAP_YAML="$ROOT/pinky_pro_alpha/pinky_navigation/map/${SELECTOR}.yaml"
fi
if [[ ! -f "$MAP_YAML" ]]; then
  echo "[reset] SLAM 지도가 없습니다: $MAP_YAML" >&2
  echo "[reset] 저장소에 있는 지도:" >&2
  ls "$ROOT"/pinky_pro_alpha/pinky_navigation/map/*.yaml \
    | xargs -n1 basename | sed 's/\.yaml$//;s/^/          /' >&2
  exit 1
fi
MAP_NAME="$(basename "$MAP_YAML" .yaml)"
echo "[reset] 지도: $MAP_NAME  ($MAP_YAML)"

source "$ROOT/scripts/lib/require_docker.sh"
require_docker || exit 1
source "$ROOT/scripts/lib/p0_environment.sh"
configure_p0_simulation_environment
configure_p0_ros_domain "$ROOT/.env"

# 협로 존 표는 지도 좌표계에 묶여 있어 지도마다 따로 재야 한다. 없으면 규칙 주행이
# 통째로 꺼지고, 로봇은 Nav2 로 협로에 들어가려다 갇힌다. 여기서 미리 말해 준다.
if [[ ! -f "$ROOT/config/narrow_zones.$MAP_NAME.yaml" ]]; then
  echo "[reset] 주의: 이 지도의 협로 존 표가 없습니다 -> config/narrow_zones.$MAP_NAME.yaml" >&2
  echo "[reset]       규칙 주행이 꺼진 채로 돕니다. 실측이 끝난 지도로 도시거나," >&2
  echo "[reset]       notebooks/narrow_zone_measurement.ipynb 로 이 지도를 다시 재세요." >&2
fi

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

echo "[reset] 3/5 컨테이너 5 개를 현재 Compose 구성에 맞춥니다"

# Gateway의 지도 feature 계약은 이미지 안의 Python 코드다. 소스에서 waypoint
# 개수나 fiducial 정책을 바꾼 뒤 예전 이미지를 재사용하면 publish가 구 계약으로
# 422를 내므로, reset 때 Gateway만 먼저 현재 소스로 다시 빌드한다.
docker compose -p trihouse_p0 \
  -f compose.yaml -f compose.control.yaml \
  -f compose.edge_4060.yaml -f compose.simulation.yaml \
  build fms_gateway

# EN: Always reconcile here so removed services cannot survive as orphan containers.
# KO: 삭제된 서비스가 orphan 컨테이너로 남지 않도록 매번 현재 구성을 적용한다.
docker compose -p trihouse_p0 \
  -f compose.yaml -f compose.control.yaml \
  -f compose.edge_4060.yaml -f compose.simulation.yaml \
  up -d --remove-orphans
until curl -fsS -m 2 http://127.0.0.1:8080/ready >/dev/null 2>&1; do
  echo "[reset]     gateway 를 기다립니다..."; sleep 3
done

echo "[reset] 4/5 DB 를 schema + seed 로 되돌립니다"
docker exec -i trihouse-mysql mysql -uroot -p"$MYSQL_PW" \
  -e "DROP DATABASE IF EXISTS trihouse_fms;
      DROP DATABASE IF EXISTS trihouse_recovery;
      CREATE DATABASE trihouse_fms
      CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>/dev/null
docker exec -i trihouse-mysql mysql -uroot -p"$MYSQL_PW" trihouse_fms \
  < db/migrations/001_physical_v1_baseline.sql 2>/dev/null

# EN: Recreate the migration ledger and apply every immutable post-baseline migration.
# KO: migration 원장을 다시 만들고 기준선 이후의 불변 migration을 모두 적용한다.
docker exec -e MYSQL_ROOT_PASSWORD="$MYSQL_PW" trihouse-mysql \
  /docker-entrypoint-initdb.d/002_record_physical_baseline.sh >/dev/null
docker exec -e MYSQL_ROOT_PASSWORD="$MYSQL_PW" trihouse-mysql \
  /docker-entrypoint-initdb.d/003_apply_physical_migrations.sh >/dev/null
docker exec -i trihouse-mysql mysql -uroot -p"$MYSQL_PW" trihouse_fms \
  < db/seeds/seed_dev.sql 2>/dev/null

# EN: The Gateway uses the same runtime account for FMS and recovery ledgers.
# KO: Gateway는 FMS 원장과 recovery 원장에 같은 런타임 계정을 사용한다.
docker exec -i trihouse-mysql mysql -uroot -p"$MYSQL_PW" \
  -e "GRANT SELECT, INSERT, UPDATE, DELETE ON trihouse_recovery.* TO '$FMS_DB_USER'@'%';" \
  2>/dev/null

# Gateway 는 기동 때 스키마를 확인하고 연결 풀을 잡는다. DB 를 갈아 끼웠으므로
# 다시 띄워 예전 연결을 버리게 한다.
docker restart trihouse_p0-fms_gateway-1 >/dev/null
until curl -fsS -m 2 http://127.0.0.1:8080/ready >/dev/null 2>&1; do sleep 2; done

echo "[reset] 5/5 지도를 다시 발행합니다"
revision="$(python3 scripts/p0_publish_map.py "$MAP_YAML" | tail -1)"
if [[ "$revision" != "$MAP_NAME":* ]]; then
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
