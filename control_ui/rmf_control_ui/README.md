# RMF Control UI (RMF 관제 사용자 인터페이스)

창고 도면을 불러와 Open-RMF용 Floor, Wall, Lane, Waypoint를 작성하고 실제
프로젝트 맵 디렉터리로 배포하는 Flutter 관리 화면입니다.

상세 사용법과 배포 동작은 다음 문서를 참고하세요.

- [App-Only Mock Robot Guide (앱 전용 Mock 로봇 가이드)](docs/APP_MOCK_ROBOTS.md)
- [Coordinate Frames (좌표계)](docs/COORDINATE_FRAMES.md)
- [Food Order, Pinky, and OMX-AI Integration Design (식품 주문 · Pinky · OMX-AI 연동 설계)](docs/FOOD_ORDER_PINKY_OMX_WORKFLOW.md)
- [Hybrid Waypoint and Lane Automatic Route Planning Guide (Waypoint·Lane 혼합형 자동 경로 지정 가이드)](docs/HYBRID_ROUTE_AUTO_PLANNING.md)
- [Isaac Sim Virtual Environment Run Guide (Isaac Sim 가상환경 실행 가이드)](docs/ISAAC_SIM_RUN_GUIDE.md)
- [RMF Control UI Map Authoring and Deployment Guide (RMF Control UI 맵 작성 및 배포 가이드)](docs/MAP_AUTHORING_AND_DEPLOYMENT.md)
- [Pinky and OMX-AI Sequential Task Guide (Pinky · OMX-AI 연속 작업 가이드)](docs/MOCK_TASKS.md)
- [Multiple Robots in One World (한 월드에 로봇 여러 대)](docs/MULTI_ROBOT_NAMESPACES.md)
- [From Gazebo to a Physical Pinky — The Nav2 Path (Gazebo에서 실물 핑키까지 — Nav2 길)](docs/NAV2_PATH.md)
- [OMX Product-Specific Policies and Imitation Learning Data Operations (OMX 물품별 Policy와 모방학습 데이터 운영)](docs/OMX_POLICY_AND_IMITATION_LEARNING.md)
- [Physical Pinky First Startup and Manual Driving Procedure (실제 Pinky 최초 기동과 수동 주행 절차)](docs/PHYSICAL_PINKY_FIRST_RUN.md)
- [Pinky Virtual Robot and Fleet Adapter Integration (Pinky 가상 로봇 · Fleet Adapter 연동)](docs/PINKY_FLEET_INTEGRATION.md)
- [Roles of RMF Control Nodes (관제 노드별 하는 일)](docs/RMF_NODES.md)
- [Robot Registration and Directory Structure (로봇 등록과 디렉터리 구조)](docs/ROBOT_REGISTRATION.md)
- [ROS Control System Waypoint Architecture Mapping (ROS 관제 시스템 Waypoint 아키텍처 매핑)](docs/ROS_CONTROL_WAYPOINT_ARCHITECTURE.md)
- [Simulation Time and Real-Time Factor (시뮬레이션 시간 및 실시간 계수, RTF)](docs/SIMULATION_TIME.md)
- [How a Task Reaches RMF (작업이 RMF까지 가는 길)](docs/TASK_TO_RMF.md)
- [One Robot, Three Data Sources (로봇 하나, 값이 오는 곳 셋)](docs/THREE_SOURCES.md)
- [What to Put in a Task (작업에 무엇을 적어야 하나)](docs/WHAT_TO_PUT_IN_A_TASK.md)

## 실행

실제 Open-RMF 배포 기능은 Linux 데스크톱 앱에서 지원합니다.

```bash
cd /home/gyi/robosapiens/rmf_control_ui
flutter run -d linux
```

창고 맵은 **사람이 정한 프로젝트 이름으로 구분되는 단위**로 MySQL `robosapiens`
데이터베이스에 저장됩니다(`map_projects`, `map_project_waypoints`,
`map_project_lanes`). 프로젝트가 다르면 Waypoint·Lane·축척·도면이 전부 별개이며,
디스크 산출물도 `rmf_maps/<프로젝트이름>/` 으로 갈립니다.

**프로젝트 이름은 도면 파일 이름과 무관합니다.** `새 프로젝트`로 이름을 먼저
정하고 도면을 올리므로, 같은 `warehouse.png`로 `2층창고_v2`와 `2층창고_v3`처럼
서로 다른 프로젝트를 만들 수 있습니다. 도면은 올리는 즉시 열린 프로젝트에
저장됩니다(`map_projects.drawing_bytes`와 프로젝트 디렉터리에 한 장씩).

이름을 먼저 정하지 않고 도면부터 올리면 도면 파일 이름을 임시로 쓰고, `프로젝트
저장`에서 이름을 확정합니다. 그때 남의 프로젝트와 이름이 겹치면 덮어쓸지 다른
이름을 쓸지 먼저 확인합니다(열려 있는 내 프로젝트에 저장할 때는 묻지 않습니다).
자세한 내용은 [Map Authoring and Deployment Guide (맵 작성 및 배포 가이드)](docs/MAP_AUTHORING_AND_DEPLOYMENT.md)의
`맵 프로젝트 저장` 절을 참고하세요.

작업 목록과 작업 변경 이력(`rmf_ui_tasks`, `rmf_ui_task_history`)도 **맵
프로젝트에 속합니다.** 작업 단계가 그 맵의 Waypoint 좌표와 이름을 그대로 담기
때문에, 다른 맵에서 꺼내면 목적지가 아무 데도 가리키지 않습니다. 그래서 열린
프로젝트가 없으면 대시보드에 작업이 표시되지 않고 주문 자동 분류도 돌지
않습니다. 프로젝트를 지우면 그 맵의 작업도 함께 사라집니다.

주문·재고(`orders`, `lots`)는 창고 공통 원장이라 프로젝트로 나누지 않습니다. 접속값은
`ROBOSAPIENS_DB_HOST`(기본 `127.0.0.1`), `ROBOSAPIENS_DB_PORT`(기본 `3306`),
`ROBOSAPIENS_DB_USER`(기본 `root`), `ROBOSAPIENS_DB_NAME`(기본 `robosapiens`)으로
변경할 수 있습니다. 팀 개발용 기본 비밀번호는 `robosapiens`로 설정되어 있으며,
운영 환경에서는 `ROBOSAPIENS_DB_PASSWORD` 환경 변수를 지정하면 기본값보다 우선합니다.

웹 빌드에서는 맵 편집과 YAML 내보내기는 가능하지만 운영체제 프로세스를
실행할 수 없으므로 실제 배포는 지원하지 않습니다.

## 팝업

모든 팝업은 위쪽 손잡이를 끌어 옮길 수 있습니다. 팝업이 화면 가운데 고정되면
그 아래의 지도나 목록을 보면서 고칠 수 없기 때문입니다.

오류 팝업은 본문을 끌어 선택하거나 `복사`로 전문을 가져갈 수 있고, 오른쪽 아래
모서리를 끌어 크기를 바꿀 수 있습니다. 진단 문구에 좌표·거리·축척 같은 수치가
들어가 길어지기 때문입니다.

새 팝업은 `lib/movable_dialog.dart`의 `showMovableDialog`로 엽니다. `showDialog`와
인자가 같습니다.
