# trihouse_pinky_docking

> 상태: 구현 계획. 현재는 README만 존재한다.

## 1. 목적과 책임

Nav2가 도킹 전 위치에 도착한 뒤 ArUco 상대 pose를 이용해 마지막 정밀 정차를 수행한다.

## 2. 넣지 않을 기능

장거리 경로 계획, 마커 영상 검출, camera-to-base 변환, 모터용 `/cmd_vel` 직접 발행을 넣지 않는다.

## 3. 계획된 노드와 작업

- `dock_action_server`: goal lifecycle, timeout, 취소, 결과 관리
- freshness/신뢰도/marker ID 검증
- 선형·각 P 제어, tolerance와 최대 속도 제한
- 마커 소실 즉시 0 출력, 제한된 탐색/재시도, 마지막 open-loop 구간

## 4. 발행·구독 토픽

vision의 base-frame `MarkerObservation`을 구독하고 `/cmd_vel_dock`을 safety에 발행한다.

## 5. 제공·호출 서비스

없음.

## 6. 제공·호출 액션

`Dock`을 제공하며 fleet만 호출한다. action feedback은 상대 오차, 상태와 재시도 횟수를 포함할 계획이다.

## 7. 사용하는 공용 인터페이스

`MarkerObservation`, `Dock`.

## 8. pinky_pro 참조

Nav2 action 결과와 URDF base/camera frame을 참조한다. 제어 출력은 벤더 모터가 아니라 safety 입력에 연결한다.

## 9. 설정 파일 후보

marker ID/크기, 목표 offset, 선형·각 gain, 속도 상한, pose/capture timeout, tolerance, 최대 3회 재시도, 마커 최소 관측 거리와 open-loop 시간.

## 10. 구현 순서와 완료 조건

1. 기록된 marker pose로 controller 단위 테스트를 만든다.
2. 취소/timeout/소실 정지를 구현한다.
3. simulation에서 safety 경유 토픽을 검증한다.
4. 실물에서 저속으로 오차와 재시도를 조정한다.

완료 조건은 마커 소실 시 즉시 정지하고, 최대 재시도 후 명확한 `DOCK_FAILED`를 반환하며, 허용 오차 안에서 반복 정차하는 것이다.
