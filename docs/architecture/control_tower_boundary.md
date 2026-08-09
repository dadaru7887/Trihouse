# Control Tower 책임 경계

## 현재 시연

```text
control_system/   # 변경 없이 UI, RMF Dashboard, map, Gazebo/Open-RMF 실행
control_tower/    # Task Manager, API, projection, adapter/backend
```

기존 `control_system` 화면은 현재 구현을 시각화하는 기준선이다. 시연 전에는 원본을
이동·수정·submodule 재배치하지 않는다. `run_office_web.sh`는 stock office를 실행하므로
robosapiens map 통합 완료라고 표현하지 않는다.

## 장기 구조

```text
control_tower/
├─ backend/              # Task Manager, API, projection, adapter
└─ ui/
   ├─ operations/        # API 기반 운영 화면
   ├─ rmf_dashboard/     # Open-RMF 표시
   └─ map_authoring/     # map 작성 도구
```

`control_system/robo_control`에서는 theme, page, widget 같은 UI 계층만 선별 이식할
수 있다. 자체 FleetEngine, SQLite, TCP 8788 server는 Task Manager·MySQL·Pinky
adapter와 권한이 겹치므로 복제하지 않는다.

## 계약

- 입력: 인증된 운영자 intent, 장비 observation, vision result
- 출력: 승인된 command와 단일 operations projection
- 상태 전이: Task Manager만 확정
- DB transaction: FMS Gateway만 수행
- 긴급 정지: 로컬 Safety가 네트워크보다 우선
