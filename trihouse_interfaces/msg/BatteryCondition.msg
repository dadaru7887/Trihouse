# Pinky가 BatteryState 원본을 검증해 만든 관측 스냅샷이다.
# 이 메시지는 정책이나 이동 명령을 포함하지 않는다.
builtin_interfaces/Time stamp
string robot_id

# UI와 정책에서 사용하는 배터리 잔량(0.0~100.0 %).
float32 percentage
# 배터리가 장착되어 있다고 보고되었는지 여부.
bool present
# sensor_msgs/msg/BatteryState의 POWER_SUPPLY_STATUS_* 원본 값.
uint8 power_supply_status

# 현재 sample의 percentage와 present가 유효한지 여부.
bool measurement_valid
# 노드 시작 후 유효한 sample을 한 번이라도 받았는지 여부.
bool has_valid_sample
# 마지막 유효 sample이 telemetry timeout 이내인지 여부.
bool telemetry_fresh
