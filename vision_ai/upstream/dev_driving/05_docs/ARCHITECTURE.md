# 전체 아키텍처 — VLM+RL+buffer 흐름

`EVOLUTION.md`가 파일별 변천사라면 이 문서는 "지금 데이터가 어떤 순서로 어디를 거쳐서
흐르는지"를 한눈에 보는 용도. 실선=실측 검증된 흐름, 점선=미구현/미연결.

```mermaid
flowchart TD
    CAM["카메라 프레임<br/>(robot_frame_server.py, 포트 8899)"] --> SEG["세그멘테이션<br/>(watch_seg_buffer_trajectory.py, YOLO aug_best.pt)"]
    LIDAR["LiDAR"] --> TRIG_DIST["거리_위험 트리거<br/>(danger zone 진입 즉시)"]
    SEG --> TRIG_OBJ["ObjectWatcher 트리거<br/>(신규출현/경로상물체/접근중)"]

    TRIG_OBJ --> COOLDOWN{"VLM_COOLDOWN_SEC<br/>지났나?"}
    TRIG_DIST --> COOLDOWN
    COOLDOWN -->|"예"| VLM["VLM 판단<br/>(vlm_contract_to_rl_state.py, Qwen2.5-VL 3B-4bit)"]
    COOLDOWN -->|"아니오"| SKIP["스킵 (트리거 무시)"]

    VLM --> STATE["RL state 벡터<br/>(9차원)"]
    STATE --> HIGH["HighLevelPolicy<br/>(TGRPO -- skill 5종 중 선택)"]
    HIGH --> LOW["LowLevelPolicy<br/>(SAC/CQL -- 좌표 dx,dy,dyaw 생성)"]
    LOW --> CANDS["K×M 후보 생성<br/>(rl_candidate_group.py)"]

    CANDS --> FILTER["안전필터 R0~R6<br/>(recovery_filters.py)"]
    FILTER -->|"R0-06 fail-closed"| VETO["사람 감독 대체<br/>(human_veto_query.py)"]
    FILTER --> SIXCL["6C-Lite 기하학적 체크<br/>(geometric_6c_lite.py, 2-멤버 앙상블)"]
    SIXCL -.->|"미구현"| WM["학습된 world-model<br/>(06_world_model/, 데모만 있음)"]

    SIXCL --> WINNER["survivor 중 목표 근접도 최고 = 우승 후보"]
    WINNER --> ENTER{"사람 Enter 확인<br/>(--execute 모드)"}
    ENTER -->|"승인"| NAV["Nav2 실행<br/>(nav_recovery_executor.py:<br/>BackUp/Spin/DriveOnHeading/NavigateToPose)"]
    ENTER -->|"거부/관찰만"| OBS_ONLY["is_execution=False로 기록<br/>(학습엔 안 씀)"]

    BATTERY["배터리 CRITICAL 감지<br/>(battery_watcher.py)"] -.->|"VLM/RL 완전히 우회"| NAV

    NAV --> POST["실행 후 재관측<br/>(프레임+VLM 재호출)"]
    POST --> REWARD["real reward 계산<br/>(real_reward.py: progress+clearance+time+intervention+rejoin)"]
    REWARD --> BUFFER[("real_recovery_buffer.pkl<br/>(recovery_data_collector.py)")]
    OBS_ONLY --> BUFFER

    BUFFER --> BUCKET["BucketedReplaySampler<br/>(SAFE/BOUNDARY/CRITICAL, 목표비율 50/30/20)"]
    BUCKET --> TRAIN["오프라인 학습<br/>(offline_train_from_buffer.py, 로봇 운행과 별개 프로세스)"]
    TRAIN --> CKPT[("checkpoint .pt")]
    CKPT -.->|"미구현 -- 로드 코드 없음"| HIGH

    style WM stroke-dasharray: 5,5
    style VETO fill:#fff3cd
    style BATTERY fill:#f8d7da
    style CKPT stroke-dasharray: 5,5
```

## 그림에서 놓치기 쉬운 것 3가지

1. **`checkpoint → HighLevelPolicy` 화살표가 점선인 이유**: 학습은 되는데, 학습된 checkpoint를
   로드해서 실제 관제(다음 트리거 때 이 정책을 쓰는 것)에 연결하는 코드가 없음
   (`recovery_system_node.py`가 TODO 상태 — `EVOLUTION.md` "다음 사람이 알아야 할 것" 참고).
   지금은 매번 학습만 하고 그 결과를 실제로 "써먹는" 배선이 빠져있는 상태.
2. **배터리 CRITICAL은 그림 왼쪽 전체를 건너뜀**: VLM도, RL도, 안전필터도 전혀 안 거치고
   곧바로 Nav2로 감(결정론적 규칙, `battery_watcher.py`) — 그림에 점선 화살표로 우회를
   표시해둔 이유.
3. **`OBS_ONLY`(사람이 관찰만 한 경우)도 buffer에 들어가긴 함**: 다만 `is_execution=False`
   태그가 붙어서 학습 시(`offline_train_from_buffer.py`) 필터링돼서 안 쓰임 — buffer에
   "있다"와 "학습에 쓰인다"는 다른 이야기.
