# P0 수동 시험 절차 — 기동부터 주문·DB 확인·2 Pinky/2 OMX 시뮬레이션까지

이 문서는 **터미널에서 그대로 따라 칠 수 있는 순서**다. 각 단계마다 "무엇이
보여야 성공인지"를 함께 적었다. 확인 문구가 안 나오면 다음 단계로 넘어가지
말고 그 자리에서 멈춰야 원인을 찾기 쉽다.

## 0. 이 문서의 검증 상태 — 먼저 읽을 것

**갱신: 2026-08-17.** 2026-08-16 추가 세션에서 스택을 실제로 띄웠고, 그때
막았던 결함 20여 건을 고쳤다. 실측 기록은
`docs/validation/2026-08-16-p0-simulation.md` 3절에 있다.

| 항목 | 상태 |
|---|---|
| Docker 층 6개 서비스 기동 (`up`) | **확인** — 모두 healthy |
| 지도 발행 (staged → validated → published) | **확인** |
| 주문 → DB 실시간 반영, 운영 WebSocket | **확인** |
| ROS 층 실제 기동 (`ros`) | **확인** — 프로세스 사망 0건 |
| Gazebo 에서 두 Pinky 주행 | **확인** (단, `cmd_vel` 직접 지령) |
| `doctor` 가 모두 healthy | **확인** (당시 11개, 지금 12개) |
| Job 러너가 주문에 자원 배정 + Step dispatch | **확인** (2026-08-17, 실 DB) |
| **주문이 로봇을 실제로 출발시킴** | **미실행 — 아래 참고** |

> **8.2~8.5 는 아직 통과할 수 없다.** 공개 주문의 첫 단계가 `pick(arm)` 인데
> Gateway 의 `omx` 채널 outbox 를 소비하는 프로세스가 없다. Step 이 열리지
> 않으므로 뒤따르는 `navigate` 가 RMF 로 나가지 못한다. 원인과 범위는
> 검증 문서 3.4.2 절에 있다. **1~7절과 8.1 절은 지금 그대로 유효하다.**

막히면 10절 문제 해결표를 먼저 보고, 그래도 안 되면 `control_system` 의
같은 기능 구현을 참고하면 된다 — RMF core 구성은 이미 거기서 가져왔다
(`control_system/rmf_maps/project1/project1.launch.xml`).

---

## 1. 스택이 두 층으로 나뉘는 이유

| 층 | 무엇이 도는가 | 띄우는 명령 |
|---|---|---|
| **Docker** | MySQL, FMS Gateway, MediaMTX, RMF API/Dashboard, 관제 UI | `./scripts/control_stack up` |
| **호스트 ROS 2** | RMF core, Gazebo, Pinky×2 Nav2/fleet adapter, OMX×2, Job 러너, RMF dispatch worker | `./scripts/control_stack ros` |

ROS 쪽은 `rclpy`, DDS 멀티캐스트, GPU 가 필요해 컨테이너로 옮기지 않았다.
그래서 명령이 두 개다. 두 층을 함께 점검하는 것은 `doctor` 하나다.

> **관제 UI 와 Gateway 는 반드시 같은 origin 이어야 한다.** UI 는 Gateway 주소를
> 페이지 origin 에서 가져오고, 다른 origin 은 HTTPS + credentialed 모드가 없으면
> 예외를 던진다. 그래서 `control_ui` 컨테이너의 nginx 가 `/api/` 와 운영
> WebSocket 을 Gateway 로 reverse proxy 한다. 브라우저는 `http://127.0.0.1:3100`
> 주소 **하나만** 보면 된다.

---

## 2. 사전 준비 (최초 1회)

### 2.1 비밀번호 환경 파일

`compose.yaml` 과 `compose.control.yaml` 이 `${MYSQL_ROOT_PASSWORD}`,
`${FMS_DB_PASSWORD}` 를 요구한다.

