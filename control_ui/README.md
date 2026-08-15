# RoboSapiens 물류 플랫폼

3온도(상온·냉장·냉동) 물류센터의 자율주행 로봇 운영 시스템입니다.

## 구성

| 패키지 | 역할 | 상태 |
|---|---|---|
| [`robo_core/`](robo_core/) | 공용 도메인 모델 + 저장소 계층 (Repository 인터페이스 · SQLite 구현) | 구현 |
| [`robo_control/`](robo_control/) | **관제센터** — 로봇 배차·안전·재고·주문 통제 (Flutter desktop) | 구현 |
| [`roboapp/`](roboapp/) | **소비자 주문 앱** — 3온도 상품 주문 + WebRTC 실시간 화면 (Flutter web·Android) | 구현 |
| [`robo_pinky/`](robo_pinky/) | **로봇 시뮬레이터** — Gazebo 안의 Pinky 3대와 구획별 적재 로봇팔(OMX) 3대를 관제에 실장비로 연결 (ROS 2 Jazzy · Gazebo Harmonic) | 구현 |
| [`openrmf_app/`](openrmf_app/) | **Open-RMF Office 관제 앱** — rmf-web API의 지도·로봇·태스크를 표시하는 Flutter desktop | 구현 |
| [`openrmf/`](openrmf/) | **Open-RMF 실행 구성** — office 데모와 rmf-web API, Flutter 앱 연결 | 구현 |

```
소비자 앱 ─┐                                     ┌─ 시뮬레이션 로봇 (RS-xx)
           ├─▶ orders 테이블 ─▶ 관제센터 ─▶ ────┼─ Gazebo Pinky   (PK-xx)
   WMS ────┘      (robo_core)      │             └─ 적재 로봇팔    (OMX-x)
                                   └── TCP 8788 ───┘
```

`orders`가 두 앱의 접점입니다. 소비자 앱이 주문을 쓰고, 관제센터가 읽어
FEFO·긴급도·동선 기반으로 로봇 태스크를 전개합니다.

관제센터는 로봇 링크 게이트웨이(TCP 8788)를 함께 엽니다. 여기에 접속한 로봇은
**위치·배터리를 스스로 보고하고 관제는 경로·정지·속도 상한만 하달**합니다.
`robo_pinky`가 그 자리에 Gazebo의 Pinky를 붙여, 실장비 투입 전에 관제 로직을
물리 시뮬레이션 위에서 검증합니다.

## 시작하기

```bash
# 관제센터
cd robo_control && flutter run -d linux

# 소비자 앱
cd roboapp && flutter run -d chrome

# Gazebo 로봇 (관제센터와 함께 실행)
cd robo_pinky && ./run.sh
```

## 문서

| | 설계 | 사용 |
|---|---|---|
| 관제센터 | [PROJECT_SUMMARY.md](robo_control/docs/PROJECT_SUMMARY.md) | [USER_GUIDE.md](robo_control/docs/USER_GUIDE.md) |
| 로봇 시뮬레이터 | [PROJECT_SUMMARY.md](robo_pinky/docs/PROJECT_SUMMARY.md) | [USER_GUIDE.md](robo_pinky/docs/USER_GUIDE.md) |

패키지별 개요는 [robo_control/README.md](robo_control/README.md),
[robo_pinky/README.md](robo_pinky/README.md)에 있습니다.

## 저장소

원장은 SQLite (`~/.local/share/robo_control/robo_control.db`, `ROBOAPP_DB_DIR`로 변경 가능).
소비자 앱이 붙는 시점에는 `robo_core`의 `DataStore` 구현만 PostgreSQL·REST로
교체하면 됩니다 — UI와 제어 로직은 그대로입니다.
