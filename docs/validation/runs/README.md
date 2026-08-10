# 검증 실행 기록

각 실행은 `YYYY_MM_DD_HHMM_<scenario>.md` 형식으로 저장한다. 결과는
`static`, `simulation`, `hardware`, `blocked` 중 하나로 표시한다.

각 기록에는 다음 정보를 포함한다.

- Git commit SHA와 변경 상태
- 실행 호스트와 GPU
- ROS 배포판, `ROS_DOMAIN_ID`
- map 이름과 revision
- 실행 명령
- 기대 결과와 실제 관찰 결과
- 로그·스크린샷·영상 경로
- 실패 또는 차단 원인과 다음 조치

## 현재 실행 기록

- [2026-08-10 Pinky 시연 준비](2026_08_10_pinky_demo_validation.md): 정적 정책과
  headless Gazebo·Safety 부분 검증, 통합 launch 차단점