> **저장소 루트의 `.env` 를 고치지 말 것.** `compose.db.yaml` 의 개발용
> MySQL 도 같은 `${FMS_DB_PORT}` 를 본다. P0 를 위해 `.env` 를 3308 로 바꾸면
> 개발 DB 가 다음 기동에서 같은 포트를 물고 충돌한다. 그래서 P0 는 전용
> **`.env.p0`** 만 쓴다 — `scripts/control_stack` 이 이 파일을 자동으로
> `--env-file` 로 넘긴다 (없으면 `.env` 로 되돌아간다).

```bash
cd /home/syw/Trihouse
cat > .env.p0 <<'EOF'
MYSQL_ROOT_PASSWORD=change_me_root
FMS_DB_USER=fms_gateway
FMS_DB_PASSWORD=change_me_gateway
FMS_DB_DATABASE=trihouse_fms
# 이 호스트에는 3306(개발 MySQL)과 3307(테스트 MySQL)이 이미 떠 있다.
# 겹치면 `up` 이 포트 바인딩에서 실패한다.
FMS_DB_PORT=3308
FMS_API_PORT=8080
CONTROL_UI_PORT=3100
EOF
chmod 600 .env.p0
```

쓰려는 포트가 비어 있는지 먼저 확인한다.

```bash
for port in 3308 8080 3100; do
  (timeout 2 bash -c "cat </dev/null >/dev/tcp/127.0.0.1/$port" 2>/dev/null \
     && echo "$port 사용 중 — .env.p0 에서 바꾸세요") || echo "$port 사용 가능"
done
```

`.env.p0` 는 커밋하지 않는다.

### 2.2 Docker 권한 확인

```bash
docker info >/dev/null && echo "docker OK"
```

`permission denied ... /var/run/docker.sock` 이 나오면 아래를 실행하고
**로그아웃 후 다시 로그인**한다.

```bash
sudo usermod -aG docker "$USER"
```

### 2.3 ROS 워크스페이스 빌드

**두 개의 워크스페이스가 필요하다.** `pinky_pro` 는 별도 colcon 워크스페이스라
따로 빌드하고 따로 source 한다. Pinky 의 URDF(`pinky_description`), Gazebo
world, plugin 이 거기에 있어서, 빠지면 로봇 spawn 자체가 안 된다.

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install \
  --packages-select trihouse_interfaces trihouse_rmf_bridge \
                    trihouse_pinky_bringup trihouse_pinky_fleet \
                    trihouse_pinky_safety trihouse_omx_adapter
