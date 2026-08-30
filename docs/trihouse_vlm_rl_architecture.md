# Trihouse VLM + RL 아키텍처 코드 읽기 노트

> 목적: Trihouse의 VLM + RL 복구 흐름을 코드 근거로 이해하고, 이후 포트폴리오·LinkedIn·면접에서 **구현된 내용 / 검증된 내용 / 설계·계획**을 구분해 설명하기 위한 조사 노트다.
>
> 작성 규칙: 아래의 `[확인 필요]`를 코드로 확인한 뒤 채운다. 모든 사실에는 가능하면 `파일 경로:함수/클래스`를 남긴다. 실행하지 않은 내용은 `코드상 확인`, 실제 실행·측정한 내용은 `실행 검증`, 아이디어만 있는 내용은 `설계/계획`으로 표시한다.

---

## 0. 한 문장 요약

### 현재 이해

카메라·YOLO 기반 이벤트에서 VLM이 장면과 위험을 구조화해 해석하고, RL은 허용된 복구 후보를 제안한다. 실제 이동은 Nav2의 계획 검증과 Safety Supervisor의 승인 이후에만 이뤄진다.

### 코드 확인 후 내 언어로 다시 쓰기

> [확인 필요] "__________ 상황에서 __________ 정보를 바탕으로, VLM/RL이 __________ 복구 후보를 제안하고 Nav2/Safety가 __________을 검증하는 구조다."

---

## 1. 먼저 찾을 파일과 진입점

코드 검색은 아래 키워드부터 시작한다.

```bash
rg -n "Qwen|VLM|TGRPO|SAC|recovery|offline_buffer|reward|trigger|Safety|cmd_vel|Nav2" .
```

| 역할 | 실제 파일·모듈 | 진입 함수/클래스 | 상태 |
| --- | --- | --- | --- |
| 카메라·YOLO 입력 | [확인 필요] | [확인 필요] | 미확인 |
| 이벤트 트리거 | [확인 필요] | [확인 필요] | 미확인 |
| VLM 호출·프롬프트 | [확인 필요] | [확인 필요] | 미확인 |
| JSON 파싱·스키마 검증 | [확인 필요] | [확인 필요] | 미확인 |
| VLM → RL 상태 변환 | [확인 필요] | [확인 필요] | 미확인 |
| TGRPO 정책 / 복구 후보 | [확인 필요] | [확인 필요] | 미확인 |
| SAC 보정 또는 정책 | [확인 필요] | [확인 필요] | 미확인 |
| waypoint 생성·검증 | [확인 필요] | [확인 필요] | 미확인 |
| Nav2 action 호출 | [확인 필요] | [확인 필요] | 미확인 |
| Safety Filter / Supervisor | [확인 필요] | [확인 필요] | 미확인 |
| Recovery Memory / buffer | [확인 필요] | [확인 필요] | 미확인 |

---

## 2. End-to-End 흐름: 코드 근거로 채우기

```text
카메라 JPEG
  → YOLO perception
  → event trigger
  → VLM JSON
  → RL state / recovery skill proposal
  → candidate validation / waypoint generation
  → Nav2 planner check + Safety approval
  → recovery execution
  → post-observation, reward, offline buffer
```

| 단계 | 실제 입력 | 실제 출력 | 파일:함수/클래스 | 구현 상태 | 확인 메모 |
| --- | --- | --- | --- | --- | --- |
| 1. 이벤트 감지 | [확인 필요] | [확인 필요] | [확인 필요] | 미확인 | |
| 2. VLM 장면 해석 | [확인 필요] | [확인 필요] | [확인 필요] | 미확인 | |
| 3. 상태 벡터 구성 | [확인 필요] | [확인 필요] | [확인 필요] | 미확인 | |
| 4. 복구 후보 제안 | [확인 필요] | [확인 필요] | [확인 필요] | 미확인 | |
| 5. 공간·안전 검증 | [확인 필요] | [확인 필요] | [확인 필요] | 미확인 | |
| 6. 이동 실행 | [확인 필요] | [확인 필요] | [확인 필요] | 미확인 | |
| 7. 결과 기록·보상 | [확인 필요] | [확인 필요] | [확인 필요] | 미확인 | |

---

## 3. VLM: 무엇을 보고, 무엇을 말하는가

### 3-1. 호출 조건

- 트리거 조건: [확인 필요]
- 정상 Nav2 recovery 대신 VLM/RL을 호출하는 이유: [확인 필요]
- 반복·희귀·의미적 예외 중 해당 사례: [확인 필요]
- 코드 위치: [확인 필요]

