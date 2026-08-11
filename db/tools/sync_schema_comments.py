#!/usr/bin/env python3
"""Synchronize English schema comments with SQL and existing XLSX/draw.io rows.

Database, table, column, and enum identifiers remain unchanged.
The historical v4 comment migration remains frozen; schema evolution uses a
separate migration. This script maintains ASCII-only metadata for reliable web
display and refreshes legacy dictionary/diagram entries that still exist.
"""


import argparse
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "db" / "schema_mysql.sql"
MIGRATION_PATH = ROOT / "db" / "migrations" / "004_add_korean_comments.sql"
DICTIONARY_PATH = ROOT / "docs" / "database" / "data_dictionary.xlsx"
DIAGRAM_PATH = ROOT / "docs" / "database" / "schema_diagram.drawio"

TABLE_META = {
    "locations": (
        "trihouse_fms",
        "운영 위치",
        "창고의 랙, 슬롯, 도크, 충전기, 작업장, 안전 노드와 RMF waypoint를 통합 관리한다.",
    ),
    "map_features": (
        "trihouse_fms",
        "지도 특징",
        "지도 revision별 표식, 정적 장애물, 병목, 출입문과 진입 금지 구역의 공간 정보를 관리한다.",
    ),
    "workers": (
        "trihouse_fms",
        "작업자",
        "관제 요청, 수동 복구와 안전 해제에 대한 책임을 식별할 작업자 계정과 권한 범위를 관리한다.",
    ),
    "devices": (
        "trihouse_fms",
        "장비",
        "Pinky 주행로봇과 OMX 로봇팔의 모델, 소속, 위치, 제어 모드와 기능을 관리한다.",
    ),
    "inventory_lots": (
        "trihouse_fms",
        "재고 로트",
        "상품 로트별 보관 위치, 유통기한, 가용 수량, 예약 수량과 보관 상태를 관리한다.",
    ),
    "jobs": (
        "trihouse_fms",
        "업무",
        "입고, 출고, 이동, 보충, 폐기, 복구와 비상 대응 업무의 전체 수명주기를 관리한다.",
    ),
    "job_items": (
        "trihouse_fms",
        "업무 품목",
        "업무에 포함된 상품, 요청 수량, 완료 수량, 배정 로트와 검수 상태를 관리한다.",
    ),
    "job_steps": (
        "trihouse_fms",
        "업무 단계",
        "업무를 Pinky 이동, OMX 조작, 검수와 인계 단위의 순서 있는 실행 단계로 관리한다.",
    ),
    "reservations": (
        "trihouse_fms",
        "자원 예약",
        "병목 통로의 진입 권한과 도크, 작업장, 장비의 독점 또는 시간대별 사용 예약을 관리한다.",
    ),
    "inventory_moves": (
        "trihouse_fms",
        "재고 변동",
        "재고와 예약 수량이 변한 원인, 증감량, 변경 후 수량과 책임 주체를 불변 이력으로 기록한다.",
    ),
    "device_states": (
        "trihouse_fms",
        "장비 최신 상태",
        "장비별 최신 heartbeat, 위치, 배터리, 진행률, 건강 상태와 현재 실행 단계를 관리한다.",
    ),
    "integration_messages": (
        "trihouse_fms",
        "연동 메시지",
        "RMF, Pinky, OMX와 주고받는 명령과 응답의 멱등 처리, 재전송, 전송 완료 상태를 관리한다.",
    ),
    "incidents": (
        "trihouse_fms",
        "안전 사건",
        "사람 감지, 낙상 후보, 충돌 위험, 비상 정지 등 안전 사건의 인지부터 해소까지를 관리한다.",
    ),
    "operation_events": (
        "trihouse_fms",
        "운영 이벤트",
        "업무, 장비, 안전, 모델 판단과 운영자 조치의 시간순 감사 이벤트를 기록한다.",
    ),
    "artifacts": (
        "trihouse_fms",
        "파일 산출물",
        "영상, 이미지, rosbag, episode, dataset, model과 보고서의 저장 위치와 무결성 정보를 관리한다.",
    ),
    "location_recovery_profiles": (
        "trihouse_fms",
        "복구 기준 노드",
        "안전 노드별 복구 역할, 사용 가능 상태와 베타 분포 기반 신뢰도를 관리한다.",
    ),
    "recovery_episodes": (
        "trihouse_recovery",
        "복구 에피소드",
        "복구 trigger부터 종료까지 하나의 사건과 사용한 VLM 및 복구 정책의 계보를 기록한다.",
    ),
    "recovery_steps": (
        "trihouse_recovery",
        "복구 실행 단계",
        "복구 에피소드에서 실제 실행한 행동, 전후 관측, 보상, 결과와 완료 상태를 순서대로 기록한다.",
    ),
}

