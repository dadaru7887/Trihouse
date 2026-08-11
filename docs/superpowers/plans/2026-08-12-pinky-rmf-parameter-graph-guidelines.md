# 실제 Pinky RMF 파라미터·Graph 가이드라인 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** office demo 기준 가이드를 실제 Pinky 파라미터 측정과 Trihouse graph 연결에 바로 사용할 수 있는 실행형 가이드로 재구성한다.

**Architecture:** `parameters_for_rmf.md`는 측정·보정·설정 반영을, `waypoint.md`는 좌표 정합·graph 제작·경로 검증을 전담한다. `open_rmf_energy_bridge_test.md`는 office 검증을 유지하면서 실제 Pinky 전환의 선행 문서와 완료 조건을 연결한다.

**Tech Stack:** Markdown, pytest 정적 문서 계약 테스트, ROS 2 Jazzy, Open-RMF, Traffic Editor, Nav2 SLAM map

## Global Constraints

- office demo 값은 `초기 참고값`이며 실제 Pinky 설정으로 승인하지 않는다.
- 실측하지 않은 실제 Pinky 값은 숫자를 만들지 않고 `미측정`으로 기록한다.
- 실제 설정 반영에는 측정일·조건·원본 로그가 필요하고, POC 운영 반영에는 반복 검증 결과가 필요하다.
- `pinky_pro`, `control_system`, `/home/syw/rmf_ws`는 수정하지 않는다.
- `trihouse_rmf_bridge/config/office_bridge.yaml`은 office 검증용으로 유지한다.
- 실제 Pinky용 설정과 launch 생성은 이번 문서 작업 범위에 포함하지 않는다.

---

### Task 1: 실제 Pinky 파라미터 측정·보정 가이드 재구성

**Files:**
- Modify: `control_tower/tests/test_rmf_parameter_guideline.py`
- Modify: `docs/guideline/parameters_for_rmf.md`

**Interfaces:**
- Consumes: `trihouse_rmf_bridge/config/office_bridge.yaml`의 파라미터 이름, `EstimateTaskEnergy` 응답 필드, 기존 JSONL 로그 이름
- Produces: 상태·측정법·증거·적용 위치를 포함한 Pinky 파라미터 기록 계약

- [ ] **Step 1: 문서 계약 실패 테스트 추가**

```python
def test_guideline_separates_office_reference_from_measured_pinky_values():
    document = parameter_document()
    for required in (
        "미측정", "초기 참고값", "측정 완료", "검증 완료",
        "office_bridge.yaml", "실제 Pinky 설정 반영 금지",
        "원본 로그", "측정일", "적용 승인",
    ):
        assert required in document

def test_guideline_maps_every_bridge_parameter_to_a_measurement():
    document = parameter_document()
    for parameter in (
        "linear_velocity", "linear_acceleration", "angular_velocity",
        "angular_acceleration", "footprint_radius", "vicinity_radius",
        "nominal_voltage", "capacity", "charging_current", "mass",
        "moment_of_inertia", "friction_coefficient", "ambient_power",
    ):
        assert f"`{parameter}`" in document
```

- [ ] **Step 2: 새 테스트가 현재 문서에서 실패하는지 확인**

Run: `python3 -m pytest control_tower/tests/test_rmf_parameter_guideline.py -q`

Expected: FAIL. 네 상태 체계, 설정 반영 금지 문구, 전체 bridge 필드 매핑이 아직 없다.

- [ ] **Step 3: 파라미터 문서를 책임 순서대로 재작성**

문서 목차를 아래 순서로 고정한다.

```text
1. 목적과 적용 범위
2. 값 상태와 적용 금지 규칙
3. office 참고값 대 실제 Pinky 측정표
4. 반드시 측정할 POC 최소값
5. 항목별 측정 절차
6. 배터리·ETA 보정 실험
7. bridge 설정 필드 매핑
8. Open-RMF 제공값과 직접 측정값
9. 측정 결과 기록 양식
10. 적용 승인 체크리스트
11. 자동 측정 로그
```

각 bridge 필드 행에는 `office 초기 참고값`, `실제 Pinky 값=미측정`, `상태=미측정`, `측정 방법`, `원본 증거`, `적용 위치`를 둔다. `expected_loading_duration_s`, `expected_handover_duration_s`, `task_time_buffer_s`도 동일한 상태 계약으로 관리한다.

- [ ] **Step 4: 파라미터 문서 테스트 통과 확인**

Run: `python3 -m pytest control_tower/tests/test_rmf_parameter_guideline.py -q`

Expected: PASS. office/Pinky 값이 분리되고 모든 bridge 설정 필드가 측정 항목에 연결된다.

- [ ] **Step 5: 파라미터 가이드 커밋**

```bash
git add docs/guideline/parameters_for_rmf.md control_tower/tests/test_rmf_parameter_guideline.py
git commit -m "docs: guide Pinky RMF parameter measurement"
```

### Task 2: 실제 Pinky waypoint·graph 연결 가이드 재구성

**Files:**
- Modify: `control_tower/tests/test_rmf_parameter_guideline.py`
- Modify: `docs/guideline/waypoint.md`

**Interfaces:**
- Consumes: `final_map_08.yaml/.pgm`, waypoint 명명 계약, `/fleet_states`, bridge 오류 코드
- Produces: 좌표계 정합부터 graph export와 필수 경로 검증까지의 체크리스트