```

성공하면 `install/setup.bash` 가 생긴다. 기동 스크립트가 이 오버레이와
`pinky_pro/install/setup.bash` 를 모두 자동으로 얹는다.

> `trihouse_pinky_bringup` 빌드가 실패하면 `build/` 에 삭제된 launch 파일을
> 가리키는 symlink 가 남은 것이다. `rm -rf build install` 후 다시 빌드한다.

### 2.4 좌표 원본 확인

P0 좌표는 **오직** 아래 파일에서만 온다. git 에 들어 있는 정본은 `control_ui/`
쪽이고, 지도 발행과 자동 테스트가 모두 이 파일을 쓴다. 13줄이어야 하고,
병목 2건은 `source_diameter_m: 0.2` / `radius_m: 0.1` 을 갖고 있어야 한다.

```bash
FEATURES=control_ui/rmf_control_ui/data/import/trihouse_test_01_physical_features.jsonl
wc -l < "$FEATURES"                              # 13
grep -c '"source_diameter_m": 0.2' "$FEATURES"   # 2
```

두 값이 맞으면 손댈 것이 없다. `control_system_test/` 아래 사본은 `.gitignore`
대상이라 새 클론에는 없을 수 있으며, 되돌아갈 자리로만 남긴다 (좌표는 동일).

---

## 3. Docker 층 기동

```bash
cd /home/syw/Trihouse
./scripts/control_stack up --mode simulation --project trihouse_test_01 --build
```

MySQL → Gateway → MediaMTX → RMF API → RMF Dashboard → 관제 UI 순서로 올라가고,
각 단계가 healthy 가 된 뒤에 다음이 시작된다. 최초 실행은 Flutter 웹 번들과
Gateway 이미지를 빌드하므로 몇 분 걸린다.

> **`--build` 를 빼면 소스 수정이 컨테이너에 반영되지 않는다.** compose 는
> 이미지가 이미 있으면 다시 빌드하지 않는다. 코드를 고친 뒤 `up` 만 다시
> 돌리면 예전 이미지가 그대로 뜬다.

확인:

```bash
./scripts/control_stack status
curl -fsS http://127.0.0.1:8080/ready          # {"status":"ready","database":"ok"}
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3100/   # 200
```

관제 UI 를 연다.

```bash
xdg-open http://127.0.0.1:3100
```

문제가 생기면:

```bash
./scripts/control_stack logs --tail 200
./scripts/control_stack logs --follow
```

---

## 4. DB 가 실시간으로 반영되는지 확인

터미널을 **두 개** 쓴다.

### 4.1 터미널 A — DB 를 계속 들여다본다

`watch` 안에서 따옴표를 중첩하면 깨지기 쉬우니 작은 스크립트를 하나 만든다.

```bash
cd /home/syw/Trihouse
cat > /tmp/trihouse_db_counts.sh <<'EOF'
#!/usr/bin/env bash
set -a; . /home/syw/Trihouse/.env.p0; set +a
docker compose --project-name trihouse_p0 exec -T mysql \
  mysql -u"$FMS_DB_USER" -p"$FMS_DB_PASSWORD" "$FMS_DB_DATABASE" -e \
  "SELECT
     (SELECT COUNT(*) FROM jobs)             AS jobs,
     (SELECT COUNT(*) FROM job_items)        AS items,
     (SELECT COUNT(*) FROM job_steps)        AS steps,
     (SELECT COUNT(*) FROM reservations)     AS reservations,
     (SELECT COUNT(*) FROM operation_events) AS events;"
EOF
chmod +x /tmp/trihouse_db_counts.sh

# 주문이 들어올 때마다 Job / Step / 예약 수가 늘어나는지 본다.
watch -n 1 /tmp/trihouse_db_counts.sh
```

### 4.2 터미널 B — 주문을 넣는다

**UI 로 넣기:** `http://127.0.0.1:3100` → 주문 화면 → 상품 추가 → 수량 입력 →
필요하면 `긴급` / `부분 출고 허용` 체크 → 제출.

**API 로 넣기 (UI 와 완전히 같은 공개 경로):**

```bash
curl -fsS -X POST http://127.0.0.1:8080/api/v1/orders \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: manual-$(date +%s)" \
  -d '{
        "external_reference": "MANUAL-ORDER-001",
        "requested_by": "W-OP-01",
        "priority": "normal",
        "allow_partial_fulfillment": false,
        "items": [
          {"product_code": "SKU-ORANGE",   "quantity": 1},
          {"product_code": "SKU-MANDARIN", "quantity": 1}
        ]
      }' | python3 -m json.tool
```

터미널 A 의 숫자가 **즉시** 올라가면 실시간 반영이 확인된 것이다.

주문 하나를 자세히 본다:

```bash
JOB_ID=17   # 위 응답의 job_id
curl -fsS "http://127.0.0.1:8080/api/v1/jobs/$JOB_ID" | python3 -m json.tool
curl -fsS "http://127.0.0.1:8080/api/v1/jobs/$JOB_ID/timeline" | python3 -m json.tool
```

구역 순서(`ambient` → `chilled` → `frozen`)와 한 구역당 Dock 방문이 한 번인지
확인한다.

### 4.3 운영 WebSocket 이 살아 있는지

관제 UI 의 운영 화면은 `/api/v1/operations/ws` 를 구독한다. 브라우저 없이
확인하려면 `websockets` 모듈이 필요하다. 이 호스트의 시스템 파이썬은
`externally-managed-environment` 라 `pip install --user` 가 막혀 있으므로
일회용 venv 를 쓴다.

