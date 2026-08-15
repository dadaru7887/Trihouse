# How a Task Reaches RMF (작업이 RMF까지 가는 길)

앱에서 만든 연속 작업이 실제 로봇을 움직이기까지 무엇이 어디서 일어나는지.

---

## 1. 짧은 답

**넷이 나눠 합니다.** RMF 작업 자체는 RMF가 합니다 — Flutter도, Flutter가 만든
Python도 아닙니다.

```
Flutter               무엇을 할지 정한다     rmf_task_request.dart   231줄
  ↓  JSON
<맵>_task_bridge.py   나른다                 90줄 · 판단 안 함
  ↓  task_api_requests
RMF                   어떻게 갈지 정한다     경로 · 순서 · 교통 정리
  ↓  목적지 하나씩
<맵>_nav2_adapter.py  실행하고 되알린다      317줄
  ↓  NavigateToPose
Nav2                  운전한다
```

Flutter가 하는 일은 **번역**입니다. "충전1로 가라"를 RMF가 아는 `go_to_place`로
바꿉니다. 그 앞뒤로 경로를 고르고 다 왔는지 판정하는 것은 전부 RMF입니다.

---

## 2. 왜 Python이 끼는가

**Flutter에 ROS 바인딩이 없습니다.** rclpy도 rclcpp도 못 씁니다.

이 앱이 처음부터 써 온 방식과 같습니다.

| 하고 싶은 일 | 부르는 것 |
|---|---|
| MySQL 읽기 | `mysql` 클라이언트 |
| 로봇 위치 받기 | `ros2 topic echo` |
| 노드 살아 있나 | `ros2 node list` |
| **작업 넣기** | **`<맵>_task_bridge.py`** |

`ros2 topic pub` 한 줄이면 좋겠지만 안 됩니다.

* 요청과 답을 `request_id`로 맞춰야 합니다. 남의 요청에 대한 답도 같은 토픽으로
  옵니다.
* QoS가 `transient_local`이라 실은 뒤 잠깐 살아 있어야 합니다.

그래서 90줄짜리 심부름꾼을 하나 둡니다. **아무것도 판단하지 않습니다** — 받아서
싣고, 답을 찍고, 끝냅니다.

---

## 3. 새 작업은 자동입니다

작업 편집기에서 무엇을 만들든, **실행을 누르는 순간** 변환이 일어납니다.

```dart
_runMockTask(task)
  → _isRmfDriven(robot.id)     // 출처가 Gazebo·실물이면 RMF로
  → convertTaskSteps(...)       // 단계 → activity
  → buildRmfTaskRequest(...)    // JSON
  → RmfTaskBridge.submit(...)   // 보낸다
```

손으로 할 일이 없습니다. 새 Waypoint를 지도에 넣어도, 단계 순서를 바꿔도, 작업을
열 개 더 만들어도 그대로 나갑니다.

**작업 편집기와 저장 형식은 그대로 둡니다.** 변환은 내보낼 때만 지나가는 자리
입니다. 되돌리기 쉬우라고 그렇게 했습니다.

### Mock 로봇은 예전 그대로

| 출처 | 누가 모나 |
|---|---|
| 앱 Mock | 앱이 좌표를 밀고 앱이 단계를 센다 |
| Gazebo · 실물 | RMF가 경로를 정하고 어댑터가 알린다 |

RMF가 모는 로봇은 **앱 타이머가 아예 건드리지 않습니다.** 좌표도 안 밀고 단계도
안 셉니다. 둘 다 하면 로봇이 아직 가는 중인데 화면만 다음 단계로 넘어갑니다 —
그게 원래 증상이었습니다.

---

## 4. 다시 해 줘야 하는 것 둘

### ① 지도나 로봇을 바꾸면 배포

Python 파일은 맵마다 만들어집니다. 로봇을 추가하거나 플릿 이름을 바꾸면 다시
배포해야 스크립트가 따라옵니다.

nav graph는 이제 실행 스크립트가 스스로 다시 만듭니다 —
[MULTI_ROBOT_NAMESPACES.md](MULTI_ROBOT_NAMESPACES.md)의 *낡은 nav graph* 를
보세요.

### ② 새로운 *종류*의 단계를 만들면 코드 한 줄

지금 아는 것은 넷입니다.

| 앱 단계 | RMF activity |
|---|---|
| `navigate` | `go_to_place` (Waypoint 이름) |
| `returnHome` | `go_to_place` (로봇의 충전 자리) |
| `armLoad` | `perform_action` + 직전 이동 위치의 워크셀 요청 |
| `wait` | `wait_for` |

여기 없는 것이 오면 **조용히 버리지 않고** 이유를 남깁니다.

```
6번째 청소 — RMF 가 모르는 단계입니다
```

조용히 버리면 화면의 10단계와 실제로 도는 9단계가 어긋납니다.

새 종류를 추가하려면 `convertTaskSteps`에 한 줄. 그것이 `perform_action`이면
**플릿 설정 `actions:`에도 같은 이름**을 넣어야 합니다.