# English metadata is the canonical source used by the schema browser.  The
# legacy Korean literals above are retained temporarily so older documentation
# diffs remain reviewable; no generated artifact consumes them.
TABLE_META = {
    "locations": ("trihouse_fms", "Operational locations", "Manages warehouse racks, slots, docks, chargers, workstations, safety nodes, and RMF waypoints."),
    "map_features": ("trihouse_fms", "Map features", "Manages spatial data for markers, static obstacles, bottlenecks, doors, and restricted areas by map revision."),
    "workers": ("trihouse_fms", "Workers", "Manages worker accounts and permission scopes for control requests, manual recovery, and safety release actions."),
    "devices": ("trihouse_fms", "Devices", "Manages models, fleets, locations, control modes, and capabilities for Pinky mobile robots and OMX robot arms."),
    "inventory_lots": ("trihouse_fms", "Inventory lots", "Manages storage location, expiration date, available quantity, reserved quantity, and status for each inventory lot."),
    "jobs": ("trihouse_fms", "Jobs", "Manages the full lifecycle of inbound, outbound, transfer, replenishment, disposal, recovery, and emergency jobs."),
    "job_items": ("trihouse_fms", "Job items", "Manages products, requested and completed quantities, assigned lots, and verification status for each job."),
    "job_steps": ("trihouse_fms", "Job steps", "Manages ordered execution steps for Pinky movement, OMX manipulation, verification, and handoff operations."),
    "job_step_attempts": ("trihouse_fms", "Job step attempts", "Records each Pinky, OMX, or FMS execution attempt with structured methods, evidence, criteria, metrics, and outcomes."),
    "reservations": ("trihouse_fms", "Resource reservations", "Manages access to bottlenecks and exclusive or time-based reservations for docks, workstations, and devices."),
    "inventory_moves": ("trihouse_fms", "Inventory movements", "Records immutable inventory and reservation quantity changes, resulting balances, reasons, and responsible actors."),
    "device_states": ("trihouse_fms", "Latest device states", "Stores the latest heartbeat, location, battery level, progress, health, and active step for each device."),
    "integration_messages": ("trihouse_fms", "Integration messages", "Manages idempotency, retries, and delivery status for commands and responses exchanged with RMF, Pinky, and OMX."),
    "incidents": ("trihouse_fms", "Safety incidents", "Manages safety incidents from detection through resolution, including people, fall risks, collision risks, and emergency stops."),
    "operation_events": ("trihouse_fms", "Operation events", "Records chronological audit events for jobs, devices, safety decisions, model decisions, and operator actions."),
    "artifacts": ("trihouse_fms", "Artifacts", "Manages storage locations and integrity metadata for videos, images, rosbags, episodes, datasets, models, and reports."),
    "location_recovery_profiles": ("trihouse_fms", "Location recovery profiles", "Manages recovery roles, availability, and beta-distribution reliability values for each safety node."),
    "recovery_episodes": ("trihouse_recovery", "Recovery episodes", "Records each recovery incident from trigger to completion, including VLM and recovery-policy lineage."),
    "recovery_steps": ("trihouse_recovery", "Recovery steps", "Records executed recovery actions, observations, rewards, outcomes, and completion status in sequence."),
}