### 3-2. 입력

| 입력 항목 | 실제 값 또는 자료형 | 생성 위치 | VLM에 필요한 이유 |
| --- | --- | --- | --- |
| 카메라 이미지 | [확인 필요] | [확인 필요] | |
| YOLO/Segmentation 결과 | [확인 필요] | [확인 필요] | |
| 로봇 pose / goal | [확인 필요] | [확인 필요] | |
| costmap·planner 상태 | [확인 필요] | [확인 필요] | |
| 이전 recovery 기록 | [확인 필요] | [확인 필요] | |

### 3-3. 출력 계약(JSON)

코드의 Pydantic/JSON schema 또는 prompt에서 실제 필드를 복사해 적는다.

| 필드 | 의미 | 후속 사용처 | 코드 근거 |
| --- | --- | --- | --- |
| `semantic_label` | [확인 필요] | [확인 필요] | [확인 필요] |
| `motion_state` | [확인 필요] | [확인 필요] | [확인 필요] |
| `path_relation` | [확인 필요] | [확인 필요] | [확인 필요] |
| `risk` | [확인 필요] | [확인 필요] | [확인 필요] |
| `confidence` | [확인 필요] | [확인 필요] | [확인 필요] |
| `evidence_quality` | [확인 필요] | [확인 필요] | [확인 필요] |
| `recovery_intent` | [확인 필요] | [확인 필요] | [확인 필요] |
| `uncertainty` | [확인 필요] | [확인 필요] | [확인 필요] |

### 3-4. 프롬프트와 실패 처리

- VLM이 자유로운 좌표·속도·`/cmd_vel`을 만들지 못하도록 한 제약: [확인 필요]
- JSON 파싱 실패 / timeout / 낮은 confidence 시 처리: [확인 필요]
- 사람이 승인해야 하는 단계가 있는지: [확인 필요]

---

## 4. RL: 무엇을 선택하고, 무엇을 선택하지 않는가

### 4-1. 상태(state)

현재 설계상 9D state 후보:

```text
[robot_x, robot_y, robot_yaw, goal_x, goal_y,
  obs_x, obs_y, obs_conf, uncertainty]
```

| state 항목 | 실제 코드상 출처 | 정규화·전처리 | 확인 |
| --- | --- | --- | --- |
| robot pose | [확인 필요] | [확인 필요] | 미확인 |
| goal pose | [확인 필요] | [확인 필요] | 미확인 |
| 최고 위험 object 위치 | [확인 필요] | [확인 필요] | 미확인 |
| object confidence | [확인 필요] | [확인 필요] | 미확인 |
| VLM uncertainty | [확인 필요] | [확인 필요] | 미확인 |

> 메모: 최고 위험 객체 하나만 쓰는지, 다중 객체 관계도 쓰는지 확인한다. 이는 모델 입력 차원과 표현 한계를 설명하는 핵심이다.

### 4-2. 행동(action)

- TGRPO가 실제로 선택하는 action / skill / candidate ID: [확인 필요]
- SAC가 실제로 보정하는 값: [확인 필요]
- `STOP`, `WAIT`, `REOBSERVE`, `REPLAN`, `BACKOUT` 등 allowlist: [확인 필요]
- 연속 좌표·속도 명령을 직접 출력하지 않는지: [확인 필요]

### 4-3. 보상(reward)

| 보상 항목 | 값 또는 식 | 의도 | 코드 근거 |
| --- | --- | --- | --- |
| 복구 성공 | [확인 필요] | | [확인 필요] |
| 충돌/안전 거부 | [확인 필요] | | [확인 필요] |
| 시간/지연 | [확인 필요] | | [확인 필요] |
| 재시도 횟수 | [확인 필요] | | [확인 필요] |
| 사람 개입 | [확인 필요] | | [확인 필요] |

### 4-4. 학습과 추론의 구분

- 실제로 학습을 실행한 알고리즘·스크립트: [확인 필요]
- 현재는 구조만 존재하거나 pseudo-code인 부분: [확인 필요]
- offline buffer에 기록만 하고 재학습은 아직 하지 않은 부분: [확인 필요]

---

## 5. 안전과 실행 권한

