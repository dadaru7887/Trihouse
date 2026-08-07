# trihouse_pinky_io

기존 Pinky Pro 센서·LED 인터페이스를 Trihouse 표준 계약에 연결한다.

- 입력: `/batt_state`, `/us_sensor/range`, `/trihouse/indicator/state`
- 출력: `/trihouse/battery`, `/trihouse/proximity/front`, 기존 `/set_led` service 호출
- 포함 예정: `battery_adapter.py`, `ultrasonic_adapter.py`, `led_indicator_client.py`, `indicator_state_selector.py`
- 제외: IR, Nav2 costmap 설정, FMS TCP 통신, 비상 래치
