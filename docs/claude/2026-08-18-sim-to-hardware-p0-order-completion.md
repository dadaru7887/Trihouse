# 시뮬 → 실기 P0 주문 완주 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 주문 1건이 UI/API → control_tower → 로봇까지 완주하는 것을 시뮬(단일 로봇)에서 확정한 뒤, 같은 계약으로 실기 PK_01에서 재현한다.

**Architecture:** 시뮬과 실기는 **서로 다른 nav2 스택**을 쓴다 — 시뮬은 `nav2_bringup`(Jazzy 표준), 실기는 벤더 `pinky_navigation/launch/bringup_launch.xml`이다. 그래서 시뮬에서 고친 것이 실기로 그대로 옮겨가지 않는다. 실기에 옮겨야 하는 것은 두 개(nav2 params root key, TF namespace)뿐이고, 두 개(collision_monitor·docking_server 절 보충)는 실기가 그 노드를 아예 띄우지 않아 해당 없음이다. 이 계획은 그 차이를 실물에서 먼저 확인한 뒤 실기 launch를 고친다. `pinky_pro`는 보호 경로이므로 벤더 파일을 고치지 않고 우리 저장소의 인자와 파생 params로 우회한다.

**Tech Stack:** ROS 2 Jazzy, nav2, Open-RMF, Gazebo(gz sim), Python 3.12, pytest, MySQL 8.4, Docker Compose, MediaMTX, OpenCV

**Spec:** [docs/validation/2026-08-18-p0-manual-test.md](../validation/2026-08-18-p0-manual-test.md) (수동 검증 절차와 성공 기준), [docs/superpowers/specs/2026-08-12-sr07-08-41-rmf-order-reservation-design.md](../superpowers/specs/2026-08-12-sr07-08-41-rmf-order-reservation-design.md) 12절(단일 Pinky 첫 시험 범위)

## 시작 기준선 (2026-08-18 커밋 `01595e9e`)

이 계획은 아래가 **이미 끝난 상태**를 전제한다. 시작 전에 `git log --oneline -3`으로 확인한다.

| 커밋 | 내용 |
|---|---|
| `a58e02d6` | 두 로봇이 localization을 공유하던 문제 |
| `4309fd21` | 온보드 토픽 절대→상대 이름 (namespace 정합) |
| `d59219e0` | 시뮬 ROS 도메인 고정 |
| `a66082ce` | 로봇의 localization을 RMF adapter까지 전달 (TF namespace, status 시계) |
| `01595e9e` | ROS 전용 서브넷 고정, 카메라 발행 IP 분리, **`robots:=PK_01` 단일 로봇 인자**, DB 포트 3308 |

따라서 아래는 **다시 하지 않는다**: 미커밋 작업 커밋, 로봇 대수 launch 인자화, `EDGE_BIND_ADDRESS`/`OMX_PC_0N_IP` 정리, DDS transport·도메인·discovery range 고정.

작업 트리가 깨끗해야 한다(` m pinky_pro` 서브모듈 제외 — 보호 경로이므로 손대지 않는다).

## Global Constraints

