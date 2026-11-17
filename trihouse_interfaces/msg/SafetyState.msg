uint8 STATE_CLEAR=0
uint8 STATE_SLOW=1
uint8 STATE_STOP=2
uint8 STATE_EMERGENCY=3

# 여유 거리 필드의 "관측되지 않음". 0.0 은 "닿았다" 이므로 섞으면 안 된다.
float32 CLEARANCE_UNOBSERVED=-1.0

builtin_interfaces/Time stamp
string robot_id
uint8 state
bool latched
string source
string detail

# 아래 세 값은 이 노드가 이미 계산해 판정에 쓰던 것을 그대로 내보내는 것이다.
# 같은 스캔을 두 번 해석하면 안전 판정과 학습 보상이 서로 다른 여유를 보게 된다.
#
# forward/reverse 는 진행 방향 보호 필드(직사각형) 안에서 **몸 끝**부터 잰 여유고,
# body 는 방향과 무관하게 **몸 경계**에서 잰 최단 거리다. 앞의 둘은 "이 방향으로
# 더 갈 수 있는가", 뒤의 하나는 "지금 이 자세가 충돌급인가" 에 답한다.
float32 forward_clearance_m
float32 reverse_clearance_m
float32 body_clearance_m