---

## 5. 정리 — 무엇이 자동인가

| | 자동인가 |
|---|:---:|
| 새 작업 만들어 실행 | ✅ |
| Waypoint · Lane 추가 | ✅ (배포 후) |
| 로봇 추가 · 플릿 이름 변경 | 배포 필요 |
| 새로운 종류의 단계 | 코드 한 줄 |

일상적으로는 변환을 의식할 일이 없습니다. `armLoad` 말고 다른 동작(문 열기,
저울 재기 같은 것)을 만들 때만 한 번씩 손이 갑니다.

---

## 6. 밟은 함정 셋

### `actions:`에 없는 동작은 작업 전체가 거절된다

단계 하나가 빠지는 것이 아닙니다. **작업이 통째로 안 들어갑니다.**

```json
{"errors": [{"code": 42,
  "detail": "Fleet not configured to perform this action"}],
 "success": false}
```

플릿 설정에 이렇게 있어야 합니다.

```yaml
actions: ["teleop", "armLoad"]
```

이 사유가 화면에 안 닿으면 또 "배차는 됐는데 로봇이 안 움직인다"로만 보입니다.
그래서 거절 사유는 팝업으로 그대로 보여 줍니다.

### 걸리는 시간을 두 군데에 적어야 한다

RMF는 `execute_action`에 **안쪽 `description`만** 넘겨 줍니다. 바깥
`unix_millis_action_duration_estimate`는 어댑터까지 닿지 않습니다.

실측 — 9.6초짜리 `armLoad`가 **1.0초** 만에 끝났습니다.

```python
description = {
    'unix_millis_action_duration_estimate': 9600,  # RMF 가 배차 계산에 쓴다
    'category': 'armLoad',
    'description': {'seconds': 9.6},               # 어댑터가 본다
}
```

### 도착 횟수와 단계 수가 다르다

RMF는 Lane 그래프를 따라 **중간 Waypoint를 스스로 끼워 넣습니다.** 도착할 때마다
단계를 넘기면 화면이 실제보다 앞서갑니다.

그래서 마지막 목적지 좌표가 **우리 단계의 목적지와 같을 때만** 넘깁니다
(오차 0.02m). 중간 Waypoint는 어느 단계와도 안 맞으니 그냥 지나갑니다.

---

## 7. 확인한 것

저장돼 있던 **연속 작업 1**(이동 9 · 적재 1)을 앱 코드가 만든 JSON 그대로
넣었습니다. 버린 단계 0개.

```
충전1 → 홈1 → 대기5 → 대기2 → 픽업1
  ◆ armLoad 9.6초
→ [대기4] → 대기3 → 대기4 → 드랍오프1 → [대기1] [대기5] [홈1] → 충전1
task_id: ''                                              ← 완료
```

대괄호는 **RMF가 스스로 끼워 넣은 경유지**입니다. 단계 10개에 도착 12번.

RMF가 순서를 지키는지는 따로 확인했습니다. `대기3 → 대기4`만 넣어 보니 그 순서
그대로였고, 중간에 낀 대기4는 경유지였습니다.

```
Publisher count: 0 → 6      (/pinky_01/cmd_vel)
```

---

## 8. `armLoad`와 OMX 워크셀 연결

### 이전 동작과 문제

이전 `armLoad`는 로봇팔 명령이 아니었다. Fleet adapter의 `execute_action()`이
설정된 시간만 기다린 뒤 `execution.finished()`를 호출하는 가상 동작이었다.
따라서 Pinky가 픽업3에 도착해도 다음 로그만 남고 OMX는 움직이지 않았다.

```text
[pinky_02] 도착했습니다.
[pinky_02] 동작 [armLoad] · 9.6초
[pinky_02] 동작 [armLoad] 끝.
```

`project1_workcell` 노드가 실행 중이어도 결과는 같았다. 워크셀 노드는
`/dispenser_requests`를 기다리지만 기존 `armLoad`는 이 토픽을 발행하지 않았기
때문이다. 당시 로그에도 `픽업3 요청 받음`, ACK, SUCCESS 또는 OMX 관절 궤적
전송 기록이 없었다.

### 현재 동작

이제 작업 변환기가 `armLoad` 바로 앞 이동 단계의 Waypoint를
`target_guid`로 넣는다.

```json
{
  "category": "armLoad",
  "description": {
    "target_guid": "픽업3",
    "seconds": 9.6
  }
}
```

Fleet adapter는 고유한 `request_guid`를 만든 뒤 다음 요청을 발행한다.

```text
/dispenser_requests
  request_guid: pinky_02-<UUID>
  target_guid: 픽업3
  transporter_type: pinky_02
```

전체 실행 흐름은 다음과 같다.

```text
Pinky가 픽업3 도착
  → armLoad execute_action
  → /dispenser_requests(target_guid=픽업3)
  → project1_workcell이 픽업3 담당 omx_03 선택
  → /omx_03/arm_controller/joint_trajectory
  → /dispenser_results(ACKNOWLEDGED)
  → OMX 동작 및 복귀
  → /dispenser_results(SUCCESS)
  → execution.finished()
  → RMF가 다음 단계 시작
```

