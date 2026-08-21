# Physical readiness tests

첫 실물 구동 전 경계를 작은 단위부터 순서대로 확인한다. 번호가 앞선 테스트가
통과하지 않으면 뒤 단계, 특히 실제 모터가 움직일 수 있는 단계는 실행하지 않는다.

현재 자동화된 비파괴 검사:

```bash
pytest -q tests/physical_readiness/test_01_database_baseline.py
pytest -q tests/physical_readiness/test_02_device_identity.py
pytest -q tests/physical_readiness/test_06_pinky_pi_compose.py
```

전체 정적 준비 검사는 다음 명령으로 실행한다.

```bash
pytest -q tests/physical_readiness -m "not hardware"
```

`hardware` 표시는 실제 로봇, 센서 또는 호스트가 필요한 검사에만 사용한다. 이
폴더의 테스트를 import하거나 수집하는 것만으로 장비 명령을 보내지 않는다.

## 실행 순서와 파일 이름

| 순서 | 테스트 파일 | 확인 경계 | 현재 상태 |
|---:|---|---|---|
| 01 | `test_01_database_baseline.py` | 001 schema, migration archive, Compose mount | 구현됨 |
| 02 | `test_02_device_identity.py` | command ID, DB name, hardware seed, map publication | 구현됨 |
| 03 | `test_03_role_environment.py` | 공통 `.env`와 역할별 필수 변수 | 역할별 Compose 구현 시 추가 |
| 04 | `test_04_control_4060_compose.py` | 관제·QR·영상 수집 서비스 | 역할별 Compose 구현 시 추가 |
| 05 | `test_05_ai_5080_compose.py` | YOLO·VLM/RL·ACT 추론 서비스 | 역할별 Compose 구현 시 추가 |
| 06 | `test_06_pinky_pi_compose.py` | Pinky overlay와 Pi 배포 provenance | overlay 구현됨, Compose 검사는 추가 예정 |
| 07 | `test_07_omx_pc_compose.py` | OMX-AI PC adapter와 namespace | 역할별 Compose 구현 시 추가 |
| 08 | `test_08_ros_domain_namespace.py` | `ROS_DOMAIN_ID=12`와 장비 namespace | 역할별 Compose 구현 시 추가 |
| 09 | `test_09_camera_rtsp_pipeline.py` | 카메라→5080 단순 영상 경로 | 영상 계약 구현 시 추가 |
| 10 | `test_10_doctor_read_only.py` | 네트워크·장비·파일 비파괴 진단 | doctor 구현 시 추가 |
| 11 | `test_11_simulation_stack.py` | simulation bringup | simulation Compose 구현 시 추가 |
| 12 | `test_12_hardware_readiness.py` | 실물 bringup 직전 종합 검사 | 실제 장비 연결 단계에서 추가 |

아직 구현되지 않은 번호는 빈 테스트나 무조건 통과하는 테스트를 만들지 않는다.
해당 경계의 실행 코드와 함께 실패 테스트부터 추가한다.