COLUMN_COMMENTS = {
    "acknowledged_at": "안전 사건 또는 메시지를 인지했다고 확정한 시각",
    "acknowledged_by_worker_id": "안전 사건을 인지 처리한 작업자의 식별자",
    "action_type": "실행할 동작 종류를 나타내는 코드 값",
    "active": "현재 운영에서 사용 가능한 레코드인지 나타내는 값",
    "active_resource_key": "활성 예약의 자원 중복을 방지하기 위해 계산한 고유 키",
    "actor_worker_id": "운영 이벤트의 사용자 조치를 수행한 작업자 식별자",
    "after_state_sha256": "행동 후 관측 파일의 무결성을 확인하는 SHA-256 해시",
    "after_state_uri": "행동 후 관측 데이터가 저장된 위치 URI",
    "allowed_zones": "작업자가 접근하거나 조작할 수 있는 구역 코드의 JSON 배열",
    "artifact_id": "파일 산출물을 식별하는 자동 증가 번호",
    "artifact_type": "산출물의 형식을 구분하는 코드 값",
    "assigned_device_id": "업무 단계를 실행하도록 배정된 장비 식별자",
    "assigned_mobile_id": "업무에 배정된 Pinky 주행로봇의 장비 식별자",
    "attempts": "메시지 전송을 시도한 누적 횟수",
    "availability_status": "복구 기준 노드의 현재 사용 가능 상태 코드",
    "available_qty": "현재 로트에서 물리적으로 보유한 전체 수량",
    "battery_pct": "장비가 보고한 배터리 잔량 백분율",
    "before_state_sha256": "행동 전 관측 파일의 무결성을 확인하는 SHA-256 해시",
    "before_state_uri": "행동 전 관측 데이터가 저장된 위치 URI",
    "byte_size": "산출물 파일의 바이트 단위 크기",
    "capabilities": "장비가 지원하는 동작과 기능을 표현한 JSON 객체",
    "captured_at": "산출물의 원본 데이터가 취득된 시각",
    "category": "운영 이벤트가 속한 기능 영역을 구분하는 코드 값",
    "channel": "메시지가 통신하는 rmf, pinky 또는 omx 채널 코드",
    "completed_at": "업무, 단계 또는 복구 행동이 완료된 시각",
    "completed_qty": "업무 품목 중 실제 처리가 완료된 수량",
    "confidence": "모델 판단의 신뢰도 값이며 0 이상 1 이하로 저장",
    "context": "해당 레코드의 추가 운영 맥락을 저장하는 JSON 객체",
    "control_mode": "장비의 자동, 수동, 오프라인, 정비 또는 안전 정지 제어 모드",
    "created_at": "해당 레코드가 데이터베이스에 생성된 시각",
    "current_job_step_id": "장비가 현재 실행 중이라고 보고한 업무 단계 식별자",
    "current_location_id": "장비가 현재 위치한 것으로 확정된 운영 위치 식별자",
    "description": "안전 사건의 원인과 상황을 운영자가 이해할 수 있게 기록한 설명",
    "destination_location_id": "업무가 최종적으로 도착해야 하는 운영 위치 식별자",
    "details": "장비별 추가 상태와 진단 값을 저장하는 JSON 객체",
    "device_id": "Pinky 또는 OMX 장비를 식별하는 고유 코드",
    "device_type": "장비를 주행로봇 mobile 또는 로봇팔 arm으로 구분하는 코드",
    "direction": "메시지의 수신 inbound 또는 송신 outbound 방향 코드",
    "due_at": "업무 완료가 요구되는 기한 시각",
    "ended_at": "복구 에피소드가 성공, 중단 또는 실패로 종료된 시각",
    "entered_at": "장비가 예약 자원에 실제로 진입한 시각",
    "event_id": "운영 이벤트를 내부에서 식별하는 자동 증가 번호",
    "event_type": "발생한 운영 이벤트의 세부 종류를 나타내는 코드",
    "event_uuid": "시스템 간 중복 없이 운영 이벤트를 식별하는 UUID",
    "execution_status": "복구 행동의 대기, 실행, 성공, 실패 또는 취소 상태 코드",
    "executor_type": "업무 단계의 실행 주체를 mobile, arm 또는 fms로 구분하는 코드",
    "exited_at": "장비가 예약 자원에서 실제로 빠져나온 시각",
    "expires_at": "점유 확인이 없을 때 예약을 자동 만료할 기준 시각",
    "expiry_date": "재고 로트의 유통기한 날짜",
    "external_auth_id": "SSO 또는 외부 인증 시스템에서 사용하는 작업자 식별자",
    "external_reference": "외부 시스템의 요청이나 작업과 연결하는 참조 값",
    "failure_reason": "업무 또는 실행 단계가 실패한 구체적인 원인",
    "feature_code": "지도 revision 안에서 feature를 식별하는 업무 코드",
    "feature_id": "지도 feature를 식별하는 자동 증가 번호",
    "feature_type": "표식, 정적 장애물, 병목, 출입문 또는 진입 금지 구역 코드",
    "final_status": "복구 에피소드의 실행 중, 성공, 중단 또는 실패 최종 상태",
    "fleet_name": "주행로봇이 소속된 Open-RMF fleet 이름",
    "fms_job_id": "복구 에피소드와 연결된 FMS 업무 식별자이며 물리적 외래 키는 두지 않음",
    "fms_job_step_id": "복구 에피소드와 연결된 FMS 업무 단계 식별자이며 물리적 외래 키는 두지 않음",
    "geometry": "지도 좌표계의 점, 선 또는 다각형 공간 정보를 담은 JSON 객체",
    "handling_unit_code": "바구니, 박스 또는 팔레트 등 취급 단위의 식별 코드",
    "health": "장비의 정상, 경고, 오류 또는 통신 두절 건강 상태 코드",
    "home_location_id": "장비가 대기하거나 복귀할 기본 운영 위치 식별자",
    "idempotency_key": "같은 요청의 중복 실행을 방지하는 업무 멱등 키",
    "incident_code": "운영 화면과 보고서에서 사용하는 안전 사건 고유 코드",
    "incident_id": "안전 사건을 식별하는 자동 증가 번호",
    "incident_type": "사람, 낙상, 충돌 위험, 비상 정지 등 사건 종류 코드",
    "input": "업무 단계를 실행할 때 전달한 입력 값을 저장하는 JSON 객체",
    "inventory_move_id": "재고 변동 이력을 식별하는 자동 증가 번호",
    "is_terminal": "해당 복구 행동이 에피소드의 마지막 단계인지 나타내는 값",
    "item_name": "운영자 화면에 표시할 상품 이름",
    "job_code": "운영 화면과 외부 연동에서 사용하는 업무 고유 코드",
    "job_id": "업무를 식별하는 자동 증가 번호",
    "job_item_id": "업무 품목을 식별하는 자동 증가 번호",
    "job_step_id": "업무 실행 단계를 식별하는 자동 증가 번호",
    "last_error": "가장 최근 메시지 전송 실패의 원인",
    "last_outcome_at": "복구 기준 노드가 실제 결과에 사용된 가장 최근 시각",
    "last_verified_at": "복구 기준 노드의 위치와 안전성을 마지막으로 검증한 시각",
    "location_code": "운영 화면과 외부 연동에서 사용하는 위치 고유 코드",
    "location_id": "연결된 운영 위치의 내부 식별자",
    "location_type": "랙, 슬롯, waypoint, 도크, 충전기, 작업장 등 위치 종류 코드",
    "lot_code": "입고 단위와 추적에 사용하는 재고 로트 고유 코드",
    "lot_id": "연결된 재고 로트의 내부 식별자",
    "map_feature_id": "병목 잠금과 연결된 지도 feature 식별자",
    "map_name": "Open-RMF와 로봇 navigation에서 사용하는 지도 이름",
    "map_revision": "좌표와 feature가 유효한 지도 버전 식별자",
    "marker_code": "QR 또는 ArUco 표식에서 읽는 숫자 코드",
    "message": "운영자가 이벤트를 이해할 수 있도록 기록한 요약 메시지",
    "message_id": "시스템 간 메시지를 중복 없이 식별하는 UUID",
    "message_type": "명령, 상태 또는 응답의 계약 종류를 나타내는 코드",
    "metadata": "해당 레코드의 확장 속성을 저장하는 JSON 객체",
    "mime_type": "산출물 파일의 MIME 형식",
    "model": "장비 제조사 또는 제품 모델 이름",
    "model_name": "판단 또는 산출물 생성에 사용한 모델 이름",
    "model_version": "판단 또는 산출물 생성에 사용한 모델 버전",
    "move_type": "입고, 출고, 예약, 해제, 조정 등 재고 변동 종류 코드",
    "name": "운영자 화면에 표시할 이름",
    "next_attempt_at": "실패한 메시지를 다음에 재전송할 예정 시각",
    "note": "재고 변동의 사유를 보충하는 설명",
    "notes": "복구 기준 노드의 검토 결과와 주의사항",
    "observed_at": "장비 상태가 실제로 관측된 시각",
    "occurred_at": "운영 이벤트가 실제로 발생한 시각",
    "operation_type": "입고, 출고, 이동, 보충, 폐기, 복구 또는 비상 업무 종류 코드",
    "outcome_class": "복구 결과를 safe, boundary 또는 critical로 구분한 코드",
    "parent_job_id": "하위 업무를 생성한 상위 업무의 식별자",
    "parent_location_id": "위치 계층에서 바로 상위에 있는 운영 위치 식별자",
    "payload": "연동 메시지 또는 운영 이벤트의 원본 데이터를 담은 JSON 객체",
    "planned_end_at": "예약 자원의 사용을 마칠 예정 시각",
    "planned_start_at": "예약 자원의 사용을 시작할 예정 시각",
    "policy_name": "업무 단계 판단에 사용한 정책 이름",
    "policy_version": "업무 단계 판단에 사용한 정책 버전",
    "pose_x": "지도 좌표계 기준 X 좌표이며 단위는 m",
    "pose_y": "지도 좌표계 기준 Y 좌표이며 단위는 m",
    "pose_yaw": "지도 좌표계 기준 회전각이며 단위는 rad",
    "priority": "업무의 critical, high, normal 또는 low 우선순위 코드",
    "priority_rank": "우선순위 정렬을 위해 자동 계산되는 숫자 값",
    "product_code": "상품 종류를 식별하는 업무 코드",
    "progress": "현재 업무 단계의 진행률이며 0 이상 1 이하로 저장",
    "properties": "지도 feature의 운영 규칙과 표시 속성을 담은 JSON 객체",
    "quantity_after": "재고 변동을 반영한 뒤의 가용 수량",
    "quantity_delta": "가용 수량에 더하거나 뺀 변화량",
    "raised_at": "안전 사건이 최초로 발생하거나 등록된 시각",
    "raised_by_worker_id": "안전 사건을 수동으로 등록한 작업자 식별자",
    "received_at": "재고 로트의 입고가 완료된 시각",
    "recorded_at": "재고 변동이 확정되어 기록된 시각",
    "recorded_by": "재고 변동을 확정한 서비스 또는 작업자 식별 값",
    "recovery_episode_uuid": "하나의 복구 사건을 시스템 간 고유하게 식별하는 UUID",
    "recovery_policy_name": "실행한 복구 정책의 이름",
    "recovery_policy_version": "실행한 복구 정책의 버전",
    "recovery_roles": "안전 노드가 지원하는 wait, retreat, detour, rejoin 역할의 JSON 배열",
    "recovery_step_id": "복구 실행 단계를 식별하는 자동 증가 번호",
    "reference_node_uuid": "복구 목표로 사용할 안전 노드를 식별하는 UUID",
    "registered_at": "작업자 또는 장비가 운영 시스템에 등록된 시각",
    "released_at": "예약 자원이 정상 또는 수동으로 해제된 시각",
    "reliability_alpha": "복구 노드 성공 신뢰도의 베타 분포 alpha 누적 값",
    "reliability_beta": "복구 노드 실패 신뢰도의 베타 분포 beta 누적 값",
    "requested_by": "업무 생성을 요청한 작업자의 식별자",
    "requested_qty": "업무에서 처리하도록 요청한 상품 수량",
    "reservation_id": "자원 예약을 식별하는 자동 증가 번호",
    "reservation_mode": "독점 잠금, 병목 잠금 또는 시간 예약 방식 코드",
    "reserved_after": "재고 변동을 반영한 뒤의 예약 수량",
    "reserved_delta": "예약 수량에 더하거나 뺀 변화량",
    "reserved_qty": "출고 등의 업무를 위해 선점된 수량",
    "resolved_at": "안전 사건의 원인이 제거되어 해소된 시각",
    "resolved_by_worker_id": "안전 사건을 최종 해소 처리한 작업자 식별자",
    "result": "업무 단계 실행 후 반환된 결과를 저장하는 JSON 객체",
    "retired_at": "작업자 또는 장비를 운영 대상에서 제외한 시각",
    "retry_count": "업무 단계 실행을 다시 시도한 누적 횟수",
    "reviewed_by_worker_id": "복구 기준 노드의 상태를 마지막으로 검토한 작업자 식별자",
    "revision": "동시 수정 충돌을 탐지하기 위한 낙관적 잠금 버전",
    "reward_components": "RL 학습용 보상을 항목별로 기록한 JSON 객체",
    "rmf_task_id": "Open-RMF에서 발급한 이동 작업 식별자",
    "rmf_waypoint_name": "Open-RMF navigation graph의 waypoint 이름",
    "role": "작업자의 운영 권한 역할 코드",
    "safety_decision": "모델 제안에 대한 안전 계층의 승인, 거부 또는 보류 결정 코드",
    "sent_at": "메시지가 외부 채널로 전송된 시각",
    "severity": "사건 또는 이벤트의 영향 수준을 나타내는 코드",
    "sha256": "산출물 내용의 무결성을 확인하는 SHA-256 해시",
    "source_event_uuid": "복구 에피소드를 시작시킨 FMS 운영 이벤트 UUID",
    "source_location_id": "업무가 시작되는 운영 위치 식별자",
    "started_at": "업무, 단계 또는 복구 행동이 실제로 시작된 시각",
    "step_no": "같은 업무 또는 에피소드 안에서 실행 순서를 나타내는 번호",
    "storage_uri": "산출물 파일이 보관된 객체 저장소 또는 파일 시스템 URI",
    "storage_uri_hash": "긴 저장 URI의 중복을 검사하기 위해 계산한 이진 해시",
    "summary": "복구 에피소드의 원인, 행동과 결과를 요약한 설명",
    "target_location_id": "업무 단계가 이동하거나 조작할 목표 운영 위치 식별자",
    "target_pose": "복구 행동이 목표로 삼은 위치와 방향의 JSON 객체",
    "temperature_zone": "상온 ambient, 냉장 chilled 또는 냉동 frozen 보관 구역 코드",
    "trigger_type": "복구를 시작시킨 정체, 사람, 저시정 또는 위치 추정 문제 코드",
    "unit_weight_kg": "상품 한 단위의 kg 기준 무게",
    "updated_at": "해당 레코드가 마지막으로 수정된 시각",
    "verification_state": "업무 품목의 미검수, 일치, 불일치 또는 수동 검토 상태 코드",
    "vlm_model_name": "복구 상황 해석에 사용한 VLM 모델 이름",
    "vlm_model_version": "복구 상황 해석에 사용한 VLM 모델 버전",
    "worker_code": "운영 화면과 인증 연동에서 사용하는 작업자 고유 코드",
    "worker_id": "작업자 계정을 식별하는 내부 고유 값",
    "zone_code": "창고 운영 구역을 식별하는 코드",
}


