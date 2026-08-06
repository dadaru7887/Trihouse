uint8 STATE_UNKNOWN=0
uint8 STATE_HEALTHY=1
uint8 STATE_DEGRADED=2
uint8 STATE_DISCONNECTED=3
uint8 STATE_RECOVERING=4

string camera_id
uint8 state
float32 fps
float32 bitrate_kbps
builtin_interfaces/Time last_frame_stamp
string detail
builtin_interfaces/Time stamp
