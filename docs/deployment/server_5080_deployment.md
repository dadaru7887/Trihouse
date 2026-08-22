# RTX 5080 서버 배포

## 책임

- YOLO 실시간 streaming/inference
- VLM 상황 해석
- 승인된 RL checkpoint를 사용한 복구 후보 추론과 평가
- 추론 artifact와 전송 재시도용 로컬 NVMe cache
- Gateway ACK 전 recovery record 재전송 queue

5080은 MySQL 계정과 3306 접근 권한을 갖지 않는다. 실시간 안전 행동은 DB 응답을
기다리지 않으며, 기록은 `message_id`를 포함해 Gateway로 비동기 전송한다.

실물 운용 컨테이너는 학습 코드를 실행하지 않는다. 학습은 Gateway가 export한
`state[9], skill, coord[3], reward, next_state[9], done` JSONL을 별도
`compose.ai_training.yaml`에서 오프라인으로 수행하고, 검증된 checkpoint만 다시
추론 컨테이너의 `/models`에 배치한다.

## 호스트 전제조건

```bash
nvidia-smi
docker version
docker compose version
docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi
```

마지막 명령은 호스트 NVIDIA driver와 Container Toolkit을 함께 검증한다. CUDA image
tag는 실제 model framework 호환표를 확인해 고정한다.

## 배포

먼저 `origin/env`의 backend Docker 정의로 image를 build하거나 registry에서 받아
`.env`의 `TRIHOUSE_AI_IMAGE`로 지정한다. `compose.ai_5080.yaml` 자체는 MySQL 계정,
DB host 또는 3306 포트를 전달하지 않는다.

```bash
cd /home/syw/Trihouse
docker compose -f compose.ai_5080.yaml config --quiet
docker image inspect "$TRIHOUSE_AI_IMAGE"
docker compose -f compose.ai_5080.yaml up -d
docker compose -f compose.ai_5080.yaml ps
```

4060과 5080은 서로 다른 호스트이므로 Docker bridge network를 공유하지 않는다.
5080의 `FMS_GATEWAY_URL`은 4060의 실제 LAN 주소와 Gateway port로 설정한다.
현재 DHCP 예약 기준은 `http://192.168.0.9:8080`이다. `host.docker.internal`은
4060과 5080이 같은 PC일 때의 smoke test에만 사용한다.

필수 모델 값은 다음처럼 실제 파일과 hash로 확인한다.

```bash
ls -lh runtime/ai/models
sha256sum runtime/ai/models/<approved-policy-checkpoint.pt>
docker compose -f compose.ai_5080.yaml config --quiet
```

## 장애 시 기록

1. 행동 수행과 Safety Supervisor 판단은 로컬에서 계속한다.
2. 전송 실패 record를 NVMe queue에 보관한다.
3. 같은 `message_id`로 bounded backoff 재전송한다.
4. Gateway ACK 후에만 queue에서 제거한다.
5. queue 용량 초과 시 학습 후보 로그부터 축소하고 안전 사건은 보존한다.