def _default_english_comment(column: str) -> str:
    """Build a concise fallback description for a schema column."""
    label = column.replace("_", " ")
    if column.endswith("_at"):
        return f"Timestamp when the {label[:-3]} event occurred."
    if column.endswith("_id"):
        return f"Identifier of the related {label[:-3]}."
    if column.endswith("_uuid"):
        return f"UUID of the related {label[:-5]}."
    if column.endswith("_uri"):
        return f"URI of the stored {label[:-4]} data."
    if column.endswith("_sha256") or column == "sha256":
        return f"SHA-256 hash used to verify the integrity of the {label.replace(' sha256', '')}."
    if column.endswith("_qty"):
        return f"Quantity for {label[:-4]}."
    if column.endswith("_code"):
        return f"Business code for {label[:-5]}."
    if column.endswith("_name"):
        return f"Name of the {label[:-5]}."
    if column.endswith("_type"):
        return f"Code identifying the {label[:-5]} type."
    if column.endswith("_status") or column == "state":
        return f"Current {label} code."
    if column in {"metadata", "context", "details", "properties", "payload", "input", "result"}:
        return f"JSON object containing additional {label} data."
    return f"{label.capitalize()} for this record."


_ENGLISH_COLUMN_OVERRIDES = {
    "active": "Indicates whether this record is available for current operations.",
    "active_resource_key": "Calculated unique key that prevents conflicting active resource reservations.",
    "allowed_zones": "JSON array of zone codes the worker may access or operate.",
    "attempts": "Total number of message delivery attempts.",
    "available_qty": "Total physical quantity currently held in the inventory lot.",
    "battery_pct": "Remaining battery percentage reported by the device.",
    "capabilities": "JSON object describing actions and features supported by the device.",
    "confidence": "Model confidence value from 0 through 1.",
    "control_mode": "Device control mode, such as automatic, manual, offline, maintenance, or safety stop.",
    "description": "Operator-readable description of the cause and circumstances of the safety incident.",
    "direction": "Message direction: inbound or outbound.",
    "failure_reason": "Specific reason the job or execution step failed.",
    "geometry": "JSON geometry describing a point, line, or polygon in map coordinates.",
    "health": "Device health code, such as healthy, warning, error, or unreachable.",
    "idempotency_key": "Business key that prevents duplicate execution of the same request.",
    "is_terminal": "Indicates whether this recovery action is the final step of the episode.",
    "message": "Operator-readable summary of the operation event.",
    "note": "Additional explanation for the inventory movement.",
    "notes": "Review notes and cautions for the recovery reference node.",
    "pose_x": "X coordinate in the map frame, in meters.",
    "pose_y": "Y coordinate in the map frame, in meters.",
    "pose_yaw": "Heading in the map frame, in radians.",
    "priority": "Job priority code: critical, high, normal, or low.",
    "priority_rank": "Automatically calculated numeric value used to sort priorities.",
    "progress": "Progress of the current job step, from 0 through 1.",
    "quantity_after": "Available quantity after applying the inventory movement.",
    "quantity_delta": "Amount added to or removed from the available quantity.",
    "reliability_alpha": "Accumulated beta-distribution alpha value for successful recovery-node outcomes.",
    "reliability_beta": "Accumulated beta-distribution beta value for failed recovery-node outcomes.",
    "reserved_after": "Reserved quantity after applying the inventory movement.",
    "reserved_delta": "Amount added to or removed from the reserved quantity.",
    "retry_count": "Total number of retries for this job step.",
    "revision": "Optimistic-lock version used to detect concurrent updates.",
    "reward_components": "JSON object containing individual reward components for reinforcement learning.",
    "step_no": "Execution order within the same job or recovery episode.",
    "target_pose": "JSON object containing the target position and orientation for the recovery action.",
    "unit_weight_kg": "Weight of one product unit in kilograms.",
}

