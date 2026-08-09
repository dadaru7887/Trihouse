# RTX 4060 서버 배포

## 책임

- 기존 `control_system` 관제 UI와 Open-RMF
- `control_tower` Task Manager/backend
- MySQL 8.4의 `trihouse_fms`, `trihouse_recovery`
- FMS Gateway와 DB 쓰기 트랜잭션
- QR 인식, 영상 중계·보존, 5080 전달

## 배포 순서

1. Ubuntu, Docker Engine, Compose V2를 설치한다.
2. 저장 장치와 백업 경로를 정하고 `.env` 비밀값을 생성한다.
3. `compose.db.yaml`을 먼저 실행하고 healthcheck와 스키마를 확인한다.
4. `compose.control.yaml`을 실행해 Gateway/Task Manager의 DB 연결을 확인한다.
5. `compose.edge_4060.yaml`의 QR·영상 서비스를 실행한다.
6. 마지막으로 기존 `control_system` UI/Open-RMF를 연결한다.

```bash
cd /home/syw/Trihouse
docker compose -f compose.db.yaml up -d --wait
docker compose -f compose.control.yaml up -d --build --wait
docker compose -f compose.edge_4060.yaml up -d mediamtx
```

`qr_worker`와 `recording_catalog`은 실제 장기 실행 image가 준비된 뒤 다음처럼
추가한다.

```bash
docker compose -f compose.edge_4060.yaml \
  --profile application_images up -d
```

개발 중 Adminer를 `127.0.0.1:8080`에 띄웠다면 Gateway와 포트가 겹친다. Adminer를
중지하거나 `.env`의 `FMS_API_PORT`를 다른 값으로 설정한다.

## 권한과 네트워크

- MySQL 3306은 기본적으로 `127.0.0.1` 또는 내부 Docker network에만 노출한다.
- UI, 장비 adapter, 5080 AI 서비스는 MySQL에 직접 쓰지 않는다.
- 외부 요청은 Gateway API에서 인증·검증·idempotency를 거친다.
- 영상 artifact와 DB backup은 서로 다른 보존 정책과 디스크 quota를 둔다.

## 운영 확인

```bash
docker compose -f compose.db.yaml ps
docker compose -f compose.control.yaml ps
docker compose -f compose.edge_4060.yaml ps
df -h
```
