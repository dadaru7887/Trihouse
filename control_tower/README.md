# control_tower

Trihouse 중앙 관제 서버의 역할별 모듈 루트다. Pinky와는 TCP 8788 NDJSON으로,
운영 UI와는 REST/WebSocket으로 통신한다. 각 Pinky ROS Domain에 직접 업무 로직을
배포하지 않는다.

| 폴더 | 책임 |
|---|---|
| `gateway/` | robot session, heartbeat, ACK, NDJSON↔내부 event 변환 |
| `task_manager/` | 작업 단계·취소·인계·incident workflow |
| `fleet_manager/` | 배차·로봇 상태·배터리·충전소 정책 |
| `rmf_adapter/` | Open-RMF task/traffic 연동 |
| `database/` | migration과 repository |
| `monitoring/` | health, metrics, audit, alert, report |
| `ui/` | operations, RMF diagnostics, map authoring |
| `tests/` | gateway·workflow·다중 로봇 통합 시험 |