| 구성요소 | 담당 권한 | 하면 안 되는 것 | 코드·문서 근거 |
| --- | --- | --- | --- |
| VLM | 장면 해석, 위험·복구 의도 제안 | raw `/cmd_vel`, 자유 좌표 생성 | [확인 필요] |
| RL | allowlisted recovery 후보/skill 선택 | 안전 우회, 직접 주행 | [확인 필요] |
| waypoint generator | 후보를 유효 pose로 변환·검증 | 검증 없는 목표 전달 | [확인 필요] |
| Nav2 | local planning, costmap 확인, recovery 실행 | 최종 안전 판단 대체 | [확인 필요] |
| Safety Supervisor | 최종 stop/allow | VLM/RL로 권한 이관 | [확인 필요] |
| FMS / Open-RMF | global task·reservation·traffic | local robot control 직접 수행 | [확인 필요] |

### 즉시 중단 경로

- E-stop / 임박 충돌 / braking distance 위반 시: [확인 필요]
- VLM/RL을 거치지 않고 Safety가 정지하는 코드 경로: [확인 필요]

---

## 6. Recovery Memory / Offline Buffer

### 저장 단위

- event / transition / episode 중 실제 저장 단위: [확인 필요]
- 저장 위치(DB, JSONL, replay buffer 등): [확인 필요]
- 작성 함수: [확인 필요]

### 저장 필드

| 필드 | 저장되는가 | 용도 | 코드 근거 |
| --- | --- | --- | --- |
| trigger reason | [확인 필요] | | [확인 필요] |
| VLM 원문·파싱 JSON | [확인 필요] | | [확인 필요] |
| state | [확인 필요] | | [확인 필요] |
| candidate/action | [확인 필요] | | [확인 필요] |
| reward | [확인 필요] | | [확인 필요] |
| outcome / post-observation | [확인 필요] | | [확인 필요] |
| Safety/Nav2 rejection reason | [확인 필요] | | [확인 필요] |

### 재사용 범위

- 사후 분석: [확인 필요]
- offline RL / 정책 재학습: [확인 필요]
- 유사 예외의 retrieval: [확인 필요]
- 현재 구현 vs 향후 계획: [확인 필요]

---

## 7. 본인 기여 범위

여기는 “팀이 한 일”이 아니라 “내가 한 일”만 적는다.

| 유형 | 내 기여 | 관련 파일·커밋·문서 | 증거 수준 |
| --- | --- | --- | --- |
| 아키텍처 설계 | [확인 필요] | [확인 필요] | 설계/계획 |
| VLM prompt/schema | [확인 필요] | [확인 필요] | 구현/검증 |
| RL state/action/reward 설계 | [확인 필요] | [확인 필요] | 설계/계획 |
| Recovery Memory 설계 | [확인 필요] | [확인 필요] | 설계/계획 |
| 코드 작성·수정 | [확인 필요] | [확인 필요] | 구현 |
| 테스트·데모·측정 | [확인 필요] | [확인 필요] | 실행 검증 |

---

## 8. 검증 현황: 주장 가능한 범위

| 항목 | 확인된 증거 | 아직 말하면 안 되는 주장 |
| --- | --- | --- |
| VLM JSON 파싱 | [확인 필요] | 실제 로봇 자율 주행/복구 성공 |
| RL 정책 | [확인 필요] | 현장 최적화 또는 안전 보장 |
| Nav2 연동 | [확인 필요] | 모든 장애물·예외에 대응 |
| Safety 연동 | [확인 필요] | E-stop을 대체하거나 인증됨 |
| Recovery Memory | [확인 필요] | 장기적으로 성능 향상 검증 완료 |

---

## 9. 코드 이해 후 만들 문장 재료

아래 세 문장을 **확인한 증거 수준에 맞는 것만** 완성한다.

### 구현·검증된 경우

> I implemented __________, which translates __________ into __________ while __________ retains final execution authority.

### 아키텍처를 설계·기여한 경우

> I contributed to the architecture for __________, designing __________ so that __________ can be proposed without granting direct motion authority to the model.

### 계획 단계인 경우

> I explored a recovery-memory design for __________, intended to record __________ for later analysis and policy improvement.

---

## 10. 읽기 완료 체크

- [ ] 이벤트 트리거부터 post-observation까지 호출 순서를 파일·함수명과 함께 설명할 수 있다.
- [ ] VLM의 입력·출력 JSON·실패 처리를 설명할 수 있다.
- [ ] RL의 state, action, reward와 TGRPO/SAC의 역할을 구분할 수 있다.
- [ ] VLM/RL이 raw `/cmd_vel`을 내보내지 않는 이유와 Nav2/Safety의 권한을 설명할 수 있다.
- [ ] Recovery Memory의 실제 구현 범위와 계획 범위를 구분할 수 있다.
- [ ] 내 기여와 팀의 기여를 파일·커밋·문서 근거로 나눠 말할 수 있다.
- [ ] 실행 검증 결과와 설계 제안을 혼동하지 않는다.