```bash
python3 -m venv /tmp/trihouse-ws && /tmp/trihouse-ws/bin/pip -q install websockets
```


```bash
/tmp/trihouse-ws/bin/python - <<'PY'
import asyncio, json, websockets
async def main():
    async with websockets.connect("ws://127.0.0.1:8080/api/v1/operations/ws") as ws:
        print("connected; 새 이벤트를 기다립니다 (다른 터미널에서 주문을 넣으세요)")
        for _ in range(5):
            print(json.loads(await ws.recv())["event_type"])
asyncio.run(main())
PY
```

주문을 넣으면 `job.created` 같은 이벤트가 흘러나온다.

---

## 5. 지도 발행 — ROS 층 전에 반드시 먼저

fleet adapter 와 dispatch worker 는 **발행된 지도 revision** 을 작업 문맥으로
쓴다. 발행 없이 ROS 를 띄우면 로봇이 명령을 거절한다.

```bash
# 현재 활성 revision 확인
curl -fsS http://127.0.0.1:8080/api/v1/map-projects | python3 -m json.tool
```

`trihouse_test_01` 의 활성 revision 이 없으면 UI 의 지도 화면에서
SLAM YAML/이미지와 위 JSONL 을 올리고 **저장 → 검증 → 배포** 를 누른다.
발행된 `map_revision` 문자열을 그대로 복사해 둔다.

```bash
export TRIHOUSE_MAP_REVISION='trihouse_test_01:<복사한_해시>'
```

---

## 6. ROS 층 기동 — Pinky 2대 + OMX 2대

새 터미널에서:

```bash
cd /home/syw/Trihouse
export TRIHOUSE_MAP_REVISION='trihouse_test_01:<복사한_해시>'

# headless (기본)
./scripts/control_stack ros --mode simulation

# Gazebo 창을 보고 싶으면
./scripts/control_stack ros --mode simulation --gui

# RViz 까지 함께
./scripts/control_stack ros --mode simulation --gui --rviz
```

이 한 명령이 아래를 **함께** 띄운다.

1. Open-RMF traffic schedule
2. Gazebo + `PK_01`(`pinky_01`) / `PK_02`(`pinky_02`) 와 각자의 Nav2·fleet adapter
   — spawn pose 는 승인된 JSONL 의 충전 스테이션 기록에서만 읽는다
3. OMX 시뮬레이터 `OMX_01`, `OMX_02`
4. **Job 러너** (`trihouse_job_runner`)
5. RMF dispatch worker

Ctrl+C 한 번이면 여기서 띄운 프로세스가 모두 정리된다.

> **Job 러너와 dispatch worker 는 짝이다.** 러너가 `queued` 주문에 로봇·OMX·
> 포장 Dock·충전기를 배정하고 현재 Step 을 outbox 로 내보내면, worker 가 그
> 행을 claim 해 RMF 로 넘긴다. 러너가 없으면 worker 는 claim 할 것이 없어
> 주문이 `queued` 에서 멈춘다 (2026-08-16 세션에서 실제로 그랬다).
> 러너만 빼고 띄우려면 `--no-job-runner` 를 준다.

러너가 무엇을 하고 있는지는 로그로 바로 보인다.

```
[INFO] [trihouse_job_runner]: job runner cycle: assigned=[2, 3] dispatched=[2, 3]
[WARN] [trihouse_job_runner]: job runner blocked: job 4: no free robot, arm, or dock
```

한 주기만 돌려 보려면 (기동 없이 진단용):

```bash
python3 -m control_tower.task_manager.job_runner_node \
  --fms-base-url http://127.0.0.1:8080 --once
```

동등한 직접 실행 (스크립트를 거치지 않고 싶을 때):

```bash
control_tower/bringup/p0_simulation_bringup.sh --gui
```

---

## 7. 전체 점검

```bash
./scripts/control_stack doctor --mode simulation
```

**열두 개** 항목이 모두 `healthy` 여야 하고 종료 코드가 `0` 이다.