- `pinky_pro/**`, `control_system/**`는 **읽기·실행만** 허용한다. 이 계획의 어떤 태스크도 그 아래를 수정하지 않는다.
- 로봇팔(OMX)은 다른 팀원 담당이다. `trihouse_omx_adapter/**`, `control_tower/task_manager/omx_*`, `control_tower/gateway/omx_*`를 수정하지 않는다.
- 카메라는 **ROS를 거치지 않는다.** 로봇의 `camera_streamer`가 ffmpeg로 MediaMTX(PC1)에 RTSP push하고, 서버가 그것을 읽어 [vision_edge/perception.py](../../vision_edge/perception.py)의 `cv2.QRCodeDetector`·`cv2.aruco.DICT_5X5_50`으로 인식한다. **카메라 토픽을 ROS 브리지에 추가하지 않는다.**
- ROS 도메인: **시뮬 0, 실기 52.** 절대 섞지 않는다.
- 로봇 선택 인자는 **robot_id 기준**이다(`robots:=PK_01`, `TRIHOUSE_ROBOTS=PK_01`). namespace(`pinky_01`)가 아니다.
- pytest는 항상 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest`로 실행한다. 그렇지 않으면 `launch_testing` 플러그인이 venv pytest와 충돌해 `PluginValidationError`가 난다.
- ROS 명령 전에는 항상 3단 source: `/opt/ros/jazzy/setup.bash` → `install/setup.bash` → `pinky_pro/install/setup.bash`.
- `trihouse_pinky_fleet`를 고치면 `colcon build --packages-select trihouse_pinky_fleet --symlink-install`로 재빌드한다(install이 복사본이다). launch 파일은 symlink라 재빌드가 필요 없다.
- 프로세스 정리는 반드시 `scripts/sim_teardown.sh`로 한다. `pkill -f <패턴>`은 자기 자신과 Docker 컨테이너의 ROS 프로세스까지 죽인다.
- `PYTHONPATH`는 덮어쓰지 말고 더한다(`PYTHONPATH="...:$PYTHONPATH"`). 덮어쓰면 `ModuleNotFoundError: rclpy`가 난다.

## File Structure

| 파일 | 책임 | 태스크 |
|---|---|---|
| `docs/validation/2026-08-18-p0-manual-test.md` | 시뮬·실기 검증 기록 | 1, 3, 7 |
| `scripts/release_stuck_job.py` (신규) | RMF에 도달하지 못한 채 로봇을 쥔 job의 감사 가능한 회수 | 2 |
| `tests/test_release_stuck_job.py` (신규) | 회수 판단 규칙(순수 함수) 회귀 | 2 |
| `control_tower/bringup/p0_runtime_assets.py` | `derive_nav2_params`에 `root_key` 추가 — RewrittenYaml이 없는 실기 launch용 | 4 |
| `control_tower/tests/test_p0_runtime_assets.py` | 위 계약 회귀 | 4 |
| `trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_pinky.launch.py` | 실기 nav2에 파생 params 전달, TF를 로봇 namespace로, vision 연결 | 5, 6 |
| `trihouse_pinky/trihouse_pinky_bringup/test/test_trihouse_pinky_launch.py` (신규) | 실기 launch 계약 회귀 | 5, 6 |

---

## 하루 안에 끝내기 위한 판단

**7개 태스크이고 그중 Task 3·7은 실물 로봇과 창고가 준비돼 있어야 한다.** 정직하게 말하면 하루에 전부는 빡빡하다. 우선순위는 이렇다.

- **임계 경로:** 1(시뮬 완주) → 3(실기 전제 확인) → 4·5(실기 launch) → 7(실기 완주)
- **자원 회수는 재시도가 2회 이상 예상되면 오히려 시간을 아낀다.** 없으면 실패한 시험마다 로봇 한 대가 영구히 묶이고, 매번 DB를 손으로 고쳐야 한다. 회수는 아래 Task 2 가 아니라 **설계 8절 1~2번**(취소 엔드포인트 + 만료 회수 엔드포인트)으로 한다.
- **Task 6(실기 카메라)은 주행 완주와 독립적이다.** 시간이 부족하면 마지막으로 미룬다.
- **Task 3에서 벤더 bringup이 namespace를 지원하지 않는 것으로 밝혀지면** 분기 B(단일 로봇을 namespace 없이 기동)로 간다. Task 4·5가 불필요해져 오히려 빨라지지만, 2대 운용은 다음 날로 미뤄진다.

---

### Task 1: 시뮬 단일 로봇으로 주문 1건 완주

새 코드를 쓰지 않는다. `robots:=PK_01`로 부하를 걷어낸 상태에서 기존 계약이 실제로 완주하는지 확인한다. **여기서 실패하면 부하가 아니라 남은 버그이므로** systematic-debugging으로 근본 원인을 찾은 뒤 진행한다.

**Files:**
- Modify: `docs/validation/2026-08-18-p0-manual-test.md`

**Interfaces:**
- Consumes: 커밋 `01595e9e`의 `robots` 인자
- Produces: 시뮬에서 검증된 성공 기준 4개. Task 7(실기)이 같은 기준을 쓴다.

- [ ] **Step 1: 깨끗한 상태를 만든다**

```bash
cd /home/syw/Trihouse
scripts/sim_teardown.sh
uptime
```

기대: `killed=<n> leftover=0`, `fastrtps_shm_left=0`, `docker_containers=8`. load average가 20 아래여야 한다. `leftover`가 0이 아니면 그 프로세스를 먼저 처리한다 — 이전 세대가 같은 토픽에 발행하면 이후 측정이 전부 무효다.

- [ ] **Step 2: Docker 층을 확인한다**

```bash
curl -s -o /dev/null -w 'control_ui %{http_code}\n' http://127.0.0.1:3100/
curl -s -o /dev/null -w 'rmf_dashboard %{http_code}\n' http://127.0.0.1:3000/
curl -s http://127.0.0.1:8080/ready
```

기대: `200`, `200`, `{"status":"ready","database":"ok"}`. 아니면 `scripts/control_stack up` 후 다시 확인한다.

- [ ] **Step 3: 단일 로봇으로 기동한다**

```bash
TRIHOUSE_MAP_REVISION="trihouse_test_01:730111d2e446f5141c5ef069e5f2c1c8c5383aea79bdeffd05d3d34f2094b7ff" \
TRIHOUSE_ROBOTS=PK_01 \
ROS_DOMAIN_ID=0 \
control_tower/bringup/p0_simulation_bringup.sh 2>&1 | tee /tmp/sim.log
```

기동에 1~2분 걸린다. 파이프가 종료코드를 가리므로 상태는 다음 단계로 판정한다.

- [ ] **Step 4: 위에서부터 판정한다**

```bash
grep -c 'Managed nodes are active' /tmp/sim.log
grep -E 'Failed to bring up all requested|Failed to change state' /tmp/sim.log
uptime
```

기대: 첫 명령이 **2**(localization 1 + navigation 1 — 로봇 한 대), 두 번째가 빈 출력. 실패하면 load average를 함께 기록한다.

- [ ] **Step 5: 로봇 상태를 읽는다**

```bash
python3 scripts/verify_robot_status.py pinky_01 20
```

기대: `publishers=1`, `frame_id=map`, `dispatchable=true`, `errors=[]`.

`ros2 topic echo`/`topic list`/`param get`은 쓰지 않는다 — 그래프 열거에 의존해 부하가 높으면 멈춘다.

- [ ] **Step 6: 3회 재현한다**

Step 1~5를 두 번 더 반복한다. **3회 연속 성공해야** 코드 정합성이 확정된다. 한 번이라도 실패하면 `uptime`과 실패한 lifecycle 노드 이름을 기록하고 보고한다.

- [ ] **Step 7: 주문 1건을 넣는다**

```bash
PW=$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)
docker exec trihouse-mysql mysql -uroot -p"$PW" -e "
  SELECT product_code, COUNT(*) AS lots FROM trihouse_fms.inventory_lots
   WHERE state='stored' GROUP BY product_code ORDER BY product_code;"

curl -s -X POST http://127.0.0.1:8080/api/v1/orders \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: sim-single-$(date +%s)" \
  -d '{"requested_by":"sim-single","priority":"normal",
       "items":[{"product_code":"SKU-COFFEE","quantity":1}]}' | python3 -m json.tool
```

기대: `201`과 함께 Job 하나와 7단계 계획. **재고는 유한하다** — SKU마다 stored lot이 하나씩이므로 주문은 실제로 소진한다. 재고가 없으면 `409 INSUFFICIENT_STOCK`, 없는 상품이면 `422 PRODUCT_NOT_FOUND`.

- [ ] **Step 8: 주문이 로봇까지 가는지 본다**

```bash
grep -E 'job runner cycle|job runner blocked' /tmp/sim.log | tail -5
grep -E 'RMF dispatch cycle' /tmp/sim.log | tail -3
curl -s http://127.0.0.1:8080/api/v1/jobs | python3 -m json.tool | head -40
```

기대: `claimed=` 1 이상, job 상태가 `queued` → `assigned` → `running`으로 전진. `no free robot`이 보이면 이전 job이 로봇을 쥐고 있는 것이니 **설계 8절 1~2번**으로 회수한다(아래 Task 2 는 대체됐다).

- [ ] **Step 9: 완주와 예약 해제를 확인한다**

```bash
docker exec trihouse-mysql mysql -uroot -p"$PW" -e "
  SELECT job_id, state, IFNULL(assigned_mobile_id,'-') AS robot
    FROM trihouse_fms.jobs ORDER BY job_id;
  SELECT job_id, state, COUNT(*) AS n
    FROM trihouse_fms.reservations GROUP BY job_id, state ORDER BY job_id;"
