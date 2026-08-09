# Robosapiens 시스템 개요

## 상태와 소유자

- 상태: 목표 아키텍처와 시연 기준
- 업무 상태 소유자: Control Tower Task Manager
- 영속 원장 소유자: 4060 FMS Gateway/MySQL
- 이동 교통 소유자: Open-RMF
- 로봇 로컬 안전 소유자: 각 Safety Supervisor

## 전체 흐름

```text
운영자 / control_system UI
             │ API
             ▼
Control Tower Task Manager (4060)
├─ FMS Gateway ── MySQL trihouse_fms + trihouse_recovery
├─ RMF Adapter ── Pinky 이동·교통 예약
├─ Pinky Transport Adapter ── 상태·명령·heartbeat
├─ OMX Adapter ── pick/place/인계/정지
├─ Vision Adapter ── QR·YOLO·VLM 결과
├─ Safety Coordinator ── 승인·거부·비상·복구
└─ Operations Projection ── UI snapshot/event
             ▲
             │ inference/result + ACK
YOLO·VLM·RL (5080)
```

## 입력과 출력

- 입력: 운영자 업무, 재고/위치, 장비 상태, 영상 관측, 안전 사건
- 출력: 승인된 장비 명령, 업무 상태 전이, UI projection, 감사·복구 기록

## 금지 연결

- UI → MySQL 직접 쓰기
- UI → Pinky `/cmd_vel` 또는 OMX joint 직접 제어
- 5080 → MySQL 직접 연결
- VLM/RL → Safety Supervisor 우회
- adapter → 독립적인 업무 상태 확정