```json
{
  "checks": {
    "mysql": "healthy", "fms_gateway": "healthy", "control_ui": "healthy",
    "mediamtx": "healthy", "control_tower": "healthy", "rmf_schedule": "healthy",
    "gazebo": "healthy", "nav2:PK_01": "healthy", "nav2:PK_02": "healthy",
    "omx:OMX_01": "healthy", "omx:OMX_02": "healthy",
    "job_runner": "healthy"
  },
  "healthy": true,
  "layers": { "docker": [...], "host_ros": [...] }
}
```

> `sg docker` 로 새 그룹 셸을 열어 쓰는 중이라면 `doctor` 는 Docker 와 ROS 를
> 함께 본다. `sg` 는 setgid 라 `LD_LIBRARY_PATH` 를 지우므로 그 안에서 ROS 를
> 부르면 `librcl_action.so` 를 못 찾는다. 다시 넣어 줘야 한다.
>
> ```bash
> sg docker -c "LD_LIBRARY_PATH='$LD_LIBRARY_PATH' ./scripts/control_stack doctor --mode simulation"
> ```
>
> 재로그인하면 `sg` 자체가 필요 없다.

`absent` 가 남으면 어느 층인지 `layers` 로 확인한다. Docker 쪽이면
`control_stack logs`, ROS 쪽이면 `ros2 node list` 를 본다.

```bash
ros2 node list
ros2 topic list | grep -E 'pinky_0[12]'
```

---

## 8. 2 Pinky / 2 OMX 수동 시험

> **지금 어디까지 되는가.** 8.1(자원 배정)은 통과한다 — Job 러너가 실제 DB 에서
> 하는 것을 2026-08-17 에 확인했다. **8.2~8.5 는 아직 통과할 수 없다.** 공개
> 주문의 첫 단계가 `pick(arm)` → `omx` 채널인데 그 채널을 소비하는 프로세스가
> 없어서 Step 이 `pending` 에 머무르고, 순서상 뒤인 `navigate` 가 RMF 로 나가지
> 못한다. 상세는 `docs/validation/2026-08-16-p0-simulation.md` 3.4.2 절.
>
> 확인 방법 — 이 질의가 `omx` 행만 보여 주고 `rmf` 행이 없으면 그 상태다.
>
> ```bash
> set -a; . ./.env.p0; set +a
> docker compose --project-name trihouse_p0 exec -T mysql \
>   mysql -u"$FMS_DB_USER" -p"$FMS_DB_PASSWORD" "$FMS_DB_DATABASE" -e \
>   "SELECT channel, state, COUNT(*) FROM integration_messages
>      WHERE direction='outbound' GROUP BY channel, state;"
> ```

### 8.1 동시 주문 두 건 → 서로 다른 로봇에 배정

```bash
for i in 1 2; do
  curl -fsS -X POST http://127.0.0.1:8080/api/v1/orders \
    -H 'Content-Type: application/json' \
    -H "Idempotency-Key: manual-traffic-$i" \
    -d "{\"external_reference\": \"MANUAL-TRAFFIC-$i\",
         \"requested_by\": \"W-OP-01\", \"priority\": \"normal\",
         \"allow_partial_fulfillment\": false,
         \"items\": [{\"product_code\": \"SKU-ORANGE\", \"quantity\": 1}]}" \
    | python3 -c 'import sys,json; print("job_id:", json.load(sys.stdin)["job_id"])'
done
```

배정 결과 확인:

```bash
set -a; . ./.env.p0; set +a
docker compose --project-name trihouse_p0 exec -T mysql \
  mysql -u"$FMS_DB_USER" -p"$FMS_DB_PASSWORD" "$FMS_DB_DATABASE" -e \
  "SELECT job_id, assigned_mobile_id,
          JSON_UNQUOTE(JSON_EXTRACT(context,'\$.assignment.omx_id'))            AS omx,
          JSON_UNQUOTE(JSON_EXTRACT(context,'\$.assignment.packing_dock_code')) AS dock,
          JSON_UNQUOTE(JSON_EXTRACT(context,'\$.assignment.charger_code'))      AS charger
     FROM jobs ORDER BY job_id DESC LIMIT 2;"
```

