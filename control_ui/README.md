# Trihouse Control UI

Trihouse의 브라우저 전용 관제 화면입니다. 실행 가능한 애플리케이션은
[`rmf_control_ui/`](rmf_control_ui/) 하나이며, 모든 운영 데이터와 명령은 FMS
Gateway의 공개 `/api/v1/*` HTTP/WebSocket 계약을 통해 오갑니다.

브라우저 인증은 Gateway가 발급한 Secure HttpOnly 세션 쿠키를 사용합니다. 기본
배포는 same-origin이며, 별도 Gateway origin은 명시적인 credentialed-CORS 설정과
HTTPS, `SameSite=None; Secure`, 정확한 allowed-origin 정책이 필요합니다. 장기
토큰은 Flutter 코드나 WebSocket URL에 전달하지 않습니다.

이 디렉터리는 데이터베이스 스키마·마이그레이션, ROS/Open-RMF 프로세스 실행,
로봇 소켓 서버, 로컬 프로젝트 파일 저장을 소유하지 않습니다. 해당 책임은 루트
프로젝트의 `fms_gateway`, `control_tower`, `trihouse_rmf_bridge`에 있습니다.

`UPSTREAM_CONTROL_SYSTEM_COMMIT`은 최초 복사본의 출처만 기록합니다. 브라우저 및
Gateway 경계로 리팩터링한 현재 트리는 원본과 byte-equivalent하지 않습니다.

## 개발

```bash
cd control_ui/rmf_control_ui
flutter test
flutter analyze
flutter run -d chrome --dart-define=FMS_GATEWAY_BASE_URL=http://127.0.0.1:8000
```