```

기대: 새 job이 종료 상태이고 그 job의 예약이 `released`.

예약이 `reserved`/`in_use`로 남으면 그 사실을 기록한다 — RMF task update가 도착하지 않아 [rmf_task_repository.py:441-472](../../control_tower/database/repositories/rmf_task_repository.py#L441-L472)의 전이 경로를 타지 못한 것이고, 그것이 **설계 8절 2번**(만료 회수)이 필요한 이유다.

- [ ] **Step 10: 기록하고 커밋한다**

`docs/validation/2026-08-18-p0-manual-test.md`에 "5. 단일 로봇 시뮬 완주 기록" 절을 만들고 Step 3~9의 실제 출력값(성공/실패, load average, 소요 시간)을 적는다. 실패한 것이 있으면 성공한 것과 함께 그대로 적는다.

```bash
git add docs/validation/2026-08-18-p0-manual-test.md
git commit -m "docs: record the single-robot simulation order run"
```

---

### Task 2: ~~RMF에 도달하지 못한 job의 안전한 회수~~ — **대체됨, 수행하지 마라**

> **이 태스크는 커밋 `c2b675c0`의 [예약 기반 작업 스케줄링 설계](2026-08-18-reservation-scheduling-design.md) **8절 1~2번**으로 대체됐다.**
>
> 아래 스크립트를 만들지 마라. 대신 그 설계대로 Gateway에 두 엔드포인트를 만든다.
>
> - `POST /internal/v1/jobs/{job_id}/cancel` (설계 4.7) — 한 트랜잭션에서 job·step·예약을 `cancelled`로, `Idempotency-Key` 필수, 끝난 job은 409
> - `POST /internal/v1/reservations/expire` (설계 4.5) — `expires_at < NOW()`인 예약을 `expired`로, 건마다 `operation_event`
>
> 이유: 행 잠금과 상태 전이 불변식이 이미 Gateway 저장소 안에 있다. 두 곳에서 같은 전이를 하면 어긋난다. 그리고 취소는 UI가 결국 노출할 기능이므로 스크립트가 아니라 API가 맞는 자리다.
>
> 아래 원문은 참고용으로만 남긴다. 판단 규칙(`in_use`면 로봇이 움직이는 중일 수 있으니 건드리지 않는다)은 여전히 유효하며 엔드포인트 구현에 그대로 옮길 값이 있다.

예약 lifecycle 자체는 이미 구현돼 있다([rmf_task_repository.py:441-472](../../control_tower/database/repositories/rmf_task_repository.py#L441-L472) — `active→in_use`, `completed→released`, `failed/canceled→cancelled`). 그러나 그것은 **RMF task update가 도착해야** 작동한다. RMF에 제출되기 전에 죽은 job은 그 경로를 타지 못하고 영원히 로봇을 쥔다 — job 2·3이 지금 그 상태다.

**Files:**
- Create: `scripts/release_stuck_job.py`
- Create: `tests/test_release_stuck_job.py`

**Interfaces:**
- Consumes: 없음
- Produces: `plan_release(job: dict, reservations: list[dict]) -> ReleasePlan`. `ReleasePlan`은 frozen dataclass이며 필드는 `job_id: int`, `reservation_ids: tuple[int, ...]`, `device_ids: tuple[str, ...]`, `blocked_reason: str | None`이다. `blocked_reason`이 `None`이 아니면 스크립트는 아무것도 쓰지 않는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_release_stuck_job.py`를 만든다.

```python
"""RMF 밖에서 멈춘 job 을 회수해도 되는지 판단하는 순수 규칙."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release_stuck_job.py"


def _module():
    spec = importlib.util.spec_from_file_location("release_stuck_job", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["release_stuck_job"] = module
    spec.loader.exec_module(module)
    return module


def test_a_job_holding_reserved_resources_can_be_released() -> None:
    module = _module()
    job = {"job_id": 2, "state": "assigned", "assigned_mobile_id": "PK_01"}
    reservations = [
        {"reservation_id": 11, "state": "reserved", "device_id": "PK_01"},
        {"reservation_id": 12, "state": "reserved", "device_id": "OMX_01"},
    ]

    plan = module.plan_release(job, reservations)

    assert plan.blocked_reason is None
    assert plan.job_id == 2
    assert plan.reservation_ids == (11, 12)
    assert plan.device_ids == ("PK_01", "OMX_01")


def test_an_in_use_reservation_blocks_release_because_the_robot_may_be_moving() -> None:
    module = _module()
    job = {"job_id": 3, "state": "running", "assigned_mobile_id": "PK_02"}
    reservations = [{"reservation_id": 21, "state": "in_use", "device_id": "PK_02"}]

    plan = module.plan_release(job, reservations)

    assert plan.blocked_reason == "reservation 21 is in_use; the robot may still be moving"
    assert plan.reservation_ids == ()


def test_a_terminal_job_needs_no_release() -> None:
    module = _module()
    job = {"job_id": 4, "state": "cancelled", "assigned_mobile_id": None}

    plan = module.plan_release(job, [])

    assert plan.blocked_reason == "job 4 is already cancelled"


def test_a_job_with_no_reservation_still_reports_a_clean_plan() -> None:
    module = _module()
    job = {"job_id": 5, "state": "queued", "assigned_mobile_id": None}

    plan = module.plan_release(job, [])

    assert plan.blocked_reason is None
    assert plan.reservation_ids == ()
    assert plan.device_ids == ()
```

