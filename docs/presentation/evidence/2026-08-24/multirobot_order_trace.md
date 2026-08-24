# 멀티로봇 주문 처리 코드 Trace

> Production planning/orchestration code dry-run. MySQL 저장과 실제 로봇 이동은 수행하지 않음.

## 1. 주문 입력

| 상품 | 요청 수량 |
|---|---:|
| SKU-AMBIENT-A | 6 |
| SKU-CHILLED-B | 3 |
| SKU-FROZEN-C | 2 |

## 2. FEFO Lot 배정

| 상품 | 선택 Lot | 예약 수량 |
|---|---|---:|
| SKU-AMBIENT-A | LOT-A-EARLY | 4 |
| SKU-AMBIENT-A | LOT-A-LATE | 2 |
| SKU-CHILLED-B | LOT-B-CHILLED | 3 |
| SKU-FROZEN-C | LOT-C-FROZEN | 2 |

## 3. 자원 할당

- AMR: **PK_01**
- Robot arms: **OMX_01, OMX_02**
- Packing dock: **PACKING-01-DOCK-01**
- Charger: **TRIHOUSE-TEST-01-CHG-01**

## 4. 생성된 작업 시퀀스

| Step | 구역/분기 | 실행 주체 | 동작 | 할당 장비 | 의존 Step | 최초 상태 |
|---:|---|---|---|---|---|---|
| 10 | ambient / omx_prepare | arm | prepare | OMX_01 | - | DISPATCHED |
| 20 | ambient / pinky_navigate | mobile | navigate | PK_01 | - | DISPATCHED |
| 30 | ambient / readiness_load_gate | fms | load | - | 10, 20 | WAITING |
| 40 | chilled / omx_prepare | arm | prepare | OMX_01 | 30 | WAITING |
| 50 | chilled / pinky_navigate | mobile | navigate | PK_01 | 30 | WAITING |
| 60 | chilled / readiness_load_gate | fms | load | - | 40, 50 | WAITING |
| 70 | frozen / omx_prepare | arm | prepare | OMX_02 | 60 | WAITING |
| 80 | frozen / pinky_navigate | mobile | navigate | PK_01 | 60 | WAITING |
| 90 | frozen / readiness_load_gate | fms | load | - | 70, 80 | WAITING |
| 100 | common / packing_navigate | mobile | navigate | PK_01 | 90 | WAITING |
| 110 | common / common | fms | handover | - | 100 | WAITING |
| 120 | common / worker_completion | fms | wait | - | 110 | WAITING |
| 130 | common / common | mobile | return_home | PK_01 | 120 | WAITING |

최초 polling에서 Step 10(OMX 준비)과 Step 20(Pinky 이동)이 동시에 dispatch되고,
두 단계가 모두 완료되어야 Step 30(load gate)이 진행된다.