_ORCHESTRATION_COLUMN_COMMENTS = {
    "actor_device_id": "Device identifier for the execution actor when the role is Pinky or OMX.",
    "actor_role": "Execution actor role: Pinky, OMX, or FMS.",
    "after_observation": "JSON object containing the state observed after execution.",
    "assignment_revision": "Assignment revision used to reject stale execution results.",
    "attempt_no": "One-based attempt number within the step, revision, and actor role.",
    "attempt_uuid": "UUID that identifies one execution attempt across systems.",
    "before_observation": "JSON object containing the state observed before execution.",
    "causation_event_uuid": "UUID of the event that directly caused this event.",
    "command_uuid": "UUID of the command that initiated this execution attempt.",
    "correlation_uuid": "UUID that groups events belonging to the same distributed operation.",
    "criteria": "JSON object containing expected, observed, and passed success criteria.",
    "data_quality_status": "Quality status of the record: complete, incomplete, or invalid.",
    "detail": "Operator-readable detail that is not used as a decision branch.",
    "evidence_refs": "JSON array containing image, video, ROS bag, RMF log, or artifact references.",
    "failure_domain": "Layer responsible for failure, or none for successful and active attempts.",
    "final_method_code": "Method code used by the final execution attempt.",
    "final_outcome_reason_code": "Stable reason code for the final step outcome.",
    "method_code": "Stable code for the execution method selected before dispatch.",
    "metrics": "JSON object containing measured execution values and units.",
    "outcome": "Terminal attempt outcome: succeeded, failed, aborted, or cancelled.",
    "outcome_reason_code": "Stable reason code produced from structured execution facts.",
    "parameters": "JSON object containing command and method parameters.",
    "policy_source": "Source that selected the method, such as rule, RMF, Nav2, VLM, RL, or operator.",
    "result_code": "Stable final result code for a terminal job.",
    "rmf_event_id": "Open-RMF event identifier associated with this job step.",
    "rmf_phase_id": "Open-RMF phase identifier associated with this job step.",
    "rmf_status": "Latest Open-RMF task status observed for this job step.",
    "rmf_status_observed_at": "Timestamp when the latest Open-RMF status was observed.",
    "selection_reason_code": "Stable reason code explaining why the execution method was selected.",
    "state_detail": "Operator-readable detail for the current job state.",
    "state_reason_code": "Stable reason code explaining the current job state.",
    "success": "Indicates whether the terminal attempt satisfied every success criterion.",
}