**확인할 것**

- 두 Job 의 `assigned_mobile_id` 가 서로 다르다 (`PK_01` / `PK_02`).
- `omx` 가 서로 다르다 (`OMX_01` / `OMX_02`).
- `dock` 이 서로 다르다.
- 충전기가 로봇에 고정이다: `PK_01 → TRIHOUSE-TEST-01-CHG-01`,
  `PK_02 → TRIHOUSE-TEST-01-CHG-02`.

### 8.2 Gazebo 에서 실제 주행 보기

`--gui` 로 띄웠다면 Gazebo 창에서 두 Pinky 가 각자 충전 스테이션에서 출발해
적재 Dock 으로 이동한다. 관제 UI 운영 화면에서는 다음이 보여야 한다.

- Nav2 전역 경로와 **실제 이동 궤적**이 먼저 그려진다.
- `RMF 진단` 토글을 켜야 RMF 예정 궤적이 나타난다.
- 내부 bootstrap graph 는 **어떤 경우에도 보이지 않는다**.

경로/일정이 어긋나면 `PATH_SCHEDULE_MISMATCH` 배지가 뜨고 로봇은 보류된다.

### 8.3 병목 통과 (지름 0.2 m, 실행 반경 0.1 m)

두 로봇이 같은 통로로 향하게 주문을 넣으면, 먼저 도착한 로봇이 통과하고 다른
로봇은 정지한다. `긴급` 주문이어도 통과 순서는 바뀌지 않는다. 15초를 넘겨
기다리면 점유 구역을 제외한 우회 경로를 계산하고, 유효한 우회가 없으면 계속
기다린다.

```bash
ros2 topic echo /trihouse/bottleneck/lease --once 2>/dev/null || \
  echo "lease 토픽이 없으면 관제 UI 운영 화면의 대기 표시로 확인한다"
```

### 8.4 OMX 적재와 작업자 완료

OMX 시뮬레이터는 `PREPARING → PICKING → OMX_READY` 를 낸다. Pinky 가 먼저
도착해도 같은 배정 revision 의 `PINKY_READY` 와 `OMX_READY` 가 모두 모여야
적재가 시작된다.

적재가 끝나면 포장대에서 작업자 완료를 누른다. API 로도 같다.

```bash
JOB_ID=17
curl -fsS -X POST "http://127.0.0.1:8080/api/v1/jobs/$JOB_ID/worker-completion" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: manual-complete-$JOB_ID" \
  -d '{"worker_id": "W-OP-01", "completion_note": "packed",
       "acknowledged_manual_item_ids": []}' | python3 -m json.tool
```

**확인할 것**

- 재고가 정확히 한 번 확정된다 (같은 키로 다시 호출하면 첫 응답을 그대로 준다).
- 포장 Dock 이 해제된다.
- `return_home` 단계가 하나 생기고 배정된 **고정 충전기**를 가리킨다.

```bash
docker compose --project-name trihouse_p0 exec -T mysql \
  mysql -u"$FMS_DB_USER" -p"$FMS_DB_PASSWORD" "$FMS_DB_DATABASE" -e \
  "SELECT action_type, state, input FROM job_steps
    WHERE job_id=$JOB_ID AND action_type='return_home';"
```

### 8.5 비상 fixture 두 건

관제 UI 운영 화면에서 사건이 열리면 원인에 맞는 카메라가 열린다.

| fixture | 여는 카메라 |
|---|---|
| 이동 중 Pinky 전도 (`PK_01`) | `CAM-PK-01` |
| 창고 내 전도 (`WH-FRZ-01`) | `CAM-FIXED-02` |

- `비상경보 발령` → 사건 확정, 보류 유지.
- `작업 계속 진행` → 작업자·사유 기록, 보류 해제, **같은 Job** 의 Nav2 경로
  재계산 + RMF 일정 재등록.
