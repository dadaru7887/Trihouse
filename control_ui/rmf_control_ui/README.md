# RMF Control UI

Flutter Web 기반 Trihouse 관제 프런트엔드입니다.

런타임 백엔드 경계는 `lib/trihouse/api/FmsApi` 하나입니다. 기본 구현인
`FmsApiClient`는 브라우저에서 사용할 수 있는 HTTP/WebSocket 패키지만 사용하며,
공개 `/api/v1/*` 경로만 호출합니다. 앱 셸은 `FmsApi`를 생성하지 않고 생성자에서
주입받으므로 위젯 테스트와 이후 기능 페이지도 같은 경계를 사용합니다.

남아 있는 최상위 Dart 라이브러리는 지도 geometry, SLAM/PGM parsing, Nav2 설정
표시용 parsing, dialog presentation처럼 브라우저에서 순수하게 계산하거나 그릴 수
있는 코드입니다. 로컬 DB, 파일 저장, ROS/process launch, telemetry socket 구현은
포함하지 않습니다.

## 실행

```bash
flutter pub get
flutter run -d chrome \
  --dart-define=FMS_GATEWAY_BASE_URL=http://127.0.0.1:8000
```

`FMS_GATEWAY_BASE_URL`을 생략하면 현재 페이지 origin을 사용합니다.

## 브라우저 인증

Control UI는 장기 토큰을 JavaScript, local storage, 요청 URL 또는 WebSocket
query에 보관하지 않습니다. 공개 Gateway가 발급한 `Secure`, `HttpOnly` 세션 쿠키를
HTTP와 WebSocket 인증에 함께 사용합니다.

- 기본값은 같은 origin입니다. 브라우저의 `same-origin` credential 정책으로
  세션 쿠키가 자동 전송됩니다.
- Gateway가 다른 origin이면 HTTPS 주소와
  `--dart-define=FMS_GATEWAY_CROSS_ORIGIN_CREDENTIALS=true`를 모두 명시해야 합니다.
  이때 HTTP client는 credentialed CORS 요청을 사용합니다.
- Cross-origin 배포의 Gateway는 정확한 Control UI origin을 허용하고
  `Access-Control-Allow-Credentials: true`를 반환해야 합니다. 세션 쿠키는
  `SameSite=None; Secure; HttpOnly`로 발급해야 합니다.
- 브라우저 WebSocket은 별도 Authorization header를 설정할 수 없으므로 같은 보안
  세션 쿠키와 Gateway의 allowed-origin 검사를 사용합니다. 토큰을 WebSocket URL에
  넣지 않습니다.

```bash
flutter run -d chrome \
  --dart-define=FMS_GATEWAY_BASE_URL=https://gateway.example \
  --dart-define=FMS_GATEWAY_CROSS_ORIGIN_CREDENTIALS=true
```

## 검증

```bash
flutter test
flutter analyze
```
