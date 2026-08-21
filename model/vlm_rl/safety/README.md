# Recovery safety boundary

The 5080 generates recovery candidates and sends approved commands through the FMS
contract. It does not publish `cmd_vel`. The Pinky-side Safety Supervisor may reject,
clip, stop, or cancel any recovery command before producing the final velocity command.

5080은 복구 후보를 만들고 운영자 승인 명령을 FMS 계약으로 전달하지만 `cmd_vel`을
직접 발행하지 않는다. Pinky의 Safety Supervisor가 최종 속도 명령 전에 복구 명령을
거부·제한·정지·취소할 수 있다.