- 대화상자를 그냥 닫으면 **아무 일도 일어나지 않는다**.

---

## 9. 정리

```bash
# ROS 층: 해당 터미널에서 Ctrl+C
# Docker 층:
./scripts/control_stack down
```

DB 볼륨까지 지우려면:

```bash
docker compose --project-name trihouse_p0 down -v
```

---

## 10. 자주 막히는 곳

| 증상 | 원인과 조치 |
|---|---|
| UI 가 흰 화면 / 설정 예외 | Gateway 를 `:8080` 으로 직접 열었다. 반드시 `:3100` 으로 접속한다. UI 는 페이지 origin 을 Gateway 로 쓰므로 nginx 를 거쳐야 한다. |
| `docker: permission denied` | 1.2 절의 `usermod -aG docker` 후 재로그인. |
| `up` 이 `mysql` 에서 멈춤 | `.env.p0` 의 `MYSQL_ROOT_PASSWORD` / `FMS_DB_PASSWORD` 가 비었다. |
| ROS 기동이 `Gateway 가 준비되지 않았습니다` 로 종료 | Docker 층을 먼저 올린다. |
| ROS 기동이 `TRIHOUSE_MAP_REVISION 이 비어 있습니다` 로 종료 | 4절에서 지도를 발행하고 revision 을 export 한다. |
| `line 9: missing field source_diameter_m` | 1.4 절의 보정 스크립트를 실행한다. |
| `doctor` 의 ROS 항목만 `absent` | 같은 셸에서 `source /opt/ros/jazzy/setup.bash` 를 했는지, `ROS_DOMAIN_ID` 가 두 터미널에서 같은지 확인한다. |
| 두 로봇이 서로의 토픽을 덮어씀 | namespace 없이 노드를 직접 띄운 경우다. 반드시 bringup 스크립트를 쓴다. |

---

## 11. 자동 검증과의 관계

이 문서는 **수동** 절차다. 같은 동작을 자동으로 확인하려면 먼저 환경을
갖춘다. Gateway 의존성(`pydantic-settings` 등)은 시스템 파이썬에 없고, 이
호스트는 `externally-managed-environment` 라 `pip install --user` 가 막혀
있으므로 저장소 안의 `.venv` 를 쓴다 (`.gitignore` 대상).

```bash
cd /home/syw/Trihouse
python3 -m venv --system-site-packages .venv       # 최초 1회
.venv/bin/pip install -r fms_gateway/requirements-dev.txt
```

`--system-site-packages` 는 ROS 의 `rclpy` 를 그대로 쓰기 위한 것이다.

DB 를 쓰는 시험은 **테스트 MySQL(:3307)** 이 떠 있어야 한다. P0 스택의
MySQL(:3308)과는 별개다.

```bash
docker compose -f compose.db_test.yaml up -d
```

그다음:

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
export FMS_DB_HOST=127.0.0.1 FMS_DB_PORT=3307 \
       FMS_DB_USER=fms_gateway FMS_DB_PASSWORD=test_gateway_password
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

.venv/bin/pytest -q db/tests control_tower/tests trihouse_rmf_bridge/test \
          trihouse_omx_adapter/tests trihouse_pinky/test vision_edge/tests \
          media tests --ignore=trihouse_rmf_bridge/test/test_office_service.py

cd fms_gateway && ../.venv/bin/pytest -q tests
```

> `pinky_pro/install/setup.bash` 를 빼면 `pinky_description` 을 못 찾아
> launch 계약 시험이 실패한다. 코드 결함이 아니라 오버레이 누락이다.

두 pytest 명령은 **같은 테스트 DB(:3307)** 를 초기화하므로 동시에 돌리면 안
된다. 운영 DB(:3306), P0 DB(:3308)와는 포트가 다르니 서로 영향을 주지 않는다.

결과 기록은 `docs/validation/2026-08-16-p0-simulation.md` 에 있다.