고정 타이머가 끝났다는 이유만으로 `armLoad`를 완료하지 않는다. 같은
`request_guid`의 SUCCESS를 받아야만 Fleet adapter가 RMF에 완료를 알린다.
워크셀은 RMF의 재전송으로 같은 요청을 여러 번 받아도 팔을 중복 동작시키지
않는다.

### 픽업 위치와 OMX 대응

project1의 현재 대응은 다음과 같다.

| `target_guid` | 워크셀 | 관절 명령 토픽 |
|---|---|---|
| `픽업1` | `omx_01` | `/omx_01/arm_controller/joint_trajectory` |
| `픽업2` | `omx_02` | `/omx_02/arm_controller/joint_trajectory` |
| `픽업3` | `omx_03` | `/omx_03/arm_controller/joint_trajectory` |

이 대응은 생성된 `<맵>_workcell.py`의 `WORKCELLS`에 들어 있다. 맵에서 픽업
Waypoint나 설비 배치를 바꾸면 프로젝트를 다시 배포하여 생성물을 갱신한다.

### 작업 작성 조건

로봇팔 적재 단계 앞에는 반드시 픽업 위치 이동 단계가 있어야 한다.

```text
올바름: 픽업3 이동 → OMX-AI 픽업/적재 → 드랍오프 이동
잘못됨: OMX-AI 픽업/적재 → 픽업3 이동
```

앞선 이동 위치가 없으면 작업 변환기는 해당 단계를 보내지 않고
`먼저 픽업 위치로 이동해야 합니다`라는 사유를 남긴다. `armLoad` 앞의 마지막
이동 위치가 `target_guid`가 되므로 실제 워크셀이 맡은 픽업 Waypoint를 지정해야
한다.

### 재시작과 테스트

Python 스크립트를 수정해도 이미 실행 중인 프로세스에는 자동 반영되지 않는다.
다음 순서를 지킨다.

1. 실행 중인 프로젝트와 Flutter 앱을 종료한다.
2. 프로젝트를 다시 실행한다.
3. Flutter 앱을 다시 실행한다.
4. 기존 접수 작업을 재사용하지 않고 새 작업을 제출한다.

정상이면 로그에 다음 순서가 나타난다.

```text
[pinky_02] 동작 [armLoad] → 워크셀 [픽업3] 요청 (...)
[omx_03] 픽업3 요청 받음 (...)
[pinky_02] 워크셀 [픽업3]이 요청을 받았습니다.
[omx_03] 픽업3 끝.
[pinky_02] 워크셀 [픽업3] 동작 완료.
```

토픽과 노드는 다음과 같이 확인한다.

```bash
ros2 node list | rg project1_workcell
ros2 topic info --verbose /dispenser_requests
ros2 topic info --verbose /dispenser_results
ros2 topic info --verbose /omx_03/arm_controller/joint_trajectory
ros2 control list_controllers -c /omx_03/controller_manager
```

`project1_workcell`만 보인다고 연결이 확인된 것은 아니다. 최소한 다음 조건이
모두 충족되어야 한다.

- `/dispenser_requests`에 Fleet adapter publisher와 workcell subscriber가 있음
- `/dispenser_results`에 workcell publisher와 Fleet adapter subscriber가 있음
- `omx_03`의 `arm_controller`가 `active`
- 로그에 같은 `request_guid`의 요청, ACK, SUCCESS가 순서대로 나타남

요청 로그가 없으면 새 작업 JSON에 `target_guid`가 포함됐는지 확인한다. 요청은
있지만 `픽업3 요청 받음`이 없으면 워크셀 매핑과 QoS를 확인한다. ACK 이후 팔이
안 움직이면 `arm_controller` 상태와 관절 명령 토픽 연결을 확인한다. SUCCESS가
없으면 RMF 작업은 다음 단계로 넘어가지 않는 것이 정상이다.

**실물 로봇은 확인하지 못했다.** 현재 검증 범위는 생성 코드, ROS 메시지 구조,
Python 문법 검사와 관련 Flutter 단위 테스트다. Gazebo 또는 실물에서 위 로그
순서와 실제 관절 움직임을 마지막으로 확인해야 한다.

---

## 관련 문서

* [OMX_POLICY_AND_IMITATION_LEARNING.md](OMX_POLICY_AND_IMITATION_LEARNING.md) — 물품별 가상 policy와 실제 모방학습 연결
* [THREE_SOURCES.md](THREE_SOURCES.md) — Mock · Gazebo · 실물 세 출처
* [NAV2_PATH.md](NAV2_PATH.md) — Nav2를 붙이기까지
* [MULTI_ROBOT_NAMESPACES.md](MULTI_ROBOT_NAMESPACES.md) — 여러 대를 가르는 법과 함정
* [COORDINATE_FRAMES.md](COORDINATE_FRAMES.md) — 도면 좌표와 RMF 월드 좌표
