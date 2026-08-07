uint8 STATE_OFFLINE=0
uint8 STATE_CONNECTING=1
uint8 STATE_ONLINE=2
uint8 STATE_DEGRADED=3
uint8 STATE_RECOVERING=4

builtin_interfaces/Time stamp
string robot_id
string session_id
uint8 state
builtin_interfaces/Time last_heartbeat_ack_stamp
string detail