- [ ] **Step 1: graph 연결 문서 계약 실패 테스트 추가**

```python
def test_waypoint_guideline_covers_real_pinky_graph_connection():
    document = waypoint_document()
    for required in (
        "final_map_08.yaml", "final_map_08.pgm", "robosapiens.png",
        "기준점 4개", "level_name", "compute_plan_starts",
        "nav_graph_file", "fleet_name", "robot_name",
        "RMF_START_NOT_ON_GRAPH", "RMF_ROUTE_UNAVAILABLE",
        "FROZEN_PICKUP_01", "PACKING_HANDOVER_01", "CHARGE_01",
        "미측정", "원본 로그", "검증 완료",
    ):
        assert required in document
```

- [ ] **Step 2: 새 graph 계약 테스트의 실패 확인**

Run: `python3 -m pytest control_tower/tests/test_rmf_parameter_guideline.py -q`

Expected: FAIL. 현재 문서에는 실제 지도 자산, start 결합, bridge 교체 항목과 증거 상태가 모두 연결되어 있지 않다.

- [ ] **Step 3: waypoint 문서를 실제 연결 순서로 재작성**

문서 목차를 아래 순서로 고정한다.

```text
1. occupancy map과 RMF graph 역할
2. 현재 지도 자산과 사용 제한
3. level 이름·좌표계 정합
4. 필수 waypoint와 lane
5. waypoint pose 측정 기록표
6. Traffic Editor 등록·export
7. bridge 설정 교체 위치
8. /fleet_states pose와 graph start 결합
9. 필수 경로·오류 코드 검증
10. 단계별 완료 체크리스트
```

`robosapiens.png`는 UI 이미지이고 graph 좌표 근거가 아니라고 명시한다. waypoint 기록표에는 좌표·yaw·허용오차·반복 횟수·상태·원본 로그를 두며 실제 값은 모두 `미측정`으로 시작한다. 필수 lane은 냉동↔포장 양방향, 작업점→SAFE_WAIT, 작업점→충전소를 포함한다.

- [ ] **Step 4: waypoint 문서 계약 통과 확인**

Run: `python3 -m pytest control_tower/tests/test_rmf_parameter_guideline.py -q`

Expected: PASS. 실제 지도 자산부터 bridge graph start와 필수 경로까지 한 흐름으로 추적된다.

- [ ] **Step 5: waypoint 가이드 커밋**

```bash
git add docs/guideline/waypoint.md control_tower/tests/test_rmf_parameter_guideline.py
git commit -m "docs: guide Pinky RMF graph connection"
```

### Task 3: 문서 간 연결과 전체 검증

**Files:**
- Modify: `docs/guideline/open_rmf_energy_bridge_test.md`
- Modify: `control_tower/tests/test_rmf_parameter_guideline.py`

**Interfaces:**
- Consumes: Task 1의 측정 승인 체크리스트와 Task 2의 graph 완료 체크리스트
- Produces: office 검증과 실제 Pinky 전환을 혼동하지 않는 문서 탐색 경로

- [ ] **Step 1: 문서 간 링크 실패 테스트 추가**

```python
def test_office_test_guide_links_pinky_conversion_prerequisites():
    document = office_test_document()
    assert "parameters_for_rmf.md" in document
    assert "waypoint.md" in document
    assert "office demo 검증" in document
    assert "실제 Pinky 적용 완료가 아님" in document
```

- [ ] **Step 2: 링크 테스트 실패 확인**

Run: `python3 -m pytest control_tower/tests/test_rmf_parameter_guideline.py -q`

Expected: FAIL. office 테스트 문서가 실제 Pinky 전환의 두 선행 문서를 아직 명시적으로 연결하지 않는다.

- [ ] **Step 3: office 문서에 실제 Pinky 전환 경계 추가**

문서 앞부분에 아래 순서를 추가한다.

```text
office bridge 자동·수동 검증
→ parameters_for_rmf.md의 필수값 측정 완료
→ waypoint.md의 좌표 정합·필수 경로 검증 완료
→ 별도 Pinky config/launch 생성
→ 실제 Pinky 연결 시험
```

office 테스트 성공은 bridge 구조 검증이며 실제 Pinky 적용 완료가 아니라고 명시한다.

- [ ] **Step 4: 정적 문서 테스트와 Markdown 품질 확인**

Run: `python3 -m pytest control_tower/tests/test_rmf_parameter_guideline.py -q && rg -n "미측정|초기 참고값|측정 완료|검증 완료" docs/guideline/parameters_for_rmf.md docs/guideline/waypoint.md && git diff --check`

Expected: 모든 테스트 PASS, 두 문서에 네 상태가 존재하고 whitespace 오류가 없다.

- [ ] **Step 5: 금지 경로와 최종 diff 확인**

Run: `git diff --stat -- pinky_pro control_system && git status --short --untracked-files=all`

Expected: 이번 작업으로 `pinky_pro`, `control_system`에 새 변경이 없고 가이드·테스트 파일만 변경된다.

- [ ] **Step 6: 문서 연결 커밋**

```bash
git add docs/guideline/open_rmf_energy_bridge_test.md control_tower/tests/test_rmf_parameter_guideline.py
git commit -m "docs: connect Pinky RMF integration guides"
```
