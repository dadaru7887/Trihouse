# P0 스택 레퍼런스 — 2층 구조와 누적 질답

> 이 문서는 **날짜가 없다.** 계속 덧붙여 쌓는 살아 있는 문서이기 때문이다.
> `README.md` 의 `YYYY-MM-DD-<주제>-{design,plan}.md` 규칙은 스냅샷 문서에만 적용된다.
>
> 같은 내용의 시각 자료가 Artifact 로도 있다 — 그쪽은 이 문서의 **렌더된 사본**이고,
> **정본은 여기다.** 내용이 갈라지면 이 파일이 맞다.

---

## 1. 큰 그림 — 왜 두 층인가

시스템은 **Docker 층**과 **호스트 ROS 2 층**으로 갈라져 있다. 가르는 기준은 하나다 —
`rclpy`·DDS·GPU 가 필요한 것은 컨테이너에 넣지 않았다. DDS 는 호스트 네트워크와
공유메모리를 직접 쓰므로 컨테이너에 가두면 discovery 가 어긋난다.

다섯 층(L1~L5) 중 **L1·L2 는 Docker 에서, L3·L4·L5 는 호스트에서** 돈다.

```text
1층  Docker            scripts/control_stack up
     mysql · fms_gateway · mediamtx · rmf_api · rmf_dashboard · control_ui
────────────────────────────────────────────────────────────────────
     경계 규칙: rclpy·DDS·GPU 가 필요하면 호스트에 둔다
────────────────────────────────────────────────────────────────────
2층  호스트 ROS 2      control_tower/bringup/p0_simulation_bringup.sh
     rmf_traffic_schedule · Gazebo + Pinky×2 · Nav2×2 · fleet adapter×2
     OMX 시뮬×2 · job_runner · executor_worker · rmf_gateway_worker
```

2층은 **포그라운드**로 돈다. `Ctrl+C` 한 번으로 거기서 띄운 것이 모두 정리되고
1층은 그대로 남는다. 두 층의 수명주기는 독립이다.

---

## 2. 1층 — Docker 가 맡는 것

| 컨테이너 | 무엇 | 호스트 포트 | 이 검증에서 |
|---|---|---|---|
| `trihouse-mysql` | `trihouse_fms`(운영)와 `trihouse_recovery`(복구 데이터셋 그릇) 두 DB | `3308 → 3306` | **L1 판정 대상** |
| `fms_gateway` | FastAPI 라우트 44개. **DB 트랜잭션을 하는 유일한 곳** | `8080` · `8788` | **L2 판정 대상** |
| `mediamtx` | 미디어 서버. 로봇 카메라가 RTSP 를 밀어 넣는 곳 | `8554` · `8888-8889` · `8189/udp` · `9996-9998` | 카메라 단계만 |
| `rmf_api` | Open-RMF API 서버. 대시보드의 백엔드 | 게시 없음(의도) | 안 씀 |
| `rmf_dashboard` | Open-RMF 웹 대시보드 | `3000 → 80` | 안 씀 |
| `control_ui` | Flutter 웹을 nginx 로 서빙하는 관제 화면 | `3100 → 80` | 안 씀 |

뒤의 셋은 켜져 있어도 **성공 기준에 넣지 않는다** — UI 를 판정 경로에서 뺀 검증이다.
꺼도 L1~L5 판정은 똑같이 된다.