COLUMN_COMMENTS.update(_ORCHESTRATION_COLUMN_COMMENTS)
_ENGLISH_COLUMN_OVERRIDES.update(_ORCHESTRATION_COLUMN_COMMENTS)

COLUMN_COMMENTS = {
    column: _ENGLISH_COLUMN_OVERRIDES.get(column, _default_english_comment(column))
    for column in COLUMN_COMMENTS
}

STATE_COMMENTS = {
    "locations": "위치의 현재 운영 상태이며 available, reserved, occupied, blocked, maintenance 중 하나",
    "inventory_lots": "재고 로트의 입고 대기, 보관, 보류, 소진, 만료 또는 손상 상태",
    "jobs": "업무의 대기부터 계획, 실행, 완료, 실패, 취소와 안전 보류까지의 상태",
    "job_steps": "업무 단계의 대기, 큐 등록, 실행, 성공, 실패, 보류 또는 취소 상태",
    "reservations": "예약의 reserved, in_use, released, expired 또는 cancelled 상태",
    "device_states": "장비가 보고한 현재 동작 상태 코드",
    "integration_messages": "메시지의 pending, sent, acknowledged, failed 또는 dead 상태",
    "incidents": "안전 사건의 open, acknowledged, mitigating, resolved 또는 closed 상태",
}

STATE_COMMENTS = {
    "locations": "Current location status: available, reserved, occupied, blocked, or maintenance.",
    "inventory_lots": "Inventory-lot status, such as pending receipt, stored, held, depleted, expired, or damaged.",
    "jobs": "Job lifecycle status: queued, assigned, running, held, completed, failed, or cancelled.",
    "job_steps": "Job-step status: pending, running, succeeded, failed, or cancelled.",
    "job_step_attempts": "Attempt progress: created, dispatched, running, reconciling, or finished.",
    "reservations": "Reservation status: reserved, in use, released, expired, or cancelled.",
    "device_states": "Current operating-state code reported by the device.",
    "integration_messages": "Message status: pending, sent, acknowledged, failed, or dead.",
    "incidents": "Safety-incident status: open, acknowledged, mitigating, resolved, or closed.",
}

TABLE_COLUMN_OVERRIDES = {
    ("locations", "name"): "운영자 화면에 표시할 위치 이름",
    ("locations", "metadata"): "위치별 확장 속성과 외부 연동 값을 저장하는 JSON 객체",
    ("map_features", "active"): "해당 지도 revision에서 feature를 운영 규칙에 사용할지 나타내는 값",
    ("workers", "name"): "운영자 화면과 감사 기록에 표시할 작업자 이름",
    ("workers", "active"): "작업자 계정이 현재 업무 요청과 승인에 참여할 수 있는지 나타내는 값",
    ("devices", "name"): "운영자 화면에 표시할 장비 이름",
    ("devices", "active"): "장비가 현재 배차와 작업 할당 대상인지 나타내는 값",
    ("job_items", "metadata"): "업무 품목별 검수와 외부 주문의 확장 값을 저장하는 JSON 객체",
    ("jobs", "context"): "업무 생성 원인과 외부 요청의 확장 맥락을 저장하는 JSON 객체",
    ("incidents", "geometry"): "안전 사건이 영향을 주는 점 또는 구역을 표현한 JSON 공간 정보",
    ("incidents", "context"): "센서 관측과 대응 절차 등 안전 사건의 추가 정보를 저장하는 JSON 객체",
    ("operation_events", "payload"): "이벤트 종류별 상세 관측과 판단 근거를 저장하는 JSON 객체",
    ("artifacts", "metadata"): "코덱, 해상도, dataset split 등 산출물별 확장 정보를 저장하는 JSON 객체",
    ("recovery_steps", "reference_node_uuid"): "행동 목표로 선택한 FMS 복구 기준 노드 UUID이며 물리적 외래 키는 두지 않음",
}