- [ ] **Step 2: 테스트를 돌려 RED를 확인한다**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/test_release_stuck_job.py
```

기대: FAIL — `spec is None` 또는 `FileNotFoundError`.

- [ ] **Step 3: 판단 규칙을 구현한다**

`scripts/release_stuck_job.py`를 만든다.

```python
#!/usr/bin/env python3
"""RMF 에 도달하지 못한 채 로봇을 쥔 job 을 감사 가능한 방식으로 회수한다.

예약 lifecycle 자체는 `rmf_task_repository` 가 이미 처리한다. 다만 그 경로는
RMF task update 가 도착해야 돈다. RMF 에 제출되기 전에 멈춘 job 은 그 경로를
타지 못하고 예약을 영원히 쥔다. Gateway 에 취소 엔드포인트가 없어서 이 스크립트가
그 자리를 메운다.

예약이 `in_use` 면 로봇이 실제로 움직이는 중일 수 있으므로 건드리지 않는다 —
그때 옳은 경로는 RMF task 를 취소하는 것이고 이 스크립트의 일이 아니다.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

TERMINAL_JOB_STATES = frozenset({"succeeded", "failed", "cancelled"})


@dataclass(frozen=True)
class ReleasePlan:
    job_id: int
    reservation_ids: tuple[int, ...]
    device_ids: tuple[str, ...]
    blocked_reason: str | None


def plan_release(job: dict, reservations: list[dict]) -> ReleasePlan:
    """무엇을 바꿀지 결정한다. 이 함수는 아무것도 쓰지 않는다."""
    job_id = int(job["job_id"])
    state = str(job["state"])
    if state in TERMINAL_JOB_STATES:
        return ReleasePlan(job_id, (), (), f"job {job_id} is already {state}")
    for reservation in reservations:
        if reservation["state"] == "in_use":
            return ReleasePlan(
                job_id,
                (),
                (),
                f"reservation {int(reservation['reservation_id'])} is in_use; "
                "the robot may still be moving",
            )
    open_rows = [row for row in reservations if row["state"] == "reserved"]
    return ReleasePlan(
        job_id,
        tuple(int(row["reservation_id"]) for row in open_rows),
        tuple(str(row["device_id"]) for row in open_rows),
        None,
    )
```

- [ ] **Step 4: 테스트를 돌려 GREEN을 확인한다**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/test_release_stuck_job.py
```

기대: 4건 PASS.

- [ ] **Step 5: 실행부를 붙인다**

같은 파일 끝에 추가한다. `--apply` 없이는 계획만 출력한다.

```python
def _fetch(cursor, job_id: int) -> tuple[dict, list[dict]]:
    cursor.execute(
        "SELECT job_id, state, assigned_mobile_id FROM jobs WHERE job_id = %s FOR UPDATE",
        (job_id,),
    )
    job = cursor.fetchone()
    if job is None:
        raise SystemExit(f"job {job_id} does not exist")
    cursor.execute(
        "SELECT reservation_id, state, device_id FROM reservations "
        "WHERE job_id = %s AND state IN ('reserved','in_use') "
        "ORDER BY reservation_id FOR UPDATE",
        (job_id,),
    )
    return job, list(cursor.fetchall())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", type=int)
    parser.add_argument("--reason", required=True, help="operation_events 에 남길 사유")
    parser.add_argument("--actor", default=os.environ.get("USER", "operator"))
    parser.add_argument("--apply", action="store_true", help="없으면 계획만 출력한다")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3308)
    args = parser.parse_args(argv)

    import mysql.connector

    password = os.environ.get("MYSQL_ROOT_PASSWORD")
    if not password:
        raise SystemExit("MYSQL_ROOT_PASSWORD is required")
    connection = mysql.connector.connect(
        host=args.host, port=args.port, user="root",
        password=password, database="trihouse_fms",
    )
    cursor = connection.cursor(dictionary=True)
    try:
        job, reservations = _fetch(cursor, args.job_id)
        plan = plan_release(job, reservations)
        print(
            f"job={plan.job_id} reservations={list(plan.reservation_ids)} "
            f"devices={list(plan.device_ids)} blocked={plan.blocked_reason}"
        )
        if plan.blocked_reason is not None:
            connection.rollback()
            return 1
        if not args.apply:
            connection.rollback()
            print("dry run; pass --apply to write")
            return 0
        if plan.reservation_ids:
            cursor.execute(
                "UPDATE reservations SET state='cancelled', released_at=NOW(6) "
                f"WHERE reservation_id IN ({','.join(['%s'] * len(plan.reservation_ids))})",
                plan.reservation_ids,
            )
        cursor.execute(
            "UPDATE jobs SET state='cancelled', assigned_mobile_id=NULL, "
            "revision = revision + 1 WHERE job_id = %s",
            (plan.job_id,),
        )
        cursor.execute(
            "INSERT INTO operation_events "
            "(event_uuid, occurred_at, actor_worker_id, job_id, severity, category, "
            " event_type, message, payload) "
            "VALUES (UUID(), NOW(6), %s, %s, 'warning', 'operation', 'job.cancelled', %s, '{}')",
            (args.actor, plan.job_id, args.reason),
        )
        connection.commit()
        print("applied")
        return 0
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: dry run으로 확인한다**

```bash
chmod +x scripts/release_stuck_job.py
export MYSQL_ROOT_PASSWORD=$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)
python3 scripts/release_stuck_job.py 2 --reason "P0 hardware test cleanup"
```

기대: 계획만 출력하고 `dry run; pass --apply to write`.

**`--apply`는 사용자 승인을 받은 뒤에만 실행한다** — 되돌릴 수 없는 운영 DB 쓰기다.

- [ ] **Step 7: 커밋한다**

```bash
git add scripts/release_stuck_job.py tests/test_release_stuck_job.py
git commit -m "feat: recover a job that never reached RMF without hand-editing the database"
```

---

### Task 3: 실기 전제 확인 — 벤더 bringup이 namespace를 지원하는가

**이 태스크가 이후 전부의 분기점이다.** 코드를 쓰기 전에 실물 로봇에서 사실을 확인한다.

실기 nav2는 벤더 [pinky_navigation/launch/bringup_launch.xml](../../pinky_pro/pinky_navigation/launch/bringup_launch.xml)이고, 그것은 세 가지를 한다.

1. `<push-ros-namespace namespace="$(var namespace)"/>` — nav2 노드가 `/pinky_01/...`이 된다
2. `<remap from="/tf" to="tf"/>` — nav2가 `/pinky_01/tf`를 듣는다
3. `<param from="$(var params_file)"/>` — params를 **RewrittenYaml 없이** 그대로 넘긴다

그리고 벤더 params([pinky_navigation/params/nav2_params.yaml](../../pinky_pro/pinky_navigation/params/nav2_params.yaml))의 최상위 키는 `amcl:`, `controller_server:` 같은 **맨 이름**이고 `/**:` 와일드카드가 없다.

따라서 `namespace:=pinky_01`로 띄우면 시뮬에서 겪은 것과 **같은 두 실패**가 실기에서 재현된다 — params 0개 적용, TF 분리로 AMCL 스캔 전량 폐기.

반면 실기는 `collision_monitor`·`docking_server`·`route_server`를 **lifecycle 목록에 넣지 않으므로**(벤더 XML의 `lifecycle_nodes_nav`가 6개뿐) 시뮬에서 고친 그 두 절은 실기에 해당 없다. `/cmd_vel` 발행자도 다르다 — 실기는 `velocity_smoother`가 `cmd_vel_smoothed`→`cmd_vel`로 remap해 발행한다.

**Files:**
- Modify: `docs/validation/2026-08-18-p0-manual-test.md`

**Interfaces:**
- Consumes: 없음
- Produces: 분기 결정. **A**(namespace 유지 → Task 4·5 수행) 또는 **B**(단일 로봇을 namespace 없이 → Task 4·5 생략).

- [ ] **Step 1: 벤더 bringup이 namespace 인자를 받는지 확인한다**

로봇 위에서:

```bash
source /opt/ros/jazzy/setup.bash
source ~/pinky_ws/install/setup.bash   # 실제 벤더 워크스페이스 경로로 바꾼다
grep -n 'namespace\|push-ros-namespace' \
  "$(ros2 pkg prefix pinky_bringup)/share/pinky_bringup/launch/bringup_robot.launch.xml"
```

판정:
- `<arg name="namespace"`와 `<push-ros-namespace`가 **둘 다 있으면** → **분기 A**
- 하나라도 없으면 그 로봇의 벤더 bringup은 namespace를 무시하고 `/odom`·`/scan`·TF가 루트에 남는다 → **분기 B**

- [ ] **Step 2: 실기 도메인과 망을 확인한다**

```bash
echo "ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
echo "ROS_AUTOMATIC_DISCOVERY_RANGE=$ROS_AUTOMATIC_DISCOVERY_RANGE"
ip -4 addr show | grep -w inet
ping -c 2 <관제 호스트 IP>
```

기대: 도메인 **52**, discovery range `SUBNET`, 로봇과 관제 호스트가 같은 `192.168.0.0/24`(ipTIME N604SR) 위에 있다. 서버 PC는 인터페이스가 둘이므로 **Ethernet 쪽 주소**를 쓴다 — Wi-Fi 쪽이면 로봇이 붙지 못한다.

- [ ] **Step 3: 관제 경계에 도달하는지 확인한다**

로봇에서:

```bash
nc -z -w3 <관제 호스트 IP> 8788 && echo "tcp 8788 ok"
curl -s --max-time 3 http://<관제 호스트 IP>:8080/ready
```

기대: 둘 다 성공. 8788에 못 붙으면 `fleet_gateway`가 ONLINE을 내지 못해 `control_link_offline`이 풀리지 않고 `dispatchable`이 false로 남는다.

- [ ] **Step 4: 분기를 기록하고 보고한다**

`docs/validation/2026-08-18-p0-manual-test.md`에 "6. 실기 전제 확인" 절을 만들고 Step 1~3의 실제 출력을 적는다. 어느 분기인지 한 줄로 명시한다.

**분기 B라면 Task 4·5를 건너뛰고 Task 7의 분기 B 절차로 간다.** 단일 로봇에서 namespace가 비면 nav2 노드가 루트에 있으므로 벤더 params의 맨 키가 그대로 맞고, `/tf` remap도 루트로 해석되어 발행자와 같은 자리가 된다 — 두 문제가 동시에 사라진다. 대신 두 대 운용은 다음 날로 미뤄진다.

```bash
git add docs/validation/2026-08-18-p0-manual-test.md
git commit -m "docs: record what the real robot's vendor bringup actually supports"
```

---

### Task 4: 실기용 nav2 params에 namespace root key를 넣는다

**분기 A일 때만 수행한다.**

시뮬은 `nav2_bringup`의 `RewrittenYaml(root_key=namespace)`가 최상위 키를 감싸 준다. 벤더 XML에는 그 장치가 없으므로 우리가 감싼 파일을 만들어 넘긴다. `derive_nav2_params`는 이미 프레임 이름과 절대 토픽에 namespace를 붙이고 초기 pose를 심으므로, 감싸기만 더한다.

**Files:**
- Modify: `control_tower/bringup/p0_runtime_assets.py:281-331`
- Test: `control_tower/tests/test_p0_runtime_assets.py`

**Interfaces:**
- Consumes: 없음
- Produces: `derive_nav2_params(source: Path, namespace: str, destination: Path, *, initial_pose: tuple[float, float, float] | None = None, root_key: str | None = None) -> None`. `root_key`가 주어지면 결과 문서 전체를 `{root_key: document}`로 감싼다. 기본값 `None`은 기존 동작 그대로다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`control_tower/tests/test_p0_runtime_assets.py` 끝에 추가한다.

```python
def test_root_key_wraps_the_document_for_launchers_without_rewritten_yaml(tmp_path):
    source = tmp_path / "nav2_params.yaml"
    source.write_text(
        "amcl:\n"
        "  ros__parameters:\n"
        "    base_frame_id: base_footprint\n"
        "controller_server:\n"
        "  ros__parameters:\n"
        "    controller_frequency: 20.0\n",
        encoding="utf-8",
    )
    destination = tmp_path / "derived.yaml"

    p0_runtime_assets.derive_nav2_params(
        source, "pinky_01", destination, root_key="pinky_01"
    )

    document = yaml.safe_load(destination.read_text(encoding="utf-8"))
    assert set(document) == {"pinky_01"}
    assert document["pinky_01"]["amcl"]["ros__parameters"]["base_frame_id"] == "pinky_01/base_footprint"
    assert document["pinky_01"]["controller_server"]["ros__parameters"]["controller_frequency"] == 20.0


def test_omitting_the_root_key_keeps_the_existing_flat_shape(tmp_path):
    source = tmp_path / "nav2_params.yaml"
    source.write_text(
        "amcl:\n  ros__parameters:\n    base_frame_id: base_footprint\n",
        encoding="utf-8",
    )
    destination = tmp_path / "derived.yaml"

    p0_runtime_assets.derive_nav2_params(source, "pinky_01", destination)

    document = yaml.safe_load(destination.read_text(encoding="utf-8"))
    assert "pinky_01" not in document
    assert document["amcl"]["ros__parameters"]["base_frame_id"] == "pinky_01/base_footprint"


def test_the_root_key_wraps_after_the_initial_pose_is_written(tmp_path):
    source = tmp_path / "nav2_params.yaml"
    source.write_text("amcl:\n  ros__parameters:\n    alpha1: 0.2\n", encoding="utf-8")
    destination = tmp_path / "derived.yaml"

    p0_runtime_assets.derive_nav2_params(
        source, "pinky_01", destination,
        initial_pose=(1.5, -2.0, 0.25), root_key="pinky_01",
    )

    amcl = yaml.safe_load(destination.read_text(encoding="utf-8"))["pinky_01"]["amcl"]
    assert amcl["ros__parameters"]["set_initial_pose"] is True
    assert amcl["ros__parameters"]["initial_pose"] == {"x": 1.5, "y": -2.0, "z": 0.0, "yaw": 0.25}
```

- [ ] **Step 2: 테스트를 돌려 RED를 확인한다**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  control_tower/tests/test_p0_runtime_assets.py -k root_key
```

기대: FAIL — `TypeError: derive_nav2_params() got an unexpected keyword argument 'root_key'`.

- [ ] **Step 3: 감싸기를 구현한다**

`p0_runtime_assets.py`의 시그니처를 바꾼다.

```python
def derive_nav2_params(
    source: Path,
    namespace: str,
    destination: Path,
    *,
    initial_pose: tuple[float, float, float] | None = None,
    root_key: str | None = None,
) -> None:
```

docstring 끝에 한 문단을 더한다.

```
    `root_key` 를 주면 문서 전체를 그 키 아래로 감싼다. `nav2_bringup` 은
    `RewrittenYaml(root_key=namespace)` 로 이것을 스스로 하지만, 벤더
    `pinky_navigation/launch/bringup_launch.xml` 은 `<param from>` 으로 원본을
    그대로 넘긴다. 그러면 `/pinky_01/amcl` 노드가 맨 키 `amcl:` 과 매칭되지
    않아 파라미터가 한 개도 적용되지 않는다.
```

`destination.write_text(...)` **직전에** 삽입한다. 초기 pose를 심은 뒤에 감싸야 한다.

```python
    if root_key:
        derived = {root_key: derived}
```

- [ ] **Step 4: 테스트를 돌려 GREEN을 확인한다**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q control_tower/tests/test_p0_runtime_assets.py
```

기대: 전부 PASS. 기존 테스트도 통과해야 한다 — 기본값이 기존 평평한 형태를 유지한다.

- [ ] **Step 5: 커밋한다**

```bash
git add control_tower/bringup/p0_runtime_assets.py control_tower/tests/test_p0_runtime_assets.py
git commit -m "feat: wrap derived nav2 params in a root key for launchers without RewrittenYaml"
```

---

### Task 5: 실기 launch가 파생 params와 하나의 TF namespace를 쓰게 한다

**분기 A일 때만 수행한다.**

[trihouse_pinky.launch.py:74-88](../../trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_pinky.launch.py#L74-L88)은 지금 벤더 navigation에 `map`·`namespace`·`use_composition`만 준다. `params_file`을 주지 않으므로 벤더 기본 params(맨 키)가 쓰이고, TF 발행자(`robot_state_publisher`, 벤더 odom)는 루트 `/tf`에 남는다. 시뮬에서 확인한 것과 같은 두 실패다.

**Files:**
- Modify: `trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_pinky.launch.py`
- Create: `trihouse_pinky/trihouse_pinky_bringup/test/test_trihouse_pinky_launch.py`

**Interfaces:**
- Consumes: Task 4의 `derive_nav2_params(..., root_key=...)`
- Produces: launch 인자 `nav2_params_file`(기본값 `""`이면 벤더 기본값). 벤더 bringup include를 `SetRemap('/tf','tf')`·`SetRemap('/tf_static','tf_static')` 그룹으로 감싼다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`trihouse_pinky/trihouse_pinky_bringup/test/test_trihouse_pinky_launch.py`를 만든다.

```python
"""실기 Pinky launch 가 벤더 nav2 에 넘기는 계약."""

import importlib.util
import sys
from pathlib import Path

from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription
from launch_ros.actions import SetRemap

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "launch" / "trihouse_pinky.launch.py"

sys.path.insert(0, str(ROOT))


def _module():
    spec = importlib.util.spec_from_file_location("trihouse_pinky_launch", LAUNCH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _flatten(entities):
    for entity in entities:
        yield entity
        if isinstance(entity, GroupAction):
            yield from _flatten(entity.get_sub_entities())


def test_launch_declares_the_nav2_params_file_argument() -> None:
    """벤더 XML 은 RewrittenYaml 을 쓰지 않으므로 감싼 params 를 우리가 넘겨야 한다."""
    description = _module().generate_launch_description()
    names = {
        action.name
        for action in description.entities
        if isinstance(action, DeclareLaunchArgument)
    }

    assert "nav2_params_file" in names


def test_vendor_bringup_is_wrapped_in_a_tf_remap_group() -> None:
    """벤더 발행자의 TF 를 nav2 가 듣는 자리로 옮긴다.

    벤더 navigation XML 이 nav2 노드에 `/tf -> tf` 를 걸어 두어 nav2 는
    `/pinky_01/tf` 를 듣는다. 발행자가 루트에 남으면 AMCL 이 스캔을 전량
    폐기한다 — 시뮬에서 확인한 것과 같은 실패다.
    """
    description = _module().generate_launch_description()
    remapped = {
        (entity.src_key, entity.dst_key)
        for entity in _flatten(description.entities)
        if isinstance(entity, SetRemap)
    }

    assert len(remapped) >= 2
```

`SetRemap`의 속성 이름이 이 배포판에서 다르면 `vars(entity)`를 출력해 실제 이름으로 바꾼다. 개수 단정(`>= 2`)만으로도 계약은 지켜진다.

- [ ] **Step 2: 테스트를 돌려 RED를 확인한다**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  trihouse_pinky/trihouse_pinky_bringup/test/test_trihouse_pinky_launch.py
```

기대: 두 건 모두 FAIL.

- [ ] **Step 3: 인자를 선언한다**

`trihouse_pinky.launch.py`의 `DeclareLaunchArgument('map', default_value='')` 아래에 추가한다.

```python
        DeclareLaunchArgument('nav2_params_file', default_value=''),
```

상단 지역 변수에 더한다.

```python
    nav2_params_file = LaunchConfiguration('nav2_params_file')
```

- [ ] **Step 4: navigation include에 params를 넘긴다**

기존 include(74-81행)를 바꾼다.

```python
        # 벤더 XML 은 `<param from>` 으로 params 를 그대로 넘기고 RewrittenYaml 을
        # 쓰지 않는다. 그래서 `/pinky_01/amcl` 노드는 맨 키 `amcl:` 과 매칭되지
        # 않는다. `p0_runtime_assets.derive_nav2_params(..., root_key=namespace)`
        # 로 미리 감싼 파일을 넘겨 그 간극을 메운다.
        IncludeLaunchDescription(
            AnyLaunchDescriptionSource(navigation),
            launch_arguments={
                'map': map_path,
                'namespace': namespace,
                'use_composition': 'False',
                'params_file': nav2_params_file,
            }.items(),
        ),
```

- [ ] **Step 5: 벤더 bringup을 TF remap 그룹으로 감싼다**

기존 include(85-88행)를 바꾼다. `PushRosNamespace`는 **넣지 않는다** — 벤더 bringup이 자기 인자로 스스로 push하므로 두 번 감싸면 `/pinky_01/pinky_01/...`이 된다.

```python
        # 벤더 발행자(robot_state_publisher, odom)는 루트 `/tf` 에 쓴다. 그런데
        # 벤더 navigation XML 이 nav2 노드에 `/tf -> tf` 를 걸어 두어 nav2 는
        # `/pinky_01/tf` 를 듣는다. 그 갈라짐이 시뮬에서 AMCL 스캔 전량 폐기를
        # 일으켰다. 발행자 쪽에도 같은 상대 이름을 걸어 한 자리로 모은다.
        GroupAction([
            SetRemap('/tf', 'tf'),
            SetRemap('/tf_static', 'tf_static'),
            IncludeLaunchDescription(
                AnyLaunchDescriptionSource(vendor_bringup),
                launch_arguments={'namespace': namespace}.items(),
            ),
        ]),
```

- [ ] **Step 6: 테스트를 돌려 GREEN을 확인한다**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  trihouse_pinky/trihouse_pinky_bringup/test/test_trihouse_pinky_launch.py \
  trihouse_pinky/test/test_namespace_contract.py
```

기대: 전부 PASS. `test_namespace_contract.py`를 함께 돌려 온보드 노드 이름 규칙을 깨지 않았는지 확인한다.

- [ ] **Step 7: 커밋한다**

```bash
git add trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_pinky.launch.py \
        trihouse_pinky/trihouse_pinky_bringup/test/test_trihouse_pinky_launch.py
git commit -m "fix: give the real robot's nav2 namespaced params and one TF namespace"
```

---

### Task 6: 실기 카메라를 MediaMTX로 올린다

[trihouse_pinky.launch.py:41](../../trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_pinky.launch.py#L41)이 `vision_enabled` 인자를 **선언만 하고 쓰지 않는다.** 그래서 실기에서 `camera_streamer`가 뜨지 않고, 서버의 QR 인식([vision_edge/perception.py](../../vision_edge/perception.py))이 받을 스트림이 없다. 카메라는 ROS를 거치지 않고 RTSP로 간다.

**Files:**
- Modify: `trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_pinky.launch.py`
- Modify: `trihouse_pinky/trihouse_pinky_bringup/test/test_trihouse_pinky_launch.py`

**Interfaces:**
- Consumes: `trihouse_pinky_vision/launch/vision.launch.py`(인자 `config_file`)
- Produces: `vision_enabled:=true`일 때 `camera_streamer`가 로봇 namespace 안에서 뜬다. launch 인자 `vision_config_file`(기본값 `""`이면 vision launch의 기본 config).

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`test_trihouse_pinky_launch.py`에 추가한다.

```python
def test_vision_is_included_so_the_camera_reaches_mediamtx() -> None:
    """카메라는 ROS 를 거치지 않는다 — `camera_streamer` 가 ffmpeg 로 RTSP 를 민다.

    `vision_enabled` 를 선언만 하고 쓰지 않으면 실기에서 스트림이 아예 생기지
    않고, 서버의 QR·ArUco 인식이 받을 것이 없다.
    """
    description = _module().generate_launch_description()
    locations = [
        str(entity.launch_description_source.location)
        for entity in _flatten(description.entities)
        if isinstance(entity, IncludeLaunchDescription)
    ]

    assert any("vision.launch.py" in location for location in locations)


def test_launch_declares_the_vision_config_argument() -> None:
    description = _module().generate_launch_description()
    names = {
        action.name
        for action in description.entities
        if isinstance(action, DeclareLaunchArgument)
    }

    assert "vision_config_file" in names
```

- [ ] **Step 2: 테스트를 돌려 RED를 확인한다**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  trihouse_pinky/trihouse_pinky_bringup/test/test_trihouse_pinky_launch.py -k vision
```

기대: 두 건 모두 FAIL.

- [ ] **Step 3: vision launch를 조건부로 포함한다**

상단 import에 더한다.

```python
from launch.conditions import IfCondition
```

지역 변수에 더한다.

```python
    vision_enabled = LaunchConfiguration('vision_enabled')
    vision_config = LaunchConfiguration('vision_config_file')
    vision = PathJoinSubstitution([
        FindPackageShare('trihouse_pinky_vision'), 'launch', 'vision.launch.py',
    ])
```

인자를 선언한다.

```python
        DeclareLaunchArgument('vision_config_file', default_value=''),
```

`GroupAction([PushRosNamespace(namespace), ...])` 안, 온보드 노드 목록 끝에 더한다. namespace 안에 두어야 두 로봇의 카메라 노드가 섞이지 않는다.

```python
            # 카메라는 ROS 토픽으로 나가지 않는다. 이 노드는 ffmpeg 로
            # MediaMTX(PC1) 에 RTSP 를 밀고, 서버가 그것을 읽어 QR·ArUco 를
            # 인식한다(`vision_edge/perception.py`).
            IncludeLaunchDescription(
                AnyLaunchDescriptionSource(vision),
                launch_arguments={'config_file': vision_config}.items(),
                condition=IfCondition(vision_enabled),
            ),
```

`vision_config_file`이 비면 `vision.launch.py`의 기본값(`config/pinky_1.yaml`)이 쓰인다. 로봇마다 config가 다르면 로봇별 값을 인자로 준다.

- [ ] **Step 4: 테스트를 돌려 GREEN을 확인한다**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  trihouse_pinky/trihouse_pinky_bringup/test/test_trihouse_pinky_launch.py
```

기대: 전부 PASS.

- [ ] **Step 5: PC1의 `.env` 값이 채워져 있는지 확인한다**

커밋 `01595e9e`가 `.env.example`에 변수와 이유를 적어 두었다. 실제 값은 호스트의 `.env`에 있어야 하고 저장소에 커밋하지 않는다.

```bash
grep -n 'EDGE_BIND_ADDRESS\|MTX_VIEWER_PASS\|PINKY_PK_01_IP' .env
```

`EDGE_BIND_ADDRESS`는 **Ethernet 쪽 주소**여야 한다 — Wi-Fi 쪽에 바인딩하면 로봇이 못 붙는 동시에 8554가 바깥으로 노출된다. `PINKY_PK_01_IP`는 PK_01의 DHCP 예약 주소이며, 주소가 바뀌면 그 로봇만 조용히 발행에 실패한다(정책이 fail closed다).

- [ ] **Step 6: 스트림이 서버에 도달하는지 확인한다**

로봇을 `vision_enabled:=true`로 띄운 뒤 서버에서:

```bash
export VISION_RTSP_URL="rtsp://viewer:${MTX_VIEWER_PASS}@${PC1_LAN_IP}:8554/pinky/CAM-PK-01"
ffprobe -v error -rtsp_transport tcp -select_streams v:0 \
  -show_entries stream=codec_name,width,height,r_frame_rate \
  -of default=noprint_wrappers=1 "$VISION_RTSP_URL"
timeout 10 ffmpeg -nostdin -v error -rtsp_transport tcp -i "$VISION_RTSP_URL" \
  -map 0:v:0 -frames:v 1 -f framemd5 -
```

기대: codec `h264`, 프레임 1장 디코딩 성공. 실패하면 MediaMTX 쪽 path 상태를 본다.

```bash
curl --fail http://127.0.0.1:9997/v3/paths/list
```

- [ ] **Step 7: 커밋한다**

```bash
git add trihouse_pinky/trihouse_pinky_bringup/launch/trihouse_pinky.launch.py \
        trihouse_pinky/trihouse_pinky_bringup/test/test_trihouse_pinky_launch.py
git commit -m "feat: start the camera streamer on the real robot when vision is enabled"
```

---

### Task 7: 실기 PK_01 단일 로봇 주문 완주

Task 1과 **같은 성공 기준**을 실기에서 재현한다. 새 코드를 쓰지 않는다.

**Files:**
- Modify: `docs/validation/2026-08-18-p0-manual-test.md`

**Interfaces:**
- Consumes: Task 1의 성공 기준, Task 3의 분기 결정, Task 4·5·6의 launch 변경
- Produces: 실기 검증 기록

- [ ] **Step 1: 파생 params를 만든다 (분기 A만)**

관제 호스트에서:

```bash
python3 -c "
from pathlib import Path
import sys; sys.path.insert(0, '.')
from control_tower.bringup.p0_runtime_assets import derive_nav2_params
out = Path('.trihouse/p0/nav2/hardware_pinky_01.yaml')
out.parent.mkdir(parents=True, exist_ok=True)
derive_nav2_params(
    Path('pinky_pro/pinky_navigation/params/nav2_params.yaml'),
    'pinky_01', out, root_key='pinky_01',
)
print(out.read_text(encoding='utf-8').splitlines()[0])
"
```

기대: 첫 줄이 `pinky_01:`. 이 파일을 로봇으로 복사한다.

- [ ] **Step 2: 로봇을 기동한다**

로봇에서. **도메인 52**다.

```bash
export ROS_DOMAIN_ID=52
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
source /opt/ros/jazzy/setup.bash
source ~/trihouse_ws/install/setup.bash
```

분기 A:

```bash
ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK_01 namespace:=pinky_01 \
  map:=/path/to/map.yaml map_revision:=<승인된 revision> \
  nav2_params_file:=/path/to/hardware_pinky_01.yaml \
  control_host:=<관제 호스트 Ethernet IP> control_port:=8788 \
  vision_enabled:=true 2>&1 | tee /tmp/hw.log
```

분기 B(벤더 bringup이 namespace를 지원하지 않을 때):

```bash
ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK_01 namespace:='' \
  map:=/path/to/map.yaml map_revision:=<승인된 revision> \
  control_host:=<관제 호스트 Ethernet IP> control_port:=8788 \
  vision_enabled:=true 2>&1 | tee /tmp/hw.log
```

- [ ] **Step 3: lifecycle이 활성까지 갔는지 본다**

```bash
grep -c 'Managed nodes are active' /tmp/hw.log
grep -E 'Failed to bring up all requested|Failed to change state' /tmp/hw.log
```

기대: 첫 명령이 **2**(localization 1 + navigation 1), 두 번째가 빈 출력.

실기에는 Gazebo도 두 번째 로봇도 없으므로 시뮬의 부하 문제는 존재하지 않는다. **여기서 실패하면 부하가 아니라 실제 결함이다.**

- [ ] **Step 4: 로봇 상태를 읽는다**

관제 호스트에서:

```bash
ROS_DOMAIN_ID=52 python3 scripts/verify_robot_status.py pinky_01 20
```

분기 B에서는 namespace가 비었으므로 스크립트가 루트 토픽을 보도록 인자를 조정한다.

기대: `publishers=1`, `frame_id=map`, `dispatchable=true`, `errors=[]`.

오류가 남으면 출처를 이렇게 가른다.

| 오류 | 뜻 | 볼 곳 |
|---|---|---|
| `map_pose_stale` | `map -> base` 변환이 없음 = AMCL 미동작 | Task 5 Step 5가 적용됐는지, 벤더 bringup이 namespace를 물었는지 |
| `nav_unavailable` | `navigate_to_pose` 액션 서버 없음 | Step 3의 실패 줄 |
| `battery_stale` | `trihouse/battery`가 안 옴 | 실기 배터리 어댑터 프로세스 |
| `control_link_offline` | 8788 미연결 | 로봇에서 `nc -z <관제 IP> 8788` |
| `scan_stale`/`odom_stale` | 벤더 센서 노드가 namespace 밖에 있음 | Task 3 Step 1의 판정 |

- [ ] **Step 5: 주문 1건을 넣는다**

Task 1 Step 7과 같은 명령을 쓴다. `requested_by`와 `Idempotency-Key`만 `hw-pk01`로 바꾼다.

- [ ] **Step 6: 완주를 확인한다**

```bash
grep -E 'job runner cycle|job runner blocked' /tmp/hw.log | tail -5
curl -s http://127.0.0.1:8080/api/v1/jobs | python3 -m json.tool | head -40
```

기대: `claimed=` 1 이상, job이 `assigned` → `running` → 종료 상태. **로봇이 실제로 움직인다.**

`no free robot`이면 이전 job이 로봇을 쥔 것이니 **설계 8절 1~2번**의 엔드포인트로 회수한 뒤(**운영 DB 쓰기이므로 사용자 승인 필요**) 다시 시도한다.

- [ ] **Step 7: 카메라와 QR을 확인한다 (Task 6을 했을 때만)**

```bash
python3 -c "
import cv2
from vision_edge.perception import VisionPerception
import os
capture = cv2.VideoCapture(os.environ['VISION_RTSP_URL'])
ok, frame = capture.read()
assert ok, 'RTSP frame not received'
print(VisionPerception().detect_qr(frame))
"
```

기대: 물품 QR이 화면에 있으면 `QrObservation`, 없으면 `None`. **`None`이어도 스트림 도달과 디코더 동작은 확인된다** — 이 단계의 목적은 그것이다.

- [ ] **Step 8: 기록하고 커밋한다**

`docs/validation/2026-08-18-p0-manual-test.md`에 "7. 실기 PK_01 단일 로봇 완주" 절을 만들고 Step 1~7의 실제 출력을 적는다. 실패한 것이 있으면 **성공한 것과 함께 그대로 적는다.**

```bash
git add docs/validation/2026-08-18-p0-manual-test.md
git commit -m "docs: record the PK_01 hardware order run"
```

---

## 이 계획이 다루지 않는 것

명시적으로 범위 밖이며, 미룬 이유를 함께 적는다.

| 항목 | 이유 |
|---|---|
| 로봇팔(OMX) 물리 동작 | 다른 팀원 담당. `executor_worker`는 `OmxProtocolSimulator`로 프로토콜 왕복만 하고, 실제 모션 정책을 주면 기동을 거부한다 |
| RMF 낙찰 기반 시간대 예약(SR07), 긴급 비선점(SR41), 안전 재할당(SR08) | 단일 로봇에서는 greedy 배차와 결과가 같다. 2대 운용에 들어갈 때 필요하다 |
| `path_schedule.py`·`order_queue.py`·`task_orchestrator.py` 연결 | 구현과 테스트는 있으나 어느 실행 경로도 import하지 않는다. `path_schedule`은 두 로봇이 동시에 stubborn override를 쥐지 못하게 하는 **2대 운용의 안전 장치**이므로 2대 시험 전에 별도 계획이 필요하다 |
| ~~Gateway 취소 엔드포인트~~ | **범위에 들어왔다.** Task 2 를 대체한 [설계 8절 1번](2026-08-18-reservation-scheduling-design.md)이 그것이고 오늘의 첫 작업이다. 스크립트가 아니라 API 로 하는 이유는 행 잠금과 상태 전이 불변식이 이미 Gateway 저장소 안에 있어서, 두 곳에서 같은 전이를 하면 어긋나기 때문이다 |
| 시뮬 Gazebo 카메라 렌더링 끄기 | 로봇마다 1280×720@30 `always_on` 카메라가 GPU 없이 소프트웨어 렌더링되고, 그 토픽은 브리지되지 않아 아무도 쓰지 않는다(설계상 카메라는 RTSP로 나간다). 순수 낭비지만 `pinky_gz.urdf.xacro`가 보호 경로 `pinky_pro` 안이라 **사용자 승인이 필요하다.** 단일 로봇 축소로 당장은 우회한다 |
| 2대 동시 운용 | Task 3에서 분기 B로 갈렸다면 그 다음 날. 분기 A라도 `path_schedule` 연결이 선행되어야 한다 |
