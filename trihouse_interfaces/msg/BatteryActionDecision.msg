# Control Tower가 내린 행동 결정이다. 실제 모터 이동 명령은 아니다.
uint8 ACTION_NONE=0
uint8 ACTION_ALLOW_GENERAL_JOB=1
uint8 ACTION_ALLOW_LOCAL_JOB=2
uint8 ACTION_WAIT_AT_SAFE_NODE=3
uint8 ACTION_COMPLETE_THEN_RETURN=4
uint8 ACTION_RETURN_TO_CHARGE=5
uint8 ACTION_HOLD_SAFE=6
uint8 ACTION_WAIT_FOR_CHARGE=7
uint8 ACTION_REQUIRE_OPERATOR=8

builtin_interfaces/Time stamp
# 재전송 시에도 유지하여 중복 실행을 막는 결정 식별자.
string decision_id
# 동일 로봇 결정의 단조 증가 순번.
uint64 sequence
# 이 결정이 유효한 기간(초). 0이면 별도 만료 없음.
float64 valid_for_s
string robot_id
string job_id
uint8 action
# 이동이 필요한 경우 등록된 RMF waypoint ID.
string target_waypoint
# RMF가 예측한 전체 작업 시간(초).
float64 estimated_duration_s
# RMF가 예측한 작업 종료 SOC(0.0~1.0).
float64 finish_state_of_charge
# 프로그램 분기용 안정적인 코드와 UI·로그용 설명.
string reason_code
string detail