**정상 개수는 6이다.** `qr_worker` 와 `recording_catalog` 는
`profiles: [application_images]` 로 막혀 있고, 이미지가 아직 구현되지 않았다
([environment_overview.md](../deployment/environment_overview.md) 가 "QR·catalog image
구현 필요"로 적어 둔 그것이다). 이름을 직접 지정해 기동하면 그 차단을 우회해
`pull access denied` 가 난다.

---

## 3. 2층 — 호스트 ROS 2 가 맡는 것

| 프로세스 | 층 | 하는 일 |
|---|---|---|
| `rmf_traffic_schedule` | L3 | 경로 예약 중재. 병목 `mutex_group` 을 실제로 강제하는 곳 |
| Gazebo + Pinky ×2 | L4 | **로봇 실물을 대신한다.** 바퀴·LiDAR·오도메트리가 여기서 나온다 |
| Nav2 (로봇마다) | L4 | 자율주행. AMCL 위치추정과 경로계획 |
| fleet adapter ×2 | L3↔L4 | 로봇 상태를 RMF 에 등록하고 작업을 받아온다 |
| OMX 시뮬 ×2 | L5 | 로봇팔 프로토콜 응답. **실제 파지는 어느 환경에서도 아직 안 된다** |
| `job_runner_node` | L3 | `queued` job 에 자원을 배정하고 현재 step 을 outbox 로 내보낸다 |
| `executor_worker_node` | L3 | step 실행 결과를 처리한다 |
| `rmf_gateway_worker_node` | L3 | outbox 행을 claim 해 RMF 로 넘긴다 |

**러너와 worker 는 짝이다.** 러너가 outbox 에 내보내야 worker 가 claim 할 것이 생긴다.
러너 없이 worker 만 띄우면 주문이 들어와도 로봇이 움직이지 않는데, 오류가 아니라
**침묵**으로 나타나 찾기 어렵다.

L3 의 세 노드는 **DB 에 직접 붙지 않는다.** 전부 HTTP 로 Gateway 를 거친다 —
"DB 트랜잭션은 Gateway 만, 상태 전이 확정은 Task Manager 만" 이 설계 경계다.

---

## 4. 켜는 순서

### 1층

```bash
# mysql → fms_gateway → mediamtx → rmf_api → rmf_dashboard → control_ui
# 앞의 것이 healthy 가 된 뒤에 다음을 올린다. 1~2분.
cd /home/syw/Trihouse
scripts/control_stack up
```

한꺼번에 올리지 않는 이유는 Gateway 가 MySQL 없이 뜨면 `/ready` 가 실패한 채로
살아 있게 되기 때문이다. 순서와 healthy 대기가 그 상태를 막는다.

### 2층

```bash
# L1·L2 를 통과한 뒤에만 켠다.
TRIHOUSE_MAP_REVISION="trihouse_test_01:730111d2…" \
TRIHOUSE_ROBOTS=PK_01 \
ROS_DOMAIN_ID=0 \
control_tower/bringup/p0_simulation_bringup.sh 2>&1 | tee /tmp/sim.log
```

`scripts/control_stack ros` 가 같은 스크립트를 부른다. 기동에 1~2분 걸리고,
파이프를 쓰면 종료코드가 가려지므로 판정은 로그로 한다.

### 전부 내리고 처음부터

```bash
scripts/sim_teardown.sh      # 2층 정리. leftover=0, fastrtps_shm_left=0 확인
scripts/control_stack down   # 1층 내리기. 볼륨은 안 지운다(-v 없음)
docker ps -a --format '{{.Names}}\t{{.Status}}'   # 비어 있어야 한다
docker volume ls | grep trihouse                  # 볼륨은 남아야 정상
scripts/control_stack up
```

---

## 5. 왜 1층만 먼저 켜는가

**L1·L2 가 ROS 를 쓰지 않는다.** DB 와 Gateway 는 컨테이너만으로 판정된다. 안 쓰는
것을 켜면 판정에 기여하지 않으면서 변수만 늘어난다.

**부하 때문이다.** 12코어 노트북에서 Gazebo 와 로봇 2대의 Nav2 와 RMF 를 함께 올리면
load average 가 60~90 까지 간다. 그 상태에서는 Nav2 lifecycle 이 스스로 포기하고
`ros2 topic list` 도 멈춘다. **결함이 아닌 실패**가 섞여 들어온다. 그래서 단일
로봇이 기본이다.

**순서가 진단 능력을 만든다.** 이 저장소에서 벽 네 개가 순차적으로만 관측된 기록이
있다 — 예약 회수를 고치니 costmap 프레임이 보이고, 그것을 고치니 RMF worker 사망이
보이고, 그것을 고치니 fleet 등록 실패가 보였다. 다 켜놓고 시작하면 그 넷이 한
덩어리로 뭉쳐 어느 것이 원인인지 말할 수 없다.

---

## 6. 두 층이 어긋나는 자리

| 함정 | 옳은 것 |
|---|---|
| `ROS_DOMAIN_ID` | 시뮬 **0**, 실기 **52**. Docker 층의 `rmf_api` 가 0 이므로 2층도 0 이어야 한다. 어긋나면 **오류 없이** 서로를 못 본다 |
| DDS transport | domain 이 같아도 전송 방식이 어긋나면 못 본다. FastDDS 기본값은 공유메모리를 함께 광고하는데, 그러면 요청은 도착하고 **응답만 못 돌아온다**. 스크립트가 두 층의 값을 같게 못박아 두었다 |
| `EDGE_BIND_ADDRESS` | 접속할 주소가 아니라 **이 컴퓨터가 귀를 열 주소**다. 그 IP 가 이 호스트의 인터페이스에 없으면 `cannot assign requested address` 로 실패한다 |
| bringup 이 `.env` 를 안 읽음 | 의도된 것이다. `.env` 에는 비밀값이 있고 source 하면 모든 ROS 노드 환경으로 샌다. 두 층의 기본값을 같게 적어 두는 쪽을 택했고, 그 일치는 테스트가 지킨다 |
| 프로세스 정리 | `pkill -f` 를 직접 쓰지 않는다 — 자기 자신과 Docker 안 ROS 프로세스까지 죽인다. `scripts/sim_teardown.sh` 를 쓴다. 단 이 스크립트는 같은 셸의 pytest 도 죽인다 |
| RViz 가 `map` 을 못 찾음 | TF 가 전역 `/tf` 가 아니라 **`/pinky_01/tf`** 에 있다. nav2 노드가 `__ns:=/pinky_01` + `-r /tf:=tf` 로 뜨기 때문이다. 결함이 아니라 두 로봇이 `/map`·`/amcl_pose` 를 공유하지 않게 한 격리의 대가다. 외부 도구는 remap 해서 붙는다 — `rviz2 --ros-args -p use_sim_time:=true -r /tf:=/pinky_01/tf -r /tf_static:=/pinky_01/tf_static` |
| 상태 판정 | 부하가 높으면 `ros2 topic list`·`node list`·`param get` 이 멈춘다. `scripts/verify_robot_status.py <namespace> <초>` 로 읽는다 |

> **되돌릴 수 없는 것.** 주문 생성은 재고 lot 을 실제로 소진하고, job 취소는
> **재고 예약을 돌려주지 않는다.** 그래서 재고를 먼저 읽고 나서 취소를 판단한다.
> 순서를 뒤집으면 갇힌 재고를 원장 직접 수정으로만 되찾을 수 있다.

---

## 7. 누적 질답

새 질문이 나오면 **아래에 덧붙인다.** 답이 나중에 틀린 것으로 드러나면 지우지 말고
정정을 아래에 적고 원래 답에 표시를 남긴다.

### Q. `trihouse*` 로 뜬 컨테이너들이 각각 뭘 의미하는가

2절 표가 답이다. 이름 규칙만 덧붙이면 — `trihouse_p0-` 접두사는 Compose 프로젝트
이름(`--project-name trihouse_p0`)이고 끝의 `-1` 은 복제본 번호다. `trihouse-mysql`
만 접두사가 없는데 compose 파일이 `container_name` 을 직접 지정했기 때문이다.

### Q. 왜 8개가 아니라 6개인가

설계 문서(`2026-08-18-backend-manual-test-design.md` L1 절)가 8개라고 적었지만
**틀렸다.** compose 파일에 정의만 있고 `profiles` 로 막혀 실행되지 않는 둘까지 센
숫자다. 정본은 [environment_overview.md](../deployment/environment_overview.md) 이고
거기에 "QR·catalog image 구현 필요"로 적혀 있다. **L1 통과 기준을 6으로 고쳐야 한다.**

### Q. `rmf_api` 도 포트가 없는데 mediamtx 와 같은 문제인가

아니다. `rmf_api` 는 대시보드가 Compose 내부 네트워크로 접근하므로 호스트에 노출할
이유가 없다 — **의도된 설계**다. mediamtx 의 빈 포트는 바인딩 실패의 결과였다.
겉보기 증상이 같고 원인이 다르다.

### Q. 서버 PC(192.168.0.9)를 켜 놨는데 왜 바인딩이 실패하나

`EDGE_BIND_ADDRESS` 는 **접속할 주소가 아니라 이 컴퓨터가 소켓을 열 주소**다.
Docker 가 귀를 여는 쪽은 이 노트북이고, 그러려면 그 IP 가 **이 노트북의 랜카드에
붙어 있어야** 한다. `192.168.0.9` 는 서버의 주소이므로 이 노트북에서는 어떤 방법으로도
열 수 없다. 서버를 켜면 오히려 그 주소는 확실히 저쪽 것이 된다.

이 노트북은 `192.168.129.9/17`(wlo1)이고 서버는 `192.168.0.9` 라 대역도 다르다.
이 PC 에서 테스트하는 동안은 `EDGE_BIND_ADDRESS=127.0.0.1` 이 맞다.
**실기 트랙에서는 그 서버 PC 에서 그 서버 자신의 Ethernet 주소로 두어야 한다.**

`PC1_LAN_IP` 는 바꾸지 않았다 — 로봇의 카메라 송신 설정
(`trihouse_pinky_vision/config/pinky_1.yaml` 의 `publish_uri`)이 그 값을 본다.

### Q. 시뮬레이션 단계에서 실물 로봇이 없어도 되는가

**된다.** 로봇을 대신하는 것이 네 겹으로 들어가 있다.

| 실물 | 시뮬에서 대신하는 것 |
|---|---|
| 로봇 본체·바퀴·LiDAR | Gazebo `ros_gz_sim` spawn |
| 배터리·초음파 | `sim_hardware` 노드가 `trihouse/battery`·`trihouse/proximity/front` 직접 발행 |
| 로봇팔 | `gazebo_omx_adapter` |
| 카메라 | MediaMTX fixture 스트림 (`config/cameras.yaml` 의 `simulation_path`) |

즉 L1 → L2 → L3 → L4(주행)까지 실물 없이 끝까지 볼 수 있다.

**시뮬로는 못 보는 것 셋:**

1. **LED·부저·OLED** — `sim_hardware` 는 배터리와 초음파만 낸다. GPIO 표시장치는
   대역이 없어 실물에서만 확인된다
2. **실제 카메라 영상** — fixture 스트림이라 경로와 디코더는 확인되지만 렌즈·조명·
   QR 인식률은 확인되지 않는다
3. **로봇팔의 실제 파지** — 시뮬 한계가 아니라 **아직 어디서도 안 된다.**
   `hardware_adapter_node` 가 `"motion remains disabled until hardware plugin is
   approved"` 인 진단 전용 skeleton 이다

### Q. `docs/claude/` 문서만으로 작업을 시작할 수 있는가

**"claude 폴더만 읽으면 된다"는 뜻이면 아니다.** `START-HERE.md` 2절이 바깥 정본
20여 개를 가리키며 "내용이 어긋나면 바깥이 정본"이라고 못박았다. 특히 성공 기준의
상태 문자열은 `db/schema_mysql.sql` 의 `CHECK` 에서 온다.

**"이 PC 에서 START-HERE.md 부터 시작하면 되는가"라면 그렇다.** 가리키는 바깥 경로
40개를 확인했고 파일은 전부 존재한다. 끊긴 링크는 없다.

**다만 다른 PC 로 clone 하면 따라가지 않는다.** `docs/claude/` 와
`docs/superpowers/` 가 `.gitignore` 에 있고, 참조 대상 중 5개가 미추적이다.
`docs/validation/2026-08-18-pinky-hardware-nav2-smoke.md` 는 커밋돼 있어 따라간다.

### Q. 아무 작업도 안 했는데 왜 job 이 `cancelled`·`assigned` 로 있는가

**DB 볼륨이 살아남기 때문이다.** `control_stack down` 은 컨테이너만 지우고 볼륨은
남긴다(`-v` 없음). `created_at` 이 `2026-08-16` 인 이전 세션 데이터가 그대로 있는
것이고, 이것은 의도된 것이다 — 그래서 L1 에서 읽을 값이 있다.

두 상태는 서로 다른 사건이다.

- **`cancelled`** — 이전 세션에서 사람이 취소 엔드포인트로 정리했다. 자원 예약은
  회수됐지만 **재고 예약은 안 돌아왔다**(아래 질문)
- **`expired`** — `job_runner` 가 매 주기 부르는 `reservations/expire` 가 job 4 의
  자원 예약을 밀었다. 그런데 job 은 `assigned` 로 남았다. step 의 outbox 가
  `dead_letter`(`DISPATCH_ATTEMPTS_EXHAUSTED`)라 재시도되지 않아 **진행도 종료도
  못 하는 상태**가 됐다

### Q. `reserved_qty` 가 왜 잡혀 있고, 그냥 0 으로 바꾸면 되는가

**그냥 바꾸면 안 된다.** 살아 있는 job 이 참조 중인 예약과 고아 예약이 섞여 있다.
`job_items` 로 대조해야 갈린다.

```sql
SELECT ji.job_id, j.state AS job_state, ji.product_code, ji.lot_id,
       ji.requested_qty, il.available_qty, il.reserved_qty
  FROM trihouse_fms.job_items ji
  LEFT JOIN trihouse_fms.jobs j  ON j.job_id  = ji.job_id
  LEFT JOIN trihouse_fms.inventory_lots il ON il.lot_id = ji.lot_id
 ORDER BY ji.job_id, ji.lot_id;
```

살아 있는 job 의 예약을 풀면 **그 job 이 없는 재고를 집으러 간다.** 순서가 있다.

1. 잔여 job 을 먼저 취소한다 — `POST /internal/v1/jobs/{id}/cancel`
2. 살아 있는 job 이 0 건임을 확인한다
3. 그때 남은 `reserved_qty` 는 전부 고아이므로 원장을 직접 고친다

`UPDATE ... SET reserved_qty = 0` 은 `available_qty` 를 건드리지 않는다. 2026-08-18
기준 정리 후 **11개 lot / available 17 / reserved 0** 이 기준선이다.

### Q. `RMF dispatch cycle: claimed=0` 이 계속 찍히는데 문제인가

아니다. job 을 전부 취소해 claim 할 것이 없는 상태이고 **루프 자체는 정상**이다.
`claimed=0` 은 결과이지 원인이 아니다. 판정은 로그가 아니라 **프로세스 목록**으로
한다 — `pgrep -af 'gz sim|nav2|amcl|fleet_adapter'`.

### Q. `TRIHOUSE_ROBOTS` 에 `pinky_01` 을 넣었더니 launch 가 죽는다

`TRIHOUSE_ROBOTS` 는 **`robot_id`(`PK_01`)** 를 받는다. namespace(`pinky_01`)가
아니다. 둘은 섞지 말라고 `two_pinky_order_demo.launch.py` docstring 이 경고하는
그 쌍이다 — `robot_id` 는 관제·감사용 식별자, `namespace` 는 DDS 이름공간이다.

```text
[ERROR] [launch]: 모르는 robot id 입니다: pinky_01. 고를 수 있는 것: PK_01, PK_02
```

`backend-manual-test-design.md` 0.2 절이 **namespace 도 받도록 한 줄 고치자고
제안**했고 그 뒤 절들은 고친 뒤의 값으로 적혀 있다. 그 변경은 아직 안 됐다.
**오늘 실행할 때는 `PK_01`** 이다.


---

## 8. 이 세션에서 고친 것

| 무엇 | 왜 |
|---|---|
| `EDGE_BIND_ADDRESS` `192.168.0.9` → `127.0.0.1` | 이 호스트에 없는 주소라 mediamtx 가 기동 실패. 시뮬만 하는 동안은 loopback 이면 충분하다 |
| `.env.p0`, `.env.bak.*` 2개 삭제 | 셋 다 `.env` 의 부분집합이고 값이 다른 키는 `FMS_DB_PORT` 하나(3306, 포트 충돌 시절 잔여물). `control_stack` 은 이제 `.env` 만 읽는다 |
| `control_ui` 이미지 재빌드 | 이미지가 `2026-08-16 16:40`, 마지막 커밋이 `2026-08-18 10:13` 로 낡아 있었다 |

**남은 정리 대상:** `scripts/control_stack:42` 의 주석과
`docs/runbooks/2026-08-16-p0-manual-test.md` 가 아직 `.env.p0` 를 만들라고 한다.
코드는 이미 `.env` 만 읽으므로 동작에는 영향이 없지만, 그 런북을 따르면 헛일을 한다.

---

## 9. 수동 검증 명령 — 단계별 누적

여기에는 **명령과 기대값**만 쌓는다. 실제로 나온 출력은 `docs/validation/` 에 적는다
(README 의 역할 분리). 통과한 단계는 그대로 두고 아래에 다음 단계를 덧붙인다.

### 0단계 — 스택 기동 (통과)

```bash
# 0-1. 전부 내린다. 볼륨은 지우지 않는다(-v 없음) — DB 데이터가 살아남아야 한다
cd /home/syw/Trihouse
scripts/sim_teardown.sh
scripts/control_stack down

# 0-2. 정말 비었는지 본다
docker ps -a --format '{{.Names}}\t{{.Status}}'   # 기대: 빈 출력
docker volume ls | grep trihouse                  # 기대: 볼륨 3개 남음

# 0-3. 기동
scripts/control_stack up

# 0-4. 컨테이너 6개 + mediamtx 포트 게시
docker ps --format '{{.Names}}\t{{.Status}}' | sort
docker ps --format '{{.Names}}\t{{.Ports}}' | grep mediamtx

# 0-5. 경계를 직접 두드린다
curl -s -o /dev/null -w 'control_ui   %{http_code}\n' http://127.0.0.1:3100/
curl -s -o /dev/null -w 'rmf_dash     %{http_code}\n' http://127.0.0.1:3000/
curl -s http://127.0.0.1:8080/ready; echo
```

기대값: 컨테이너 **6개** `Up`, mediamtx Ports 에 `127.0.0.1:8554` 외 4개,
`200` / `200` / `{"status":"ready","database":"ok"}`.

볼륨 3개가 남는 것이 정상이다 — `trihouse_p0_trihouse_mysql_data`(P0 운영 DB),
`trihouse_p0_trihouse_map_runtime`(맵 런타임 자산),
`trihouse_db_mysql_data`(`compose.db.yaml` 의 별개 개발 DB, P0 와 무관).

### L1 — DB (읽기 전용)

```bash
# 1-a. root 비밀번호를 셸에 잡는다. 이후 쿼리가 전부 $PW 를 쓰므로 같은 셸을 유지한다
cd /home/syw/Trihouse
PW=$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-); echo "len=${#PW}"

# 1-b. 테이블 6개가 오류 없이 응답하는가. 행 수가 아니라 SELECT 가 도는 것이 기준이다
docker exec trihouse-mysql mysql -uroot -p"$PW" --table -e "
SELECT 'jobs' AS tbl, COUNT(*) AS rows_n FROM trihouse_fms.jobs
UNION ALL SELECT 'job_steps',            COUNT(*) FROM trihouse_fms.job_steps
UNION ALL SELECT 'reservations',         COUNT(*) FROM trihouse_fms.reservations
UNION ALL SELECT 'integration_messages', COUNT(*) FROM trihouse_fms.integration_messages
UNION ALL SELECT 'map_projects',         COUNT(*) FROM trihouse_fms.map_projects
UNION ALL SELECT 'inventory_lots',       COUNT(*) FROM trihouse_fms.inventory_lots;
" 2>&1 | grep -v 'password on the command line'

# 1-c. 재고 — job 취소보다 반드시 먼저 읽는다
#      취소는 재고 예약을 돌려주지 않는다. 순서를 뒤집으면 갇힌 재고를
#      원장 직접 수정으로만 되찾게 된다
docker exec trihouse-mysql mysql -uroot -p"$PW" --table -e "
SELECT lot_id, product_code, lot_code, available_qty, reserved_qty, state
  FROM trihouse_fms.inventory_lots ORDER BY lot_id;
" 2>&1 | grep -v 'password on the command line'

# 1-d. 현재 점유 — 누가 로봇을 쥐고 있는가. 비종료 상태 4개만 본다
docker exec trihouse-mysql mysql -uroot -p"$PW" --table -e "
SELECT job_id, job_code, state, operation_type,
       IFNULL(assigned_mobile_id,'-') AS robot, created_at
  FROM trihouse_fms.jobs
 WHERE state IN ('queued','assigned','running','held')
 ORDER BY job_id;
" 2>&1 | grep -v 'password on the command line'

# 1-e. 예약이 어느 job 에 묶여 있는가 — 1-c 와 대조할 근거
#      job_state 가 종료 상태인데 res_state 가 살아 있으면 그것이 누수다
docker exec trihouse-mysql mysql -uroot -p"$PW" --table -e "
SELECT r.reservation_id, r.job_id, j.state AS job_state, r.state AS res_state,
       IFNULL(r.device_id, CONCAT('location:', r.location_id)) AS resource,
       IFNULL(r.active_resource_key,'(none)') AS active_key
  FROM trihouse_fms.reservations r
  LEFT JOIN trihouse_fms.jobs j ON j.job_id = r.job_id
 ORDER BY r.reservation_id;
" 2>&1 | grep -v 'password on the command line'

# 1-f. recovery 그릇 확인 — 그릇이 있는지만 판정한다
docker exec trihouse-mysql mysql -uroot -p"$PW" --table -e "
SHOW DATABASES;
SELECT TABLE_NAME FROM information_schema.TABLES
 WHERE TABLE_SCHEMA='trihouse_recovery';
SELECT COUNT(*) AS cross_db_fk FROM information_schema.REFERENTIAL_CONSTRAINTS
 WHERE CONSTRAINT_SCHEMA='trihouse_recovery' AND UNIQUE_CONSTRAINT_SCHEMA='trihouse_fms';
SELECT COUNT(*) AS recovery_episodes FROM trihouse_recovery.recovery_episodes;
SELECT COUNT(*) AS recovery_steps    FROM trihouse_recovery.recovery_steps;
SHOW GRANTS FOR 'fms_gateway'@'%';
" 2>&1 | grep -v 'password on the command line'
```

기대값:

| 확인 | 기준 |
|---|---|
| 1-b 테이블 6개 | 6행 반환, 오류 없음 |
| 1-c 재고 | 숫자를 미리 못박지 않는다. **읽은 값 자체가 산출물**이고 그것으로 주문 예산이 정해진다 |
| 1-d 점유 | 같음. 여기 나온 `job_id` 가 취소 승인 게이트의 후보다 |
| 1-e 예약 | 종료된 job 을 참조하는데 `res_state` 가 살아 있으면 누수로 기록한다 |
| 1-f DB 2개 | `trihouse_fms` 와 `trihouse_recovery` 둘 다 |
| 1-f 회복 테이블 | `recovery_episodes`, `recovery_steps` **2개** |
| 1-f 교차 DB FK | **0개.** 설계상 금지다 |
| 1-f 행 수 | 두 테이블 모두 **0행**. 완주 뒤에 다시 세어 여전히 0행임을 확인한다 |
| 1-f 권한 | 통과 기준이 아니다. **기록만 한다** |

---

## 10. 관측된 결함 — 고치지 않고 기록만 한다

| # | 무엇 | 근거 |
|---|---|---|
| D1 | **bringup 이 로봇 launch 가 죽어도 성공으로 보고한다.** `two_pinky_order_demo` 가 예외로 죽었는데 `"P0 ROS 층이 올라왔습니다"` 를 출력했다. 로봇이 하나도 없는데 통과로 보인다 | `/tmp/sim.log` 의 `Caught exception in launch` 가 성공 문구 **뒤에** 찍힌다 |
| D2 | **job 취소가 재고 예약을 돌려주지 않는다.** 자원 예약(`reservations`)은 닫히는데 `inventory_lots.reserved_qty` 는 남는다. 되찾는 API 가 없어 원장 직접 수정뿐이다 | 취소된 job 2·3 이 lot 3·6 의 `reserved_qty` 를 남긴 채였다 |
| D3 | `.env.p0` 참조가 남아 있다. `scripts/control_stack:42` 주석과 `docs/runbooks/2026-08-16-p0-manual-test.md` 가 아직 그 파일을 만들라고 한다. 코드는 `.env` 만 읽는다 | 파일은 2026-08-18 에 삭제됨 |
| D4 | 설계의 L1 통과 기준이 컨테이너 **8개**로 적혀 있으나 실제는 **6개**다. `profiles` 로 막힌 미구현 둘을 셌다 | `environment_overview.md` 가 "QR·catalog image 구현 필요" 로 적어 둔 그것 |
| D5 | **`control_link_offline` 이 TCP 가 붙어 있는데도 굳는다.** `gateway_node._publish_link_state()` 는 연결 상태가 **바뀔 때만** 발행하는데 publisher QoS 가 기본값(`VOLATILE`)이라 나중에 뜬 `status_node` 는 그 한 번을 놓친다. 그러면 `dispatchable=False` 로 남아 **RMF 가 로봇을 안 받는다** | 소켓은 `ESTAB`(`fleet_gateway → 127.0.0.1:8788`)인데 `/pinky_01/trihouse/fms/state` 를 8초 구독해 **0건** 수신. publisher 는 1 |

**판정 규칙:** bringup 의 성공 문구를 믿지 않는다. 층이 실제로 떴는지는 항상
프로세스 목록과 `Managed nodes are active` 개수로 확인한다.

| D6 | **`--gui` 가 Gazebo 창을 열지 못한다.** launch 는 언제나 `gz sim -r -s`(서버 전용)만 띄우고, `headless:=false` 는 `--headless-rendering` 문자열을 뗄 뿐 GUI 클라이언트를 시작하는 코드가 없다 | [two_pinky_order_demo.launch.py:471-476](../../trihouse_rmf_bridge/launch/two_pinky_order_demo.launch.py#L471-L476) |

### D6 을 지금 푸는 법

Gazebo GUI 는 **돌고 있는 서버에 나중에 붙을 수 있다.** 시뮬을 내리지 않아도 된다.

```bash
gz sim -g          # GUI only. 실행 중인 서버에 attach
```

RViz 도 따로 붙인다. `--rviz` 는 `rmf_core.launch.py` 의 `start_visualization` 으로만
가고 RViz2 를 직접 띄우지 않는다.

```bash
source /opt/ros/jazzy/setup.bash && source install/setup.bash
export ROS_DOMAIN_ID=0
rviz2 --ros-args -p use_sim_time:=true
# Fixed Frame: map / Add: RobotModel, LaserScan(/pinky_01/scan),
#              Map(/pinky_01/map), Path(/pinky_01/plan)
```

**근본 수정**: launch 에 `gz sim -g` 를 조건부 `ExecuteProcess` 로 추가한다.
`headless` 인자가 이미 있으므로 그 반대일 때 붙이면 된다.

| D7 | **`finishing_request: "charge"` 가 시뮬 로봇을 영구히 묶는다.** 유휴 시 RMF 가 `ChargeBattery` 작업을 만들고 **항상 100% 를 목표로** 한다. 시뮬 배터리는 100% 에서 더 오르지 않으므로 그 작업이 끝나지 않고, 로봇이 작업 중이라 배송 dispatch 가 거절된다 → attempts 소진 → `dead_letter` | `Robot [PK_01] is still waiting for its battery to charge to 100.0%. The current battery percentage is 100.0% ... 0.0 %/hour` 가 60초마다 반복 |

### D7 — `recharge_soc` 와 `finishing_request` 는 다른 것을 제어한다

처음에 `recharge_soc: 1.000` 이 원인이라고 보고 `0.300` 으로 고쳤으나 증상이 남았다.
둘은 서로 다른 경로다.

| 키 | 언제 쓰이나 |
|---|---|
| `recharge_soc` | 배터리가 `recharge_threshold`(10%) **아래로 떨어져** 자동 충전이 걸릴 때 어디까지 채우는가 |
| `finishing_request` | **할 일이 없을 때** 무엇을 하는가. `charge` 면 `ChargeBattery` 작업을 만들고 목표는 **항상 100%** |

배터리가 100% 면 `recharge_threshold` 를 건드리지 않으므로 `recharge_soc` 는 발동조차
하지 않는다. 막는 것은 `finishing_request` 다.

정본([parameters_for_rmf.md:107](../guideline/parameters_for_rmf.md))은 "10% 부근 → 30%
이상"으로 **충전 임계와 목표치**만 정한다. 유휴 시 100% 충전은 정본이 요구하지 않는다.

| 값 | 유휴 시 | 막힘 |
|---|---|---|
| `charge` | 충전소로 가서 100% 까지 | **영원히 안 끝남** |
| `park` | 주차 지점으로 이동 | 없음. 로봇이 이미 `is_parking_spot` 위면 제자리 |
| `nothing` | 아무것도 안 함 | 없음 |

2026-08-18 기준 `recharge_soc: 0.300`(정본 준수) + `finishing_request: "park"` 으로 둔다.

**설정을 고치면 시뮬을 재기동해야 한다.** 어댑터는 시작할 때 한 번만 읽는다.
`install/.../pinky_fleet.yaml` 은 원본으로 가는 symlink 라 `colcon build` 는 필요 없다.

| **D8** | **`RosTaskSummaryObserver` 가 런타임에 붙지 않는다.** RMF 는 제출 즉시 booking 만 만들고 배정은 입찰이 끝난 뒤(실측 약 7초) 정해진다. 그 배정을 FMS 로 되돌려 줄 observer 가 코드로만 있고 아무도 `attach()` 를 부르지 않는다. 그래서 outbox 가 `RMF_ASSIGNMENT_PENDING` 에서 못 벗어나고 재시도 5회를 소진해 `dead_letter` 가 된다. **주문이 로봇을 못 움직이는 진짜 원인** | `ros_task_client.py:109` `RosTaskSummaryObserver`, `:116` `attach()`. `attach` 호출처 **0곳**. `rmf_gateway_worker_node.main()` 은 `RosTaskApiClient`(제출)만 만든다 |

### D8 — 오늘 job 4·6·7·8 이 모두 여기서 죽었다

```text
1. 워커가 RMF 에 작업 제출          booking 수락, assignment=None (입찰 전이라 정상)
2. RMF_ASSIGNMENT_PENDING 으로 두고 message 는 sent 유지
3. RMF 가 입찰을 끝내고 PK_01 에 낙찰   ← 로그: "Bid ... awarded", "TaskAssignments updated"
4. 그 사실을 FMS 로 되돌릴 observer 가 없다   ← 끊김
5. 워커가 같은 message 를 재시도 → attempts 5 소진 → dead_letter
6. step 20 은 영원히 pending, 로봇은 움직이지 않는다
```

`rmf_gateway_worker.py:106-118` 의 주석이 이 상황을 예고한다 — "assignment
**observer**/cancel 확인 전까지 sent 상태를 유지해 실행을 차단한다". 그 observer 가
배선되지 않았다.

**부하와 무관하다.** RTF 0.19 에서도 0.71 에서도 같은 자리에서 멈췄다. 부하는 별개로
`PINKY_NOT_READY` 를 유발했지만(D7 이후에도 간헐), 완주를 막은 것은 D8 이다.

**같은 종류의 것이 셋이다** — 설계 3절이 "런타임에 도는 것과 모듈이 존재하는 것은
다르다"고 적은 항목:

| 모듈 | 상태 |
|---|---|
| `rmf_adapter/bottleneck.py` | import 하는 곳이 테스트뿐 |
| `rmf_adapter/traffic_reservation.py` | import 하는 곳이 테스트뿐 |
| `rmf_adapter/ros_task_client.py` 의 `RosTaskSummaryObserver` | 클래스는 import 되나 `attach()` 호출 0곳 |

| **D9** | **`earliest_start_time` 이 벽시계라 RMF 시계와 어긋난다.** Gateway 는 `integration_messages.created_at`(벽시계)을 시작 시각으로 준다. 시뮬 fleet adapter 는 `use_sim_time` 이라 기동 후 몇백 초짜리 시계를 본다. 차이가 **약 56년**이라 RMF 는 그 작업을 "먼 미래에 시작 가능" 으로 읽는다. 입찰·낙찰은 정상이고 로봇만 IDLE 로 남는다 | sim clock `403,067 ms` 대 우리가 보낸 `1,787,065,234,974 ms`. `fleet_states` 에서 `PK_01 task_id='' mode=0` |
| **D10** | **시뮬 launch 에 `fleet_node` 가 없다.** `ExecuteTransport` action **서버**를 그 노드가 연다. `fleet_gateway` 는 같은 action 의 **클라이언트**라 서버가 아니다. 실기 launch 에는 처음부터 있었다 | `[PK_01] Pinky ExecuteTransport action server가 없습니다.` 반복. 온보드 노드 6개 중 `fleet_node` 없음 |
| **D11** | **명령 등록이 실행 가능 여부보다 먼저다 — 실패하면 원장에 행이 무한히 쌓인다.** `_navigate` 가 `claim_command`(행 1개 생성)를 부른 **뒤에** action server 존재를 확인한다. 서버가 없어 실패해도 행은 남고, RMF 재시도마다 `execution.identifier` 가 새로 와 멱등키가 달라져 계속 쌓인다 | step 59 하나에 `pinky/execution_command` **463행**. `executor error: step 59: HTTP Error 409` 가 초당 수십 회 |

### D9 — 두 시계는 만나지 않는다

`request_time_ms`(원장의 벽시계, 감사용)와 `earliest_start_time`(RMF 와 같은 시계)은
서로 다른 것이다. 같은 값을 쓰면 시뮬에서 갈라진다.

**고친 방식**: 워커가 자기 ROS 시계로 시작 시각을 찍는다. 시뮬이면 시뮬 시계,
실기면 벽시계가 그대로 오므로 **양쪽이 저절로 맞는다.**

- `task_api.py` — `GoToPlaceRequest.earliest_start_time_ms` 분리. 없으면 기존대로
- `rmf_gateway_worker.py` — 시계 주입(`now_ms`)
- `rmf_gateway_worker_node.py` — `--use-sim-time` + ROS 시계 전달
- `p0_simulation_bringup.sh` — 시뮬 워커에 `--use-sim-time`

### D11 — 두 결함의 곱이다

| | 무엇 | 역할 | 상태 |
|---|---|---|---|
| D11-a | 멱등키가 `execution_id` 를 포함해 재시도마다 새 행 + `_navigate` 가 검증보다 먼저 기록 | **행을 무한히 만든다** | **고침** |
| D11-b | executor claim 이 `message_type` 을 안 거른다 | **그 행을 집어 409 루프를 돈다** | **고침 (2026-08-19)** — 그 전까지 InMemory 만 고쳐져 있었고 이 표는 "고침" 으로 적혀 있었다. 운영이 도는 MySQL 은 그대로였다 |

b 가 더 위험했다. a 는 행이 남을 뿐이지만 b 는 남의 행을 집어 CPU 를 태우고
`attempts` 를 올려 결국 `dead_letter` 로 민다. 그리고 b 는 `execution_command` 가
만들어지는 **정상 경로에서도** 일어나므로 완주가 되기 시작하면 오히려 더 자주 터진다.

**b 를 고친 방식** — RMF claim 은 처음부터 걸러 왔고 executor claim 만 빠져 있었다.

```sql
-- claim_rmf_dispatches (원래 정상)
WHERE im.direction='outbound' AND im.channel='rmf'
  AND im.message_type = 'dispatch_task_request'

-- claim_executor_dispatches (고친 뒤)
WHERE im.direction='outbound' AND im.channel IN (...)
  AND im.message_type IN ('execute_action','execute_fms_action')
```

MySQL·InMemory 양쪽에 같은 규칙을 넣었다. **InMemory double 도 함께 고쳤다** —
`claim_command` 가 만드는 `execution_command` 행을 double 이 갖고 있지 않아 이
결함이 단위 테스트로 재현되지 않았다. double 이 실제와 다르면 계약을 검증할 수 없다.

### D11-a — 멱등키가 "일" 이 아니라 "시도" 를 가리켰다 (고침)

**근본 원인.** 멱등 방어막은 원래부터 있었다. 키가 틀려서 한 번도 작동하지 않았다.

```python
# 전
external_reference = f"rmf:{rmf_task_id}:execution:{request['execution_id']}"
# 후
external_reference = f"rmf:{rmf_task_id}:robot:{robot_id}:rev:{assignment_revision}"
```

RMF 는 실패한 작업을 재시도할 때마다 **새 execution handle** 을 준다. 그 값이 키에
들어 있으면 키가 매번 달라지고, 기존 행 조회가 늘 비어 새 행을 만든다. 상한도
없어 원장이 무한히 커진다(실측 479 → 590 → 925).

같은 작업을 같은 로봇이 같은 배정으로 하는 한 그것은 **같은 명령**이다. 실행
핸들이 새로 발급됐다고 새 명령이 되는 것이 아니다.

`assignment_revision` 을 키에 넣는 것이 맞는 근거 — 이 값은 배정이 바뀔 때만
오른다(`repositories.py` 두 곳, 둘 다 `assigned_device_id` 를 새로 쓰는 자리).
스키마 주석도 "stale execution results 를 거절하는 배정 판" 이라고 적고 있다.
재시도에는 안 변하고 재배정에만 변하므로, 재배정된 작업은 새 명령이 된다 — 의도한
동작이다.

**충돌 판정도 좁혔다.** 키를 바꾸면 같은 키에 다른 `execution_id` 가 오는데, 전체
`request` 를 비교하면 그것을 충돌로 거절해 버린다.

| 필드 | 비교 | 왜 |
|---|---|---|
| `robot_id` | 한다 | 다른 로봇이 같은 작업을 주장하면 진짜 충돌 |
| `map_revision` | 한다 | 지도가 다르면 진짜 충돌 |
| `execution_id` | **안 한다** | 재시도마다 달라지는 것이 정상. payload 에 기록만 남긴다 |

**함께 고친 위생 문제.** `_navigate` 가 `claim`(부수효과) 뒤에 실행 가능 여부를
확인했다. 이제 확인이 먼저다 — 실행 못 할 명령은 흔적조차 남기지 않는다.

```python
if not self._transport.server_is_ready(): ...  return   # 먼저
position 검증 ...                                       # 먼저
context = self._command_claims.claim(...)               # 그 뒤에
```

**폭주는 이제 세 겹으로 막힌다.**

| 층 | 무엇 |
|---|---|
| 근본 | 멱등키가 일 기준 — 재시도 몇 번이든 행 1개, 실패 이유와 무관 |
| 위생 | 검증이 부수효과보다 앞 — 실행 못 할 명령은 안 적는다 |
| 격리 | executor claim 이 `message_type` 필터 (D11-b) — 남의 행을 안 집는다 |

순서만 뒤집는 것으로는 부족했다. 그러면 `robot is not idle` 은 막지만 다른 실패
경로에서 같은 폭주가 다시 난다.


```python
def _navigate(self, destination, execution):
    context = self._command_claims.claim(...)          # 원장에 행 1개 생성
    ...
    if not self._transport.server_is_ready():
        self._fail_command(command_id, "...서버가 없습니다.")
        return                                          # 실패. 그러나 행은 남는다
```

`pinky_adapter_node.py:_navigate` 다. D10 이 방아쇠였을 뿐, **어떤 이유로든
`_navigate` 가 실패하면 같은 폭주가 다시 난다.**

피해가 앞의 것들과 다르다. D8~D10 은 "아무 일도 안 일어남" 이지만 D11 은 **원장을
오염시키고 CPU 를 태운다.** 오늘 RTF 가 낮았던 원인의 일부일 수 있다.

**고칠 방향 후보** — 아직 결정하지 않았다.

1. 실행 가능 여부를 **먼저** 확인하고 그 뒤에 claim 한다 (순서 뒤집기)
2. 멱등키에서 `execution_id` 를 빼고 `rmf_task_id + robot_id + assignment_revision`
   으로 묶는다. 같은 작업의 재시도는 같은 행을 다시 쓴다
3. 실패 시 만든 행을 되돌린다 (보상 트랜잭션)

2번이 근본에 가깝다 — 같은 작업의 재시도는 **같은 명령**이지 새 명령이 아니다.
다만 `execution_id` 가 RMF 실행 신원이라 그것을 뺐을 때 추적성이 어떻게 되는지
확인이 필요하다.

**임시 대응**: 폭주가 보이면 그 job 을 취소한다. 취소가 열린 메시지를 한 번에
닫는다(실측 463개 정리).

| **D12** | **(고침) `job_runner` 와 `executor_worker` 가 Gateway 재시작을 못 견디고 죽었다.** HTTP 예외가 `run_once` 밖으로 전파되어 프로세스가 종료된다. `rmf_gateway_worker` 는 같은 상황에서 오류만 찍고 계속 돈다(커밋 `4d1f3c4f` 가 거기에만 내성을 넣었다) | `docker restart fms_gateway` 직후 `job_runner.py:141 list_jobs()` → `urlopen ... Connection reset by peer` 트레이스백 후 프로세스 0개. 주문이 `queued` 에서 멈춤 |

| **D13** | **Nav2 SUCCEEDED 와 "정차 완료" 사이를 기다리는 코드가 없어 로봇이 영구히 잠긴다.** Nav2 는 goal tolerance 안에 들어오면 SUCCEEDED 를 주고 속도 0 을 요구하지 않는다. `velocity_smoother` → `collision_monitor` 때문에 `cmd_vel` 이 0.2~0.5초 더 감쇠하는데, `fleet_node` 가 결과가 온 순간 **한 번만** 묻는다. `stationary=False` 면 workflow 가 `"waiting for stop"` 을 돌려주고 phase 가 `NAVIGATING` 에 갇혀 **이후 모든 명령이 `"robot is not idle"` 로 거절된다** | `[PK_01] robot is not idle` 이 초당 여러 번. `arrival.py:20` 과 `test_arrival_stop_settlement_contract.py` 가 이 함정을 이미 문서화해 두었다 |

| **D14** | **시뮬 launch 에 `safety_supervisor` 가 없어 Nav2 의 속도가 모터에 닿지 않는다.** launch 는 Nav2 를 `cmd_vel → cmd_vel_nav` 로 remap 하고, gz bridge 는 `cmd_vel` 을 Gazebo 로 넘긴다. 그 사이를 잇는 유일한 노드가 `safety_supervisor` 다(모터용 `cmd_vel` 을 단독 소유). 없으면 **경로는 계획되고 step 은 `running` 이 되는데 로봇이 영원히 움직이지 않는다** | `/pinky_01/cmd_vel` 수신 **0건**(0값조차 없음 = 발행자 없음), odom 이동 `0.0000 m`. RViz 에는 초록 Global Plan 이 그려진다 |

| **D15a** | **(고침) 시뮬 센서 주기가 안전 gate 의 신선도 판정보다 느려 gate 가 깜빡인다.** `sim_hardware` 가 1 Hz 로 발행하는데 `sensor_timeout_s` 기본이 0.5초다. RTF<1 이면 더 벌어진다. STOP 이 뜰 때마다 `safety_blocked` → `dispatchable=False` → adapter 가 로봇을 RMF 에서 빼고 → `Unable to replan assignments` | 55초에 상태 전이 **28회**. `safety state=0 clear 67회 / state=2 sensor_timeout 6회`. proximity 0.2 Hz, scan 1.9 Hz |
| **D15** | **순간적인 안전 정지가 `dispatchable` 을 떨어뜨려 로봇을 fleet 에서 빼낸다 (미수정, 근본)** | `status.py` 가 `safety_blocked` 를 `execution_ready` 에 넣고, `pinky_adapter_node` 가 그것으로 `unstable_decommission()` 을 부른다 |

| **D16** | **(고침) 취소한 job 을 `job_runner` 가 되살려 로봇이 영원히 묶인다.** `assign_job_resources` 가 job 의 **상태를 검사하지 않는다**. `cancel_job` 이 step·예약을 닫고 `jobs.state='cancelled'` 로 쓴 직후, 다음 주기의 러너가 같은 job 을 다시 집어 `assigned` 로 되돌린다. 그러면 **step 은 cancelled 인데 job 은 assigned** 인 상태가 남고, 러너는 매 주기 `job runner blocked: step ... is cancelled` 를 찍으며 자기가 되살린 job 에 스스로 막힌다 | job 15·16 이 그 상태로 남아 뒤의 주문이 `no free robot` 으로 줄줄이 밀렸다. 재취소하면 `state=='cancelled'` 조기 반환 경로를 타서 닫히는데, 그건 타이밍이 우연히 맞은 것이지 설계된 동작이 아니다 |

| **D17** | **(고침) `sim_teardown.sh` 가 `camera_streamer` 를 안 죽여 세대가 겹친다.** 패턴 목록에 `trihouse_pinky_vision`·`camera_streamer` 가 없어 세대마다 살아남는다. 실측 **3개** 동시 실행 | `verify_robot_status.py` 가 `publishers: status 2, scan 2` 를 보고 "이전 세대가 남았다 — 아래 값을 믿지 마라" 로 판정. **측정 도구가 오염된 채로 판단한 구간이 있었다** |
| **D18** | **bringup 셸을 닫으면 시뮬 전체가 SIGHUP 으로 죽는다 (미수정, 운용)** | 로그가 오류 없이 뚝 끊기고 `gz sim` 만 살아남는다. OOM 아님(가용 5.4G). 오늘 여러 회차를 이렇게 잃었다 |

| **D11-b** | **(고침) executor 가 어댑터 소유 행을 집어 주행 성공한 step 을 `failed` 로 닫는다.** MySQL 의 `claim_executor_dispatches` 가 **채널로만** 고른다. `pinky` 채널에는 executor 가 실행할 `execute_fms_action` 과, `claim_command` 가 남기는 로봇 명령 기록 `execution_command` 가 **함께 흐른다**. executor 가 후자를 집어 FMS 액션으로 실행하려다 409 를 맞는다 | job 18 step 20 은 Nav2 가 `Goal succeeded` 를 냈고 어댑터가 `도착·정지 확인 후 RMF 이동을 완료했습니다` 까지 찍었는데 step 은 `failed` 로 닫혔다. `executor error: step 115: HTTP Error 409` 가 60초마다 반복 |
| **D19** | **(설정으로 회피) job 없는 RMF 이동이 어댑터를 무한 루프에 빠뜨린다.** 로봇 프로토콜은 job 없는 이동을 원천 거부한다(`protocol.py:83`). 그런데 `finishing_request: "park"` 와 `responsive_wait: true` 가 RMF 로 하여금 주차·비켜서기 이동을 스스로 만들게 한다. 그 task 는 원장에 없으므로 claim 이 404 → `_fail_without_finish` → `replan()` → 같은 작업 재계획 | **초당 13건** (누적 2104건). 설정을 끈 뒤 같은 측정에서 **0건** |
| **D20** | **다른 세션이 같은 PC 에서 시뮬을 만지면 서로 죽인다 (운용).** `sim_teardown.sh` 는 `p0_simulation_bringup` 을 kill 패턴에 넣고 `pytest` 를 예외로 둔다. 다른 창이 teardown 을 돌리면 이 창의 bringup 만 죽고 그 창의 테스트는 산다 | bringup 기동 7초 뒤 `trap cleanup INT TERM EXIT` 가 발동. 살아남은 것은 `ros2 launch trihouse_pinky_vision ... config_file:=/tmp/pytest-of-syw/...` 하나뿐이었다 |

### 2026-08-19 — 로봇이 처음으로 주행했다

기록해 둘 가치가 있다. 그동안 `cmd_vel` 은 늘 0 이었고 odom 이동은 `0.0000 m`
였다. 이날 처음으로 다음이 로그에 남았다.

```text
[controller_server] Reached the goal!
[bt_navigator]      Goal succeeded
[fleet_adapter]     [PK_01] Pinky 도착·정지 확인 후 RMF 이동을 완료했습니다.
```

충전소에서 출발해 `frozen_storage_loading_dock_01` 에 도착했다. 마지막 줄은
D13 에서 넣은 정차 대기가 실제로 동작했다는 뜻이다.

**그런데 그 step 은 `failed` 로 닫혔다.** 주행과 원장이 어긋난 것이고, 그것이
D11-b 다. 주행이 되는지와 원장이 그것을 옳게 적는지는 별개의 문제다.

### D11-b — InMemory 만 초록이었다

이 결함의 수정은 **InMemory 쪽에만 들어가 있었다.** 주석까지 정확히 이 상황을
설명해 두었는데 MySQL 쪽 SQL 에는 같은 조건이 없었다. 운영은 MySQL 로 돈다.

```python
# InMemory — 있었다
or response["message_type"] not in ("execute_action", "execute_fms_action")
```

```sql
-- MySQL — 없었다. 채널로만 골랐다
WHERE im.direction = 'outbound' AND im.channel IN (...)
```

**저장소 결함은 반드시 MySQL 을 상대로 RED 를 봐야 한다.** InMemory 는 이중
장부(double)이지 운영 코드가 아니다. 이날 그것을 확인하려고 통합 테스트를
새로 만들었고, 고치기 전에 정확한 이유로 실패하는 것을 먼저 보았다.

```text
assert 'execution_command' not in {'execution_command'}
```

- 테스트: [test_executor_claim_repository.py](../../fms_gateway/tests/integration/test_executor_claim_repository.py)
- 테스트 DB 는 `compose.db_test.yaml` (tmpfs, 3307). 환경변수는
  `docs/validation/2026-08-16-p0-simulation.md` 2.1 절 그대로 쓴다
- 결과: Gateway 전체 **328 passed, 1 skipped**

### D19 — 원장 밖의 이동은 이 설계에 없다

로봇은 job 없는 이동을 거부하도록 **일부러** 만들어져 있다.

```python
# trihouse_pinky_fleet/protocol.py:83
raise ProtocolError('execute_transport requires an active task_context')
```

그러니 RMF 가 자기 판단으로 로봇을 움직이려 하면 반드시 막힌다. 그리고 막힌
뒤 `replan()` 을 부르면 RMF 는 **같은 작업을 다시 계획한다** — 조건이 하나도
바뀌지 않았으므로 그대로 무한 루프가 된다.

| 파일 | 줄 | 전 | 후 |
|---|---|---|---|
| `trihouse_rmf_bridge/config/pinky_fleet.yaml` | 35 | `finishing_request: "park"` | `finishing_request: "nothing"` |
| 〃 | 36 | `responsive_wait: true` | `responsive_wait: false` |

`install/` 쪽은 심볼릭 링크라 colcon 재빌드가 필요 없다.

**귀환은 원장 안의 step 70 `return_home` 이 이미 맡고 있다.** `finishing_request`
를 함께 켜면 같은 귀환을 원장 안과 밖에서 두 번 지시하는 셈이고, 밖의 것은
로봇이 거부한다. `responsive_wait` 는 여러 대가 서로 비켜설 때 쓰는 것이라
1 대만 띄우는 동안에는 얻는 것이 없다 — 2 대로 늘릴 때 다시 판단한다.

**근본은 남았다.** 어댑터가 **영구 실패에 `replan()` 을 거는 것** 자체가 결함이다.
재계획은 경로가 막힌 것처럼 **일시적** 실패에 맞는 대응이고, "이 작업은 원장에
없다" 처럼 다시 시도해도 같은 조건인 실패에는 조용히 거절해야 한다. 설정을
끄면 지금 증상은 사라지지만 다른 경로로 같은 일이 난다.

### D20 — 한 번에 한 창만

이날 bringup 이 기동 7초 만에 죽었고, RViz 는 빈 화면이었다. RViz 설정 문제가
아니라 **P0 층 전체가 없었다.**

```text
trap cleanup INT TERM EXIT          ← TERM 을 받고 정리했다
살아남은 것: ros2 launch trihouse_pinky_vision ... /tmp/pytest-of-syw/pytest-122/...
```

`sim_teardown.sh` 의 `EXCLUDE_PATTERNS` 에 `pytest` 가 있고 `PATTERNS` 에
`p0_simulation_bringup` 이 있다. 살아남은 것과 죽은 것이 이 규칙과 정확히
일치한다 — 다른 창이 teardown 을 돌린 것이다.

**규칙: 시뮬을 만지는 창은 하나로 유지한다.** 두 세션이 같은 `ROS_DOMAIN_ID=0`
에서 같은 프로세스 이름을 상대로 일하면 서로의 작업을 지운다. "세대 겹침" 으로
진단했던 구간 중 일부는 실제로 이것이었을 수 있다.

### 진단 요령 — 코드는 있는데 배선이 없다

이날까지 같은 패턴이 네 번 나왔다: D8(observer), D10(`fleet_node`),
D13(`may_report_arrival`), D14(`safety_supervisor`). 모두 실기 launch 에는
있고 시뮬 launch 에만 없었다.

**새 결함을 만나면 먼저 `trihouse_pinky.launch.py`(실기)와
`two_pinky_order_demo.launch.py`(시뮬)를 비교한다.**

여기에 두 가지를 더한다.

| 증상 | 먼저 볼 것 |
|---|---|
| 저장소 동작이 테스트와 다르다 | InMemory 와 MySQL 두 구현이 같은가. 한쪽만 고쳐진 적이 있다 |
| 시뮬이 이유 없이 죽는다 | 다른 창이 열려 있는가. `ps -eo args \| grep claude` |

### D18 — 터미널과 분리해서 띄운다

포그라운드로 묶으면 창을 닫는 순간 프로세스 그룹이 통째로 죽는다. `setsid` 로
새 세션에 띄우면 창과 무관하게 산다.

```bash
setsid nohup env \
  TRIHOUSE_MAP_REVISION="..." TRIHOUSE_ROBOTS=PK_01 \
  TRIHOUSE_NAV2_MAP="$PWD/control_ui/rmf_control_ui/data/rmf_maps/new_map_2.yaml" \
  ROS_DOMAIN_ID=0 \
  control_tower/bringup/p0_simulation_bringup.sh > /tmp/sim.log 2>&1 &
disown
```

진행은 `tail -f /tmp/sim.log` 로 보고(Ctrl+C 해도 시뮬은 산다), 내릴 때만
`scripts/sim_teardown.sh` 를 쓴다.

**근본 대책**은 bringup 이 스스로 세션을 분리하거나 systemd user unit 으로
가는 것이다. 지금은 운용으로 넘긴다.

### D16 — 오늘 job 이 계속 쌓인 이유

```text
t0  취소 요청        cancel_job 이 job 행을 FOR UPDATE 로 잠그고
                     step·예약·outbox 를 닫고 jobs.state='cancelled' 커밋
t1  job_runner 주기  그 job 을 후보로 집어 assign_job_resources 호출
                     → 상태를 안 보므로 배정을 진행하고 jobs.state='assigned' 로 되돌림
결과                 step=cancelled, job=assigned → 로봇을 쥔 채 영원히 멈춤
```

**고친 방식** — 행은 이미 `FOR UPDATE` 로 잠겨 있으므로 검사 한 줄이면 경쟁이
사라진다. 취소가 먼저 커밋했으면 러너는 잠금을 기다렸다가 종료 상태를 보고 물러난다.

```python
if job["state"] in {"cancelled", "completed", "failed"}:
    raise ResourceAssignmentConflict("JOB_ALREADY_TERMINAL")
```

MySQL·InMemory 양쪽에 같은 규칙을 넣었다. **원장에서 막는 것이 근본이다** — 러너가
아닌 다른 경로로도 같은 일이 날 수 있다.

### 관련: task event outbox 가 가득 차면 명령이 거절된다

`fleet_node` 는 outbox 가 한도에 닿으면 `ExecuteTransport` 를 거절한다
(`task event outbox capacity reached`). 관제와 끊긴 채 계속 일하지 말라는 올바른
안전장치이지만, 오늘처럼 시뮬을 여러 번 죽였다 살리면 ACK 못 받은 이벤트가 쌓여
로봇이 막힌다. 실측 **1002행 / 1.19 MB**.

큐는 런타임 상태이지 저장소 자산이 아니다. 막히면 지우고 다시 만든다.

```bash
scripts/sim_teardown.sh
rm -f .trihouse/p0/pinky_0*_task_events.sqlite3
```

**왜 쌓였는지는 D5·D12 와 같은 뿌리다** — Gateway 재시작을 견디는 설계가 아직
부족하다. 근본 대책은 별도 항목이다.

### D15a — 표층 두 겹은 고쳤다

| 층 | 무엇 | 조치 |
|---|---|---|
| 표층 | `sensor_timeout_s` 0.5초가 시뮬 센서 주기보다 짧다 | 시뮬 launch 에서 **2.0초**. 안전 임계(정지·감속 거리)는 실기와 같게 둔다 |
| 중간 | `sim_hardware` 가 1 Hz 로 발행한다 (실기 초음파는 10 Hz 이상) | `publish_period_s` 파라미터화, 기본 **0.1초**. 배터리는 실제 경과 시간으로 적분하므로 주기를 바꿔도 거동이 같다 |

### D15 — 근본은 아직 남았다

**안전 정지는 정상 운영 중에 늘 일어난다.** 사람이 지나가면 서고 장애물이 보이면
감속한다. 그때마다 로봇을 fleet 에서 빼내고 RMF 가 배정을 다시 짜야 한다면
시스템은 돌 수 없다.

```text
safety STOP (순간)  →  safety_blocked  →  execution_ready=False  →  dispatchable=False
                                          →  unstable_decommission()
                                          →  RMF "Unable to replan assignments"
```

`dispatchable` 은 **"이 로봇에게 새 작업을 줘도 되는가"** 이고 `safety_blocked` 는
**"지금 잠깐 못 움직인다"** 다. 서로 다른 질문인데 한 값에 섞여 있다.

| 조건 | `dispatchable=False` 가 맞는가 |
|---|---|
| 센서 없음 · AMCL 죽음 · 링크 끊김 | **맞다** — 지속적 사용 불가 |
| 배터리 부족 | **맞다** |
| **안전 정지(순간)** | **아니다** — 배정은 유지하고 실행만 잠시 멈춰야 한다 |

표층만 고치면 시뮬은 돌지만 **실기에서 사람이 지나갈 때 같은 일이 난다.** 근본
수정은 `status.py`·`status_node`·`pinky_adapter_node` 와 그 테스트에 걸치므로,
완주를 한 번 보고 기준선을 만든 뒤에 하는 것이 맞다 — 그러면 그 변경이 무엇을
깨뜨렸는지 즉시 보인다.

### D14 — 로그만 보면 정상으로 보인다

이 결함에는 실패 신호가 없다. step 은 `running`, outbox 는 `sent`, Nav2 는 경로를
계획하고 RViz 에 초록 선이 그려진다. **실제로 안 움직이는 것만 다르다.** 그래서
`cmd_vel` 을 직접 재보지 않으면 발견되지 않는다.

```text
Nav2 → cmd_vel_nav → [safety_supervisor 없음] → cmd_vel → gz bridge → Gazebo
                      ↑ 여기가 비어 있었다
```

**판정 방법**: 주행을 확인할 때는 로그가 아니라 `cmd_vel` 과 odom 이동거리를 본다.

```python
n.create_subscription(Twist, "/pinky_01/cmd_vel", cmds.append, 10)
n.create_subscription(Odometry, "/pinky_01/odom", odoms.append, 10)
# cmd_vel 이 0건이면 발행자가 없다는 뜻이다. 0값이 오는 것과 다르다.
```

시뮬에는 초음파가 없으므로 `require_ultrasonic: False` 로 띄운다. 켜 두면 센서
미달로 gate 가 계속 정지를 걸어 역시 못 움직인다.

### 시뮬 launch 에 아직 없는 것

| 노드 | 시뮬 | 실기 | 주행에 필요한가 |
|---|---|---|---|
| `safety_supervisor` | **추가함(D14)** | 있음 | **필수** |
| `fleet_node` | 추가함(D10) | 있음 | **필수** |
| `recovery_health` | 없음 | 있음 | 복귀 판정용. 완주에는 아직 불필요 |
| `battery_adapter`·`ultrasonic_adapter` | 없음 | 있음 | `sim_hardware` 가 대신한다 |
| LED·부저·OLED | 없음 | 있음 | GPIO 라 시뮬에 없어도 된다 |

**같은 패턴이 오늘 네 번 나왔다** — 코드는 있는데 시뮬 경로에 배선이 없는 것:
D8(observer), D10(`fleet_node`), D13(`may_report_arrival`), D14(`safety_supervisor`).
실기 launch 에는 처음부터 있던 것이 시뮬 launch 에만 빠져 있었다. **새 결함을 만나면
먼저 `trihouse_pinky.launch.py`(실기)와 `two_pinky_order_demo.launch.py`(시뮬)를
비교해 보라.**

### D13 — 해결 함수는 있었고 배선이 없었다

`arrival.may_report_arrival(stationary, waited_s, timeout_s)` 가 정확히 이 대기를
위해 존재했다. 그런데 `fleet_node` 는 같은 모듈에서 `within_tolerance` 만 import
하고 그 함수는 쓰지 않았다. **오늘 세 번째로 만난 같은 패턴이다** — D8(observer),
D10(fleet_node), D13(may_report_arrival).

**고친 방식.** `_execute` 는 `async def` 이고 Nav2 결과도 `await` 로 받는다. 그래서
`await` 로 양보하며 기다리면 그 사이 odom 콜백이 계속 돌아 `self.stationary` 가
갱신된다. `rclpy.spin` 이 단일 스레드라 블로킹 sleep 으로는 안 된다 — 그러면
`stationary` 가 영원히 갱신되지 않는다.

```python
await self._settle_before_arrival()          # 정차 또는 상한까지 대기
arrived = self.workflow.nav_result(succeeded=..., stationary=self.stationary)
```

상한은 파라미터 `arrival_stop_timeout_s`(기본 2.0초)다. 끝내 멈추지 않는 것은 실제
결함이므로 무한히 기다리지 않는다 — 그때는 goal 이 `ROBOT_NOT_STOPPED` 로 정직하게
실패하는 편이 action 이 영원히 매달려 있는 것보다 낫다.

### D12 — 고친 방식

`run_poll_loop` 에서 `run_once` 를 `try/except` 로 감싸 한 주기를 잃고 다음으로
넘긴다. `rmf_gateway_worker_node` 가 이미 그렇게 하고 있었고(커밋 `4d1f3c4f`),
나머지 둘에만 없었다. 셋의 계약을 한 테스트가 함께 고정한다
(`control_tower/tests/test_poll_loop_survives_gateway_restart.py`).

프로세스를 잃는 것보다 한 주기를 잃는 것이 낫다. 죽으면 주문이 `queued` 에서 멈추고
사람이 알아채기까지 시간이 걸린다.

### D5 와 D12 는 맞물려 있다

```text
D5 (연결 상태가 굳음)  →  Gateway 재시작으로 푼다  →  D12 (재시작을 못 견딤)
                                                    →  러너·실행기 사망  →  주문 정지
```

그래서 **D5 를 먼저 고치는 것이 맞다.** 고치면 재시작 자체가 필요 없어져 D12 가
터질 일도 줄어든다. D12 도 독립적으로 고쳐야 하지만(운영 중 Gateway 재배포는
언제든 일어난다) 급한 쪽은 D5 다.

### D5 를 지금 푸는 법 (근본 수정 아님)

연결을 한 번 끊었다 붙이면 edge 가 다시 생기고, 이미 구독 중인 `status_node` 가
그것을 받는다.

```bash
docker restart trihouse_p0-fms_gateway-1
sleep 12
curl -s http://127.0.0.1:8080/ready; echo
python3 scripts/verify_robot_status.py pinky_01 20   # errors=[] , dispatchable=true
```

**근본 수정 두 갈래** — 둘 다 이 문서 밖의 구현이다.

1. `state_pub` 을 `transient_local` QoS 로 바꾼다. 늦게 붙은 구독자도 마지막 상태를 받는다
2. `_heartbeat` 타이머(2초)에서 현재 링크 상태를 함께 재발행한다

1번이 의미상 맞다 — 연결 상태는 **최신 값이 계속 유효한 사실**이지 흘러가는 사건이
아니다. 다만 구독자 쪽 QoS 도 함께 맞춰야 한다.

### 진단 절차 — 상태 토픽이 실제로 오는지 본다

`ros2 topic echo` 는 부하에서 멈추므로 타입을 손에 들고 직접 구독한다.
`scratchpad` 에 아래 내용을 `probe_connstate.py` 로 저장하고 돌린다.

```python
import time, rclpy
from rclpy.node import Node
from trihouse_interfaces.msg import ConnectionState

rclpy.init(); n = Node("probe_connstate"); got = []
topic = "/pinky_01/trihouse/fms/state"
n.create_subscription(ConnectionState, topic, lambda m: got.append(m), 10)
end = time.monotonic() + 8
while rclpy.ok() and time.monotonic() < end:
    rclpy.spin_once(n, timeout_sec=0.2)
print("publishers:", n.count_publishers(topic), " received:", len(got))
if got:
    print("state:", got[-1].state, got[-1].detail)
n.destroy_node(); rclpy.shutdown()
```

`publishers=1` 인데 `received=0` 이면 D5 다. 소켓 자체는 `ss -tnp | grep 8788` 로
확인한다 — `ESTAB` 이 보이면 TCP 는 정상이고 문제는 토픽 쪽이다.

## 11. RViz 로 주행 보기

Gazebo world 는 `ground_plane` 뿐이라(벽·선반 없음) **창을 열어도 로봇만 보인다.**
볼 것은 RViz 에 있다.

```bash
source /opt/ros/jazzy/setup.bash && source install/setup.bash
export ROS_DOMAIN_ID=0
rviz2 --ros-args -p use_sim_time:=true \
  -r /tf:=/pinky_01/tf -r /tf_static:=/pinky_01/tf_static
```

| 설정 | 값 | 왜 |
|---|---|---|
| Global Options → Fixed Frame | `map` | `pinky_01/odom` 이면 지도가 안 보인다 |
| Add → By display type → TF | — | **로봇 위치를 가장 확실히 보여준다.** 이것 하나면 움직임은 보인다 |
| Add → By topic → `/pinky_01/map` | Map | 우리 지도(44×54 격자, 2.2m × 2.7m) |
| Add → By topic → `/pinky_01/scan` | LaserScan | LiDAR |
| Add → By topic → `/pinky_01/plan` | Path | 계획된 경로 |
| Views → Distance | `3` | 맵이 작아 기본값 10 에서는 점처럼 보인다 |

**Map 이 안 보이면** 그 Display 의 `Topic → Durability Policy` 를 `Transient Local`
로 바꾼다. `map_server` 가 지도를 latch 로 한 번만 보내므로 `Volatile` 이면 늦게
붙은 RViz 는 영영 못 받는다. D5 와 같은 종류다.

### 두 지도는 서로 다른 것이다

| | 무엇 | 어디서 보나 | 현재 |
|---|---|---|---|
| Gazebo world (`.trihouse/p0/world.sdf`) | 물리 세계. 벽·선반·바닥 | Gazebo 창 | **바닥만 있다** |
| Nav2 occupancy grid (`trihouse_map_01.pgm`) | 위치추정·경로계획용 격자 | RViz | 44×54px, 2.2m × 2.7m |

**occupancy grid 에는 벽이 있는데 Gazebo 세계에는 없다.** LiDAR 가 빈 공간만
스캔하므로 AMCL 이 맞출 특징이 없고, `frame_id=map` 이 통과해도 실제로 수렴한
위치추정은 아니다. 선반이 보이는 그림을 원하면 world 에 형상을 넣어야 하고
(`control_system/robo_pinky/src/robo_pinky_sim/worlds/warehouse_3temp.sdf` 가
39KB 로 있다) 그것은 **검증이 아니라 구현**이다. nav_graph 좌표와 정합이 먼저다.
