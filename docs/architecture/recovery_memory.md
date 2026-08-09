# VLM/RL Recovery Memory

## 결정

Reference Memory는 `trihouse_fms.location_recovery_profiles`, Episodic Memory는
`trihouse_recovery.recovery_episodes`와 `recovery_steps`에 저장한다. MySQL은 4060
한 곳에 두며 5080은 Gateway API/export만 사용한다.

## 데이터 흐름

```text
검증된 map/location ──> Reference Memory ──> 복구 후보 생성
실제 trigger/step/outcome ──> Episodic Memory ──> replay/export
                                     ▲
5080 local queue ── message_id/ACK ── Gateway
```

Reference Memory는 map revision과 승인 상태를 포함하는 운영 기준이다. Episodic
Memory는 실제 실행한 episode와 step의 결과를 보존한다. 실행하지 않은 candidate
rollout과 GPU replay buffer는 MySQL 핵심 원장이 아니라 artifact/cache다.

## 실시간 기록

복구 행동과 local safety는 DB 왕복을 기다리지 않는다. 5080은 record를 NVMe queue에
먼저 기록하고 Gateway ACK까지 같은 `message_id`로 재전송한다. Gateway는 idempotent
하게 한 번만 반영한다.

## 금지 연결

- RL/VLM이 전역 배차나 최종 안전 권한을 소유하지 않는다.
- 5080에 MySQL root/FMS 계정을 배포하지 않는다.
- 서로 다른 database 사이에 FK를 만들어 수명주기를 결합하지 않는다.
- replay buffer를 감사 원장으로 취급하지 않는다.
