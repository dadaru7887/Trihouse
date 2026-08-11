# 관제·UI·로봇이 공유하는 현재 배터리 정책 스냅샷이다.
uint8 STATE_UNKNOWN=0
uint8 STATE_NORMAL=1
uint8 STATE_LOCAL_ONLY=2
uint8 STATE_RETURN_REQUIRED=3
uint8 STATE_CHARGE_WAIT=4
uint8 STATE_CHARGING=5
uint8 STATE_RECOVERY_CHECK=6

builtin_interfaces/Time stamp
string robot_id
# 검증된 관측값. 정책 판단의 입력이지 행동 명령이 아니다.
trihouse_interfaces/BatteryCondition condition
uint8 state
# 새 작업 배정 가능 여부. 작업 종류 제한은 state로 판별한다.
bool ready
# 프로그램 분기용 안정적인 코드와 UI·로그용 설명.
string reason_code
string detail
