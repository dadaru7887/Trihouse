# P0 Step 0 — 주문·재고 예약·위치·자원 할당 확인

이 문서는 주문을 만든 뒤 Pinky나 OMX를 **움직이지 않고** 다음 상태를 한 번에
확인하는 절차다.

```text
주문 HTTP 요청
→ 재고 lot 선택·예약
→ 보관 위치 연결
→ Step 10~70 생성
→ Pinky·OMX·포장 도크 할당·예약
```

Step 0이 끝났다고 주행 준비가 끝난 것은 아니다. 실제 Pinky 주행은 이 문서의
마지막 Gate를 통과한 뒤 [p0-hardware-camera-gated-run.md](p0-hardware-camera-gated-run.md)의
Gate 3~8에서 시작한다.

## 시작 전 규칙

- `POST /orders`, `POST /cancel`, `POST /assignment`은 DB 상태를 바꾼다.
- 이 문서에서는 `job_runner_node`, `executor_worker_node`,
  `rmf_gateway_worker_node`를 실행하지 않는다. 따라서 Step 10이나 Step 20이
  dispatch되지 않고 실물 로봇도 움직이지 않는다.
- MySQL 비밀번호 경고는 컨테이너 내부 환경변수로 접속할 때 표시되는 일반 경고다.
  비밀번호를 화면이나 문서에 적지 않는다.
- 명령 하나의 PASS 기준을 확인한 뒤 다음 명령으로 넘어간다.

## 1. 공통 준비와 Gateway 확인

4060 서버 터미널에서 실행한다.

```bash
cd /home/newuser/Trihouse

dc() {
  docker compose -p trihouse_p0 \
    -f compose.yaml \
    -f compose.control.yaml \
    -f compose.edge_4060.yaml "$@"
}

db() {
  dc exec mysql sh -lc \
    'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "$1"' \
    sh "$1"
}
```

```bash
curl -sS http://127.0.0.1:8080/ready | python3 -m json.tool
```

**PASS**

```json
{"status":"ready","database":"ok"}
```

**FAIL**이면 주문을 만들지 말고 Gateway 로그만 먼저 본다.

```bash
dc logs --tail=100 fms_gateway
```

## 2. 기존 Job과 자원 예약 확인

```bash
curl -sS http://127.0.0.1:8080/api/v1/jobs | python3 -m json.tool
```

```bash
db "
SELECT
  reservation_id, job_id, device_id, location_id,
  reservation_mode, state, expires_at
FROM reservations
WHERE state IN ('reserved', 'in_use')
ORDER BY job_id, reservation_id;
"
```

**판정**

- 새 주문 상품의 `reserved_qty`가 이미 차 있으면 같은 상품 주문은 `409 INSUFFICIENT_STOCK`이 된다.
- 다른 Job이 쥔 Pinky·OMX·포장 도크를 선택해 할당하면 `409`이 된다.

## 3. 기존 주문 취소와 재고 예약 해제 확인 (필요할 때만)

예전 연습 주문이 DUMPLING을 잡고 있다면 그 Job만 취소한다. 아래 예시는 Job 3이다.
다른 Job을 취소하려면 숫자를 바꾸고, 대상 Job이 맞는지 먼저 조회한다.

```bash
export OLD_JOB=3

db "
SELECT
  ji.job_id, ji.job_item_id, ji.product_code,
  il.lot_code, il.available_qty, il.reserved_qty
FROM job_items ji
JOIN inventory_lots il ON il.lot_id = ji.lot_id
WHERE ji.job_id = $OLD_JOB
ORDER BY ji.job_item_id;
"
```

아래 명령은 `OLD_JOB`을 취소한다.

```bash
curl -sS -X POST \
  "http://127.0.0.1:8080/internal/v1/jobs/$OLD_JOB/cancel" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: step0-cancel-$OLD_JOB" \
  -d '{
    "reason": "restart Step 0 reservation check",
    "requested_by": "W-OP-01"
  }' | python3 -m json.tool
```

취소 뒤 원장을 확인한다.

```bash
db "
SELECT
  move_type, quantity_delta, quantity_after,
  reserved_delta, reserved_after, recorded_at, note
FROM inventory_moves
WHERE job_id = $OLD_JOB
ORDER BY inventory_move_id;
"
```

**PASS**: `reservation_release`, `reserved_delta=-1`, `reserved_after=0`이 추가된다.
`quantity_delta=0`, `quantity_after` 유지가 맞다. 취소는 실물 재고를 더하거나 빼지 않고
그 주문의 예약만 푼다.

## 4. 새 주문 만들기

이 명령은 주문 Header(`jobs`), 주문 품목(`job_items`), 실행 단계(`job_steps`),
재고 예약(`inventory_lots`, `inventory_moves`)을 한 DB 트랜잭션으로 만든다.

