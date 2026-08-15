# omx_03 · OMX-03

project1-ver2 프로젝트의 설치 로봇입니다.
rmf_control_ui 가 로봇 등록에서 만들었습니다.

| 항목 | 값 |
|---|---|
| 종류 | 설치 로봇 |
| 값의 출처 | Gazebo 시뮬레이션 |
| 모델 | omx_f |
| Gazebo 이름 | omx_03 |
| 토픽 네임스페이스 | `/omx_03` |
| 설비 자리 | 설비1 |

Gazebo가 물리를 돌리고 그 결과를 ROS 토픽으로 주고받습니다.

프로젝트 bringup 이 이 로봇을 Gazebo 에 올립니다.

## 파일

| 파일 | 용도 |
|---|---|
| `robot.yaml` | 이 로봇의 등록 정보 |
| `spawn.launch.xml` | 이 로봇만 Gazebo 에 올리는 launch |
| `bridge.yaml` | 이 로봇이 주고받는 토픽 |

프로젝트 bringup 이 `spawn.launch.xml` 을 include 합니다.
이 로봇만 따로 시험하려면 그 파일을 직접 돌리면 됩니다.

## 고치는 곳

여기 파일을 손으로 고치지 마세요. 다음 저장 때 덮어써집니다.
앱의 `로봇` 메뉴 → `로봇 등록`에서 고칩니다.

## 설치 로봇 참고

한자리에 고정되므로 fleet adapter 에 들어가지 않습니다.
배차 대상이 아니라 Open-RMF 에서는 workcell 로 다룹니다.

올리는 컨트롤러:

- `joint_state_broadcaster`
- `arm_controller`
- `gripper_controller`