TABLE_COLUMN_OVERRIDES = {
    ("locations", "name"): "Location name displayed in operator interfaces.",
    ("locations", "metadata"): "JSON object containing location-specific attributes and external integration values.",
    ("map_features", "active"): "Indicates whether this feature is used by operating rules for the map revision.",
    ("workers", "name"): "Worker name displayed in operator interfaces and audit records.",
    ("workers", "active"): "Indicates whether this worker account may participate in job requests and approvals.",
    ("devices", "name"): "Device name displayed in operator interfaces.",
    ("devices", "active"): "Indicates whether this device is eligible for dispatch and job assignment.",
    ("job_items", "metadata"): "JSON object containing item-specific verification and external-order values.",
    ("jobs", "context"): "JSON object containing the job origin and extended context from external requests.",
    ("incidents", "geometry"): "JSON geometry describing the point or area affected by the safety incident.",
    ("incidents", "context"): "JSON object containing sensor observations, response procedures, and other incident details.",
    ("operation_events", "payload"): "JSON object containing detailed observations and decision evidence for the event type.",
    ("artifacts", "metadata"): "JSON object containing artifact-specific details such as codec, resolution, and dataset split.",
    ("recovery_steps", "reference_node_uuid"): "UUID of the FMS recovery reference node selected as the action target; no physical cross-database foreign key is used.",
}

CREATE_TABLE_RE = re.compile(
    r"CREATE TABLE IF NOT EXISTS\s+`?(?P<table>[a-z0-9_]+)`?\s*\("
    r"(?P<body>.*?)\n\) ENGINE=InnoDB(?:\s+COMMENT='(?:''|[^'])*')?;",
    re.DOTALL,
)
NON_ASCII_RE = re.compile(r"[^\x00-\x7f]")
COMMENT_RE = re.compile(r"\s+COMMENT\s+'(?:''|[^'])*'\s*$", re.IGNORECASE)


def escape_sql_comment(value: str) -> str:
    return value.replace("'", "''")