```bash
export RUN_TAG="PHYSICAL-STEP0-$(date +%Y%m%d-%H%M%S)"

ORDER=$(curl -sS -X POST http://127.0.0.1:8080/api/v1/orders \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $RUN_TAG" \
  -d "{
    \"external_reference\": \"$RUN_TAG\",
    \"requested_by\": \"W-OP-01\",
    \"priority\": \"normal\",
    \"allow_partial_fulfillment\": false,
    \"items\": [
      {\"product_code\": \"SKU-DUMPLING\", \"quantity\": 1}
    ]
  }")

echo "$ORDER" | python3 -m json.tool

export JOB="$(printf '%s' "$ORDER" | python3 -c \
'import json,sys; print(json.load(sys.stdin).get("job_id", ""))')"

echo "JOB=$JOB"
```

**PASS**: `JOB=<숫자>`, 응답의 `state=queued`, `reserved_quantity=1`.

**FAIL**: `JOB=`이면 다음 SQL을 실행하지 않는다. 출력된 HTTP 오류를 먼저 읽는다.
특히 `INSUFFICIENT_STOCK`은 다른 Job의 예약을 2부에서 확인한다.

## 5. 주문 재고 lot과 예약 확인

```bash
db "
SELECT
  ji.job_item_id,
  ji.job_id,
  JSON_UNQUOTE(JSON_EXTRACT(ji.metadata, '$.line_no')) AS line_no,
  ji.product_code,
  ji.requested_qty,
  JSON_UNQUOTE(JSON_EXTRACT(ji.metadata, '$.reserved_quantity')) AS item_reserved_qty,
  il.lot_id,
  il.lot_code,
  il.available_qty,
  il.reserved_qty
FROM job_items ji
JOIN inventory_lots il ON il.lot_id = ji.lot_id
WHERE ji.job_id = $JOB
ORDER BY ji.job_item_id;
"
```

**PASS 예시 (Job 4 DUMPLING)**

```text
job_item_id=4, line_no=1, lot_id=9, lot_code=LOT-FRZ-DUMPLING-001
requested_qty=1, item_reserved_qty=1, available_qty=1, reserved_qty=1
```

`line_no`와 `reserved_quantity`는 `job_items`의 일반 컬럼이 아니라 `metadata` JSON에
있다. 한 주문 줄이 여러 lot으로 나뉘면 `job_items`는 여러 행이 될 수 있으므로,
물리 행의 식별자는 `job_item_id`다.

## 6. 선택된 물품의 실제 보관 위치 확인

```bash
db "
SELECT
  ji.job_item_id,
  JSON_UNQUOTE(JSON_EXTRACT(ji.metadata, '$.line_no')) AS line_no,
  ji.product_code,
  il.lot_code,
  l.location_id,
  l.location_code,
  l.name AS location_name,
  l.zone_code,
  l.temperature_zone,
  l.state AS location_state
FROM job_items ji
JOIN inventory_lots il ON il.lot_id = ji.lot_id
LEFT JOIN locations l ON l.location_id = il.location_id
WHERE ji.job_id = $JOB
ORDER BY ji.job_item_id;
"
```

**PASS 예시 (Job 4 DUMPLING)**

```text
lot_id=9 → location_id=24 → FRZ-L2-S02
zone_code=frozen, temperature_zone=frozen, location_state=occupied
```

`inventory_lots.location_id → locations.location_id`가 실제 lot과 선반 slot을 잇는 키다.

## 7. 작업 스케줄(Step 10~70) 확인

```bash
curl -sS "http://127.0.0.1:8080/api/v1/jobs/$JOB" | python3 -m json.tool
```

```bash
db "
SELECT
  job_step_id, step_no, executor_type, action_type,
  assigned_device_id, target_location_id, state,
  JSON_UNQUOTE(JSON_EXTRACT(input, '$.branch')) AS branch
FROM job_steps
WHERE job_id = $JOB
ORDER BY step_no;
"
```

단일 온도 구역 주문의 기본 단계는 아래와 같다.

| Step | 실행 주체 | 동작 | 지금 단계에서의 의미 |
|---:|---|---|---|
| 10 | arm | `pick` | OMX 물품 준비. 아직 실행하지 않는다. |
| 20 | mobile | `navigate` | Pinky 적재 도크 이동. 첫 실제 주행 단계다. |
| 30 | fms | `load` | OMX 준비와 Pinky 도착을 함께 확인한다. |
| 40 | mobile | `navigate` | 포장 도크로 이동한다. |
| 50 | fms | `handover` | 인계 처리한다. |
| 60 | fms | `wait` | 작업자 완료 확인을 기다린다. |
| 70 | mobile | `return_home` | 선택 Pinky 충전소로 복귀한다. |

**PASS**: 이 시점에는 모든 `state=pending`, `assigned_device_id=NULL`이다.

## 8. 할당 전에 선택 가능한 자원 확인

```bash
curl -sS http://127.0.0.1:8080/api/v1/devices | python3 -m json.tool
```

