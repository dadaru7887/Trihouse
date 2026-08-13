uint8 STATE_IDLE=0
uint8 STATE_ACTIVE=1
uint8 STATE_SUCCEEDED=2
uint8 STATE_CANCELED=3
uint8 STATE_FAILED=4

builtin_interfaces/Time stamp
string robot_id
trihouse_interfaces/TaskContext task_context
uint8 state
float32 progress
geometry_msgs/PoseStamped target_pose
geometry_msgs/PoseStamped current_pose
string detail
