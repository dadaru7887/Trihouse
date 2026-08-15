# roboapp — RoboSapiens 마트 (소비자 주문 앱)

상온·냉장·냉동 3온도 상품을 주문하고, **로봇이 상품을 가져오는 모습을
실시간 영상으로 확인**하는 앱입니다.

## 화면

| | |
|---|---|
| 상품 목록 | 상온·냉장·냉동 3개 탭. 재고·가격·유통기한 임박 표시 |
| 장바구니 | 수량 조절, 수령 희망 시간(15분~3시간) 선택 |
| 주문 내역 | 주문별 진행률 · 담당 로봇 · 수령 예정 시각 |
| 실시간 화면 | WebRTC 영상 (현재는 로컬 카메라) |

## 실행

```bash
flutter run -d chrome
```

브라우저가 카메라 권한을 물으면 **허용**해야 실시간 화면이 나옵니다.

## 실시간 화면에 대해

`getUserMedia()` + `RTCVideoRenderer`, 즉 **WebRTC 표준 API를 그대로** 씁니다.
지금은 이 기기의 카메라를 띄우지만, 로봇 카메라 연동 시
[`live_view_page.dart`](lib/ui/live_view_page.dart)의 `_openLocalCamera()`를
시그널링 접속 + `RTCPeerConnection` 원격 트랙 구독으로 바꾸면 되고,
렌더러와 화면 구성은 그대로 유지됩니다.

> **Linux 데스크톱 빌드는 지원하지 않습니다.** Flutter 스냅이 번들한 구형
> 툴체인이 `flutter_webrtc`가 요구하는 시스템 라이브러리(glibc 2.34+)와
> 링크되지 않습니다. 웹·Android로 실행하세요.

## 데이터 연결

플랫폼에 따라 저장소가 달라집니다 ([`store_factory.dart`](lib/data/store_factory.dart)).

| 타깃 | 저장소 | 관제센터 연동 |
|---|---|---|
| 웹 | `MemoryDataStore` + 데모 카탈로그 | 없음 (`dart:ffi` 불가) |
| Android · 데스크톱 | `SqliteDataStore` | 같은 원장 직접 공유 |

네이티브 빌드에서 접수한 주문은 `orders` 테이블에 `expanded = 0`으로 남고,
관제센터가 3초 주기로 읽어 로봇 출고 태스크로 전개합니다. 소비자 앱은
스케줄러·평면도를 알 필요가 없습니다.

실제 서비스에서는 휴대폰이 관제 PC의 파일을 열 수 없으므로, 서버 API를
호출하는 `DataStore` 구현으로 교체해야 합니다.

## 테스트

```bash
flutter test    # 4개 — 카탈로그 집계 · 장바구니 상한 · 주문 저장 · 화면 렌더링
```