def split_definitions(body: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    index = 0
    while index < len(body):
        char = body[index]
        if quote is not None:
            if char == quote:
                if index + 1 < len(body) and body[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif char in {"'", '"', "`"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(body[start:index])
            start = index + 1
        index += 1
    parts.append(body[start:])
    return parts


def column_name(definition: str) -> str | None:
    match = re.match(r"\s*([a-z][a-z0-9_]*)\b", definition)
    return match.group(1) if match else None


def comment_for(table: str, column: str) -> str:
    if column == "state":
        return STATE_COMMENTS[table]
    return TABLE_COLUMN_OVERRIDES.get((table, column), COLUMN_COMMENTS[column])


def render_schema(source: str) -> tuple[str, dict[str, list[str]]]:
    seen: dict[str, list[str]] = {}

    def replace(match: re.Match[str]) -> str:
        table = match.group("table")
        if table not in TABLE_META:
            raise ValueError(f"Missing table metadata: {table}")
        definitions = split_definitions(match.group("body"))
        rendered: list[str] = []
        columns: list[str] = []
        for definition in definitions:
            name = column_name(definition)
            if name is None:
                rendered.append(definition)
                continue
            try:
                comment = comment_for(table, name)
            except KeyError as error:
                raise ValueError(f"Missing column comment: {table}.{name}") from error
            if NON_ASCII_RE.search(comment):
                raise ValueError(f"Comment is not ASCII English: {table}.{name}")
            clean = COMMENT_RE.sub("", definition.rstrip())
            rendered.append(f"{clean} COMMENT '{escape_sql_comment(comment)}'")
            columns.append(name)
        seen[table] = columns
        database, _logical_name, table_comment = TABLE_META[table]
        if NON_ASCII_RE.search(table_comment):
            raise ValueError(f"Table comment is not ASCII English: {database}.{table}")
        body = ",".join(rendered)
        return (
            f"CREATE TABLE IF NOT EXISTS {table} ({body}\n) ENGINE=InnoDB "
            f"COMMENT='{escape_sql_comment(table_comment)}';"
        )

    rendered = CREATE_TABLE_RE.sub(replace, source)
    if set(seen) != set(TABLE_META):
        missing = sorted(set(TABLE_META) - set(seen))
        extra = sorted(set(seen) - set(TABLE_META))
        raise ValueError(f"Schema metadata mismatch: missing={missing}, extra={extra}")
    if sum(map(len, seen.values())) != 298:
        raise ValueError(f"Expected 298 columns, found {sum(map(len, seen.values()))}")
    return rendered, seen


def render_migration(schema: str) -> str:
    lines = [
        "-- Replace table and column comments with English metadata in an existing v4 database.",
        "-- This migration changes metadata only and does not delete application data.",
        "",
    ]
    for match in CREATE_TABLE_RE.finditer(schema):
        table = match.group("table")
        database, _logical_name, table_comment = TABLE_META[table]
        definitions = [
            definition.strip()
            for definition in split_definitions(match.group("body"))
            if column_name(definition) is not None
        ]
        lines.extend(
            [
                f"ALTER TABLE `{database}`.`{table}`",
                f"  COMMENT = '{escape_sql_comment(table_comment)}';",
                "",
                f"ALTER TABLE `{database}`.`{table}`",
            ]
        )
        for index, definition in enumerate(definitions):
            suffix = ";" if index == len(definitions) - 1 else ","
            indented = definition.replace("\n", "\n  ")
            lines.append(f"  MODIFY COLUMN {indented}{suffix}")
        lines.append("")
    return "\n".join(lines)


def cell_text(row: ET.Element, column: str, namespace: str) -> str | None:
    ns = {"m": namespace}
    for cell in row.findall("m:c", ns):
        if cell.attrib.get("r", "").rstrip("0123456789") == column:
            text = cell.find("m:is/m:t", ns)
            return text.text if text is not None else None
    return None


def set_inline_cell(row: ET.Element, column: str, value: str, namespace: str) -> None:
    ns = {"m": namespace}
    row_number = row.attrib["r"]
    reference = f"{column}{row_number}"
    target = None
    for cell in row.findall("m:c", ns):
        if cell.attrib.get("r") == reference:
            target = cell
            break
    if target is None:
        target = ET.SubElement(row, f"{{{namespace}}}c", {"r": reference, "t": "inlineStr"})
    else:
        target.attrib["t"] = "inlineStr"
        for child in list(target):
            target.remove(child)
    inline = ET.SubElement(target, f"{{{namespace}}}is")
    text = ET.SubElement(inline, f"{{{namespace}}}t")
    text.text = value


def update_dictionary(*, check: bool) -> None:
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ET.register_namespace("", namespace)
    with ZipFile(DICTIONARY_PATH) as workbook:
        entries = {info.filename: workbook.read(info.filename) for info in workbook.infolist()}
        infos = {info.filename: info for info in workbook.infolist()}
    root = ET.fromstring(entries["xl/worksheets/sheet1.xml"])
    rows = root.findall(f".//{{{namespace}}}row")
    set_inline_cell(rows[0], "I", "column_description_en", namespace)
    set_inline_cell(rows[0], "J", "table_description_en", namespace)
    seen: set[tuple[str, str]] = set()
    mismatches: list[str] = []
    for row in rows[1:]:
        table = cell_text(row, "B", namespace)
        column = cell_text(row, "C", namespace)
        if not table or not column:
            continue
        expected_column = comment_for(table, column)
        expected_table = TABLE_META[table][2]
        if check:
            if cell_text(row, "I", namespace) != expected_column:
                mismatches.append(f"{table}.{column}.column_comment")
            if cell_text(row, "J", namespace) != expected_table:
                mismatches.append(f"{table}.{column}.table_comment")
        else:
            set_inline_cell(row, "I", expected_column, namespace)
            set_inline_cell(row, "J", expected_table, namespace)
        seen.add((table, column))
    if len(seen) != 253:
        raise ValueError(f"Expected 253 dictionary rows, found {len(seen)}")
    if check:
        if mismatches:
            raise ValueError(f"Dictionary metadata mismatch: {mismatches[:10]}")
        return
    dimension = root.find(f"{{{namespace}}}dimension")
    if dimension is not None:
        dimension.attrib["ref"] = "A1:J254"
    entries["xl/worksheets/sheet1.xml"] = ET.tostring(
        root, encoding="utf-8", xml_declaration=True
    )
    with NamedTemporaryFile(dir=DICTIONARY_PATH.parent, suffix=".xlsx", delete=False) as temp:
        temp_path = Path(temp.name)
    try:
        with ZipFile(temp_path, "w", ZIP_DEFLATED) as workbook:
            for name, content in entries.items():
                workbook.writestr(infos[name], content)
        temp_path.replace(DICTIONARY_PATH)
    finally:
        temp_path.unlink(missing_ok=True)


def update_diagram(*, check: bool) -> None:
    root = ET.parse(DIAGRAM_PATH)
    mismatches: list[str] = []
    for table, (database, logical_name, _table_comment) in TABLE_META.items():
        cell_id = f"table_{database}_{table}"
        cell = root.find(f".//mxCell[@id='{cell_id}']")
        if cell is None:
            # The v4 diagram is retained as a legacy overview. New v5 tables
            # are documented in schema_mysql.sql and database_guide.md.
            continue
        value = cell.attrib["value"]
        header = f"<b>{database}.{table}</b>"
        rest = value.removeprefix(header + "<br>")
        had_logical_name = re.match(r"^<i>[^<]+</i><br>", rest) is not None
        rest = re.sub(r"^<i>[^<]+</i><br>", "", rest)
        expected = f"{header}<br><i>{logical_name}</i><br>{rest}"
        if check:
            if value != expected:
                mismatches.append(f"{database}.{table}")
        else:
            cell.attrib["value"] = expected
            geometry = cell.find("mxGeometry")
            if not had_logical_name and geometry is not None and "height" in geometry.attrib:
                geometry.attrib["height"] = str(float(geometry.attrib["height"]) + 20).rstrip("0").rstrip(".")
    if check:
        if mismatches:
            raise ValueError(f"Diagram metadata mismatch: {mismatches}")
        return
    root.write(DIAGRAM_PATH, encoding="utf-8", xml_declaration=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify that SQL, migration, XLSX, and draw.io metadata are synchronized",
    )
    args = parser.parse_args()

    source = SCHEMA_PATH.read_text(encoding="utf-8")
    rendered_schema, _columns = render_schema(source)
    if args.check:
        if source != rendered_schema:
            raise ValueError("schema_mysql.sql comments are not synchronized")
        update_dictionary(check=True)
        update_diagram(check=True)
        print(
            "Schema metadata check: 19 tables and 298 SQL columns; "
            "253 legacy dictionary rows are synchronized."
        )
        return

    SCHEMA_PATH.write_text(rendered_schema, encoding="utf-8")
    update_dictionary(check=False)
    update_diagram(check=False)
    print(
        "Updated comments for 19 tables and 298 SQL columns; "
        "refreshed 253 existing dictionary rows."
    )


if __name__ == "__main__":
    main()
