# VLM/RL Recovery Memory

## 결정

Reference Memory는 `trihouse_fms.location_recovery_profiles`, Episodic Memory는
`trihouse_recovery.recovery_episodes`, `recovery_steps`,
`recovery_learning_transitions`에 저장한다. MySQL은 4060
한 곳에 두며 5080은 Gateway API/export만 사용한다.

## 데이터 흐름

```text
검증된 map/location ──> Reference Memory ──> 복구 후보 생성
실제 trigger/step/outcome ──> Episodic Memory ──> JSONL export ──> offline training
                                     ▲
5080 local queue ── message_id/ACK ── Gateway
```

Reference Memory는 map revision과 승인 상태를 포함하는 운영 기준이다. Episodic
Memory는 실제 실행한 episode와 step의 결과를 보존한다. 실행하지 않은 candidate
rollout과 GPU replay buffer는 MySQL 핵심 원장이 아니라 artifact/cache다.

학습 전이 한 행은 기존 모델이 요구하는 여섯 필드를 빠짐없이 복원한다.

```text
state[9], skill[0..4], coord[dx,dy,dyaw], reward,
next_state[9], done
```

`stop` 감사 step과 실행되지 않은 후보에는 학습 전이를 만들지 않는다. `done`은 SQL
처리 완료 여부가 아니라 해당 행동 뒤 정책 episode가 끝나는지를 뜻한다.

## 실시간 기록

복구 행동과 local safety는 DB 왕복을 기다리지 않는다. 5080은 record를 NVMe queue에
먼저 기록하고 Gateway ACK까지 같은 `message_id`로 재전송한다. Gateway는 idempotent
하게 step 완료, 학습 전이, ACK receipt를 한 트랜잭션으로 한 번만 반영한다. ACK가
유실되면 5080의 pending 파일이 남고 같은 요청을 재전송한다. 같은 message ID와 같은
payload는 저장된 ACK를 돌려주고, 다른 payload는 409로 격리한다.

## 학습과 실물 추론 경계

- 실물 5080: `model.vlm_rl.inference`만 실행한다.
- 오프라인 학습: Gateway의 `/internal/v1/recovery/training-export.jsonl`을 내려받아
  `compose.ai_training.yaml`의 명시적 `training` profile로 실행한다.
- 실물 운전 중 gradient update를 하지 않는다.
- 승인된 SHA-256 checkpoint만 추론에 올린다.
- 5080은 후보와 복구 요청을 만들 뿐 `cmd_vel`을 직접 발행하지 않는다. 운영자 승인
  뒤에도 Pinky Safety Supervisor가 최종 거부권을 가진다.

## 금지 연결

- RL/VLM이 전역 배차나 최종 안전 권한을 소유하지 않는다.
- 5080에 MySQL root/FMS 계정을 배포하지 않는다.
- 서로 다른 database 사이에 FK를 만들어 수명주기를 결합하지 않는다.
- replay buffer를 감사 원장으로 취급하지 않는다.
