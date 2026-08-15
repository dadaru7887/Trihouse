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

## 검증

```bash
flutter test
flutter analyze
```