```bash
db "
SELECT
  d.device_id, d.device_type, d.control_mode, d.active,
  ds.state AS runtime_state, ds.health, ds.battery_pct
FROM devices d
LEFT JOIN device_states ds ON ds.device_id = d.device_id
ORDER BY d.device_type, d.device_id;

SELECT
  location_code, location_type, map_name, state,
  JSON_UNQUOTE(JSON_EXTRACT(metadata, '$.operational_role')) AS operational_role
FROM locations
WHERE map_name = 'trihouse_test_01'
  AND location_type IN ('loading_dock', 'outbound_dock', 'staging', 'charger')
ORDER BY location_type, location_code;
"
```

선택 조건은 다음과 같다.

- Pinky/OMX: `active=1`, `control_mode=automatic`, `runtime_state=idle` 또는 `charging`, `health=ok`
- 포장 도크: `state=available`, `operational_role=loading_dock`
- 충전소: 선택 Pinky의 고정 충전소 코드

현재 구현의 고정 결속은 다음과 같다.

```text
PK_01 → TRIHOUSE-TEST-01-CHG-01
PK_02 → TRIHOUSE-TEST-01-CHG-02
```

위 SQL 결과에 이 location code가 없으면 값을 추측해 넣지 않는다. 활성 지도와
자원 코드가 맞지 않는 상태이므로 관제 지도 데이터를 먼저 고친다.

## 9. Pinky·OMX·포장 도크 할당

아래 네 값은 **8부 SQL 결과로 바꾼 뒤** 실행한다. 예시는 PK_02와 OMX_02다.

```bash
export MOBILE="PK_02"
export OMX="OMX_02"
export PACKING_DOCK="<8부에서 확인한 loading_dock location_code>"
export CHARGER="TRIHOUSE-TEST-01-CHG-02"
```

아래는 DB 상태 변경 명령이다. Job을 `assigned`로 바꾸고 Pinky·OMX·포장 도크를
4시간 `reserved`로 잡지만, 이동 명령을 보내지는 않는다.

```bash
curl -sS -X POST \
  "http://127.0.0.1:8080/internal/v1/jobs/$JOB/assignment" \
  -H 'Content-Type: application/json' \
  -d "{
    \"revision\": 1,
    \"mobile_id\": \"$MOBILE\",
    \"omx_id\": \"$OMX\",
    \"packing_dock_code\": \"$PACKING_DOCK\",
    \"charger_code\": \"$CHARGER\"
  }" | python3 -m json.tool
```

**PASS**: 응답의 `job_id`, `mobile_id`, `omx_id`, 도크·충전소 코드가 입력값과 같다.

## 10. Step 0 최종 할당 판정

```bash
db "
SELECT
  job_id, state, assigned_mobile_id, destination_location_id, revision
FROM jobs
WHERE job_id = $JOB;

SELECT
  step_no, executor_type, action_type,
  assigned_device_id, assignment_revision, state
FROM job_steps
WHERE job_id = $JOB
ORDER BY step_no;

SELECT
  reservation_id, device_id, location_id,
  reservation_mode, state, expires_at
FROM reservations
WHERE job_id = $JOB
ORDER BY reservation_id;
"
```

**PASS**

```text
jobs.state = assigned
jobs.assigned_mobile_id = 선택한 PK_0N
arm step의 assigned_device_id = 선택한 OMX_0N
mobile step의 assigned_device_id = 선택한 PK_0N
reservations = Pinky 1개 + OMX 1개 + 포장 도크 1개
```

## Step 0 뒤: 실물 Pinky 주행으로 넘어가기 전 Gate

여기서 `job_runner_node`를 실행하면 Step 10부터 실제 dispatch가 가능해진다. 하지만
Step 20은 Pinky가 실제로 움직이는 단계이므로, 아래를 모두 통과하기 전에는 worker를
시작하지 않는다.

1. [p0-hardware-camera-gated-run.md](p0-hardware-camera-gated-run.md)의 Gate 3~4:
   PK 카메라 송신, 4060 MediaMTX 수신, 실제 프레임 디코딩 확인
2. 같은 문서 Gate 6: 모터 입력 토픽의 유일한 publisher가 safety supervisor인지,
   E-stop 담당자와 빈 주행 경로가 준비됐는지 확인
3. 같은 문서 Gate 7: 넓고 짧은 구간 수동 Nav2 왕복 성공
4. 협로를 지날 예정이면 `new_map_2`용 `narrow_zones` 파일과 RMF `mutex:`를 확인

모두 PASS이면 해당 문서 Gate 8의 관제 worker 기동과 주문 1건 절차를 사용한다.
그때도 Step 10이 먼저 dispatch되고, Step 20이 `running`이 되기 전 Pinky는 움직이지 않는다.

## 구현 위치

- 주문 HTTP 진입점: `fms_gateway/app/main.py`의 `POST /api/v1/orders`
- lot 선택·예약·작업 저장 트랜잭션: `fms_gateway/app/repositories.py`의 `create_outbound_order`
- Step 10~70 템플릿: `control_tower/task_manager/outbound_sequence.py`
- 자원 할당·예약 트랜잭션: `fms_gateway/app/repositories.py`의 `assign_job_resources`
- 재고·Job·Step·예약 컬럼 정본: `db/schema_mysql.sql`
