# System Requirements

## 작성 기준

- 본 문서는 2026년 8월 21일 시연 영상 완료를 목표로 하는 4주 프로젝트의 시스템 요구사항이다.
- Priority `High`는 기본 시나리오와 안전을 위해 반드시 구현하는 기능, `Medium`은 기본 시나리오를 보조하는 운영·예외 대응 기능, `Low`는 핵심 기능 완료 후 구현하는 확장 기능을 의미한다.
- 입고 기본 시나리오는 QR·DB 등록이 완료된 상태에서 시작한다. QR 인식부터 DB 등록 및 Pinky 배정까지의 자동화는 Low 확장 범위로 둔다.
- 모든 물품은 Pinky와 OMX가 취급할 수 있는 범위라고 가정하며, 로드셀과 무게 기반 판단은 사용하지 않는다.
- Pinky는 물품을 목적지까지 운반하고 정차한다. 물품 하차와 후속 처리는 OMX 또는 작업자가 수행한다.
- 대기·충전소 복귀는 지정 위치로 이동하는 기능이며 충전 단자 접촉을 자동화하지 않는다.
- 작업 중에는 원본 재고 DB를 변경하지 않고, 물품의 최종 적재 또는 전달이 완료된 후에만 반영한다. 이번 범위에서는 DB 저장 실패 복구를 다루지 않는다.
- 기본 범위에서는 주문 1건에 Pinky 1대를 배정한다. 주문 1건을 여러 Pinky가 나누어 처리하는 기능은 Low 확장 범위다.
- 통신은 정상적으로 유지된다고 가정한다. 통신 단절 안전정지와 복구는 별도의 Low 확장 기능으로만 정의한다.

## 요구사항

| SR ID | Category | Subject | Name | Priority | UR ID | Description |
| --- | --- | --- | --- | --- | --- | --- |
| SR_01 | 입고, 출고, 비상상황 | 관제 UI | 통합 관제 화면 기능 | High | UR_07 | 관제 UI는 운영자가 하나의 화면에서 등록된 모든 Pinky와 OMX, 진행 중인 입고·출고 작업 및 사람 위급상황을 확인할 수 있도록 한다.<br>• 창고 지도에 Pinky의 위치와 방향을 표시하고 로봇별 배터리, 안전 상태, 현재 작업과 오류를 함께 표시한다.<br>• 작업별 주문·물품, 배정 로봇, 현재 단계 및 대기·진행·완료·실패 상태를 표시한다.<br>• 사람 위급상황은 발생 위치와 시각을 일반 알림보다 눈에 띄게 표시한다.<br>• 카메라 영상은 운영자가 선택한 경우에만 CCTV 다중 화면으로 재생하며, 선택 여부와 관계없이 녹화 서버의 저장은 계속된다.<br>• UI는 Gateway의 REST·WebSocket을 사용하고 DB, RMF 또는 ROS 노드에 직접 접근하지 않는다. |
| SR_02 | 입고, 출고, 비상상황 | 관제 UI, FMS | 관리자 개입 기능 | High | UR_07, UR_12 | 관제 UI는 자동 처리로 해결되지 않는 작업에 한해 운영자가 작업 보류, 재개, 취소 또는 재할당을 요청할 수 있도록 한다.<br>• 정상적인 할당, 정지, 취소와 재할당은 FMS가 자동 수행하고 관리자 판단이 필요한 작업만 개입 대상으로 표시한다.<br>• 취소와 재할당은 확인 절차를 거치며 같은 요청을 중복 실행하지 않는다.<br>• 물품을 파지하거나 운반 중이면 로봇이 현재 물품을 안전하게 유지한 상태에서 작업을 보류한다.<br>• 재할당은 마지막으로 정상 완료된 단계의 다음 단계부터 시작하며 완료된 파지·적재·운반 단계를 반복하지 않는다.<br>• 실행할 수 없는 요청은 기존 작업 상태를 유지하고 사유를 화면에 표시한다. |
| SR_03 | 입고, 출고, 비상상황 | Pinky, OMX | 로봇 상태 공유 기능 | High | UR_06, UR_07 | Pinky와 OMX는 FMS가 작업을 배정하고 관제 UI가 진행 상태를 표시할 수 있도록 현재 상태를 주기적으로 전송한다.<br>• 공통 정보에는 로봇 ID, 전송 시각, 작업 ID와 현재 단계를 포함한다.<br>• Pinky는 위치·방향, 배터리, 주행, 적재, 안전 및 오류 상태를 전송한다.<br>• OMX는 준비, 동작, 파지·적재, 안전 및 오류 상태를 전송한다.<br>• 기본 전송 주기는 1초로 하고 작업 단계나 안전 상태가 바뀌면 즉시 전송한다.<br>• 센서 또는 제어 오류로 작업할 수 없으면 `작업 불가` 상태를 전송하고 FMS는 새 작업을 배정하지 않는다. |
| SR_04 | 입고, 출고, 비상상황 | DB, 녹화 서버 | 작업·비상 이력 및 영상 기록 기능 | High | UR_10, UR_15 | DB와 녹화 서버는 입고·출고 작업 및 사람 위급상황을 작업 ID와 시각을 기준으로 추적할 수 있도록 기록한다.<br>• DB에는 작업 ID, 주문·물품 ID, 로봇 ID, 단계별 시작·종료 시각, 결과, 취소·재할당 및 관리자 개입을 기록한다.<br>• 녹화 서버는 관제 화면의 재생 여부와 관계없이 등록된 모든 카메라의 H.264 영상을 계속 저장한다.<br>• 영상은 카메라 ID와 시각으로 조회할 수 있는 1분 단위 파일로 저장한다.<br>• 저장 한도를 넘으면 재생 중이거나 기록 중인 파일을 제외하고 가장 오래된 완료 파일부터 삭제한다.<br>• 최종 보존 기간과 용량은 실제 서버 저장 공간을 확인한 후 설정값으로 확정한다. |
| SR_05 | 입고, 출고, 비상상황 | YOLO | 저조도 데이터 증강 기반 인식 기능 | High | UR_08 | YOLO는 저조도·반사·그림자가 포함된 학습 데이터로 학습하여 상온·냉장·냉동 구역에서 사람과 물품 인식 성능을 유지한다.<br>• 밝기, 대비, 노이즈와 그림자 증강은 학습 데이터셋을 만들 때만 적용한다.<br>• 실시간으로 들어오는 영상에는 밝기나 대비 보정을 적용하지 않는다.<br>• 원본 검증 세트와 저조도 검증 세트를 분리해 사람·물품 검출 성능을 확인한다.<br>• QR 해독과 ArUco 검출은 전용 OpenCV 처리기를 사용하며 YOLO가 대신하지 않는다.<br>• 물품 또는 마커를 확인하지 못하면 OMX 작업을 시작하지 않고 정해진 재인식 절차로 전환한다. |
| SR_06 | 입고, 출고 | FMS, DB | 작업 완료 후 원본 DB 반영 기능 | High | UR_01, UR_02, UR_15 | FMS와 DB는 작업 중간 상태를 원본 재고에 반영하지 않고 물품의 최종 적재 또는 전달이 완료된 후 결과를 한 번만 반영한다.<br>• 작업 진행 상태는 원본 재고와 분리된 작업 단계 데이터로 관리한다.<br>• 입고는 지정 선반 적재가 완료된 후 수량, 보관 구역과 선반·슬롯을 반영한다.<br>• 출고는 포장대 또는 작업자 전달 위치까지 인계가 완료된 후 출고 수량과 상태를 반영한다.<br>• 파지, OMX-Pinky 적재와 운반 같은 중간 단계에서는 원본 재고를 변경하지 않는다.<br>• 보류·취소된 작업은 작업 상태만 변경하고 원본 재고는 유지한다. |
| SR_07 | 입고, 출고 | FMS | 작업 할당 기능 | High | UR_01, UR_02, UR_06, UR_13 | FMS는 주문과 로봇의 상태·일정을 바탕으로 Pinky를 배정하고, Pinky의 창고별 도착 예상 시각에 맞춰 OMX 작업을 할당한다.<br>• 기본 범위에서는 주문 1건을 완료할 때까지 Pinky 1대에만 배정한다.<br>• 현재 작업 중인 Pinky도 예상 완료·복귀 시각을 계산해 다음 작업을 미리 예약할 수 있으며 작업 시간은 겹치지 않아야 한다.<br>• 같은 창고 또는 동일 OMX 작업 위치의 물품은 하나의 작업 묶음으로 구성한다.<br>• Pinky의 예상 출발 위치에서 각 작업 묶음을 거쳐 포장대까지의 전체 이동 시간이 짧아지도록 방문 순서를 정한다.<br>• **작업 사전 할당 시에는 Pinky의 현재 작업 예상 완료·복귀 시각에 FMS 주행 그래프의 구간 길이를 실험으로 측정한 구간별 유효 속도로 나눈 주행 시간을 더해 창고별 도착 예상 시각을 계산한다.**<br>• **Nav2가 실제 경로를 생성하면 해당 구간의 FMS 예상값을 `Nav2 남은 경로 길이 ÷ 실험 기반 유효 속도`로 교체하고, 경로가 다시 생성되면 남은 경로를 기준으로 도착 예상 시각을 갱신한다. FMS 경로 길이와 Nav2 경로 길이는 중복 합산하지 않는다.**<br>• **FMS는 각 OMX에 대해 `Pinky 예상 도착 시각 - OMX 평균 파지 시간 - 준비 여유 시간`으로 사전 파지 시작 시각을 계산하고 해당 시각에 명령을 전송한다.**<br>• **여러 OMX의 사전 파지 일정은 독립적으로 계산하여 같은 주문의 서로 다른 창고 물품을 병렬로 준비할 수 있지만, 실제 적재는 해당 Pinky 도착과 양쪽 준비 완료 후 시작한다.**<br>• RMF/Fleet Adapter는 배정된 Pinky의 경로와 교통을 조정하며 같은 주문의 Pinky를 임의로 변경하지 않는다. |
| SR_08 | 입고, 출고 | FMS | 작업 재할당 기능 | Medium | UR_12 | FMS는 Pinky가 작업을 계속 수행할 수 없을 때 미완료 작업을 다른 Pinky에 재할당한다.<br>• 작업 시작 전이면 주문 전체를 다른 Pinky에 배정한다.<br>• 작업 진행 중이면 마지막으로 정상 완료된 단계의 다음 단계부터 이어서 수행한다.<br>• 완료된 파지, 적재 또는 운반 단계는 재할당된 Pinky가 반복하지 않는다.<br>• 물품이 기존 Pinky에 실려 있어 다른 Pinky가 직접 이어받을 수 없으면 작업을 보류하고 관리자 개입 필요 상태로 표시한다.<br>• 즉시 가능한 Pinky가 없으면 예상 완료·복귀 시각이 가장 빠른 Pinky의 다음 작업으로 예약한다. |
| SR_09 | 입고, 출고 | FMS, RMF/Fleet Adapter | 공유 작업공간·경로 예약 기능 | High | UR_06, UR_09, UR_14 | FMS와 RMF/Fleet Adapter는 같은 작업 위치나 좁은 통로를 여러 Pinky가 동시에 사용하지 않도록 공간과 진입 시간을 예약한다.<br>• FMS는 OMX 작업 위치, 픽업 위치, 포장대 및 대기·충전 위치의 사용 상태를 관리한다.<br>• RMF/Fleet Adapter는 등록된 주행 그래프를 기준으로 좁은 통로의 진입 순서를 조정한다.<br>• 예약 권한이 없는 Pinky는 지도에 등록된 가까운 대기 노드에서 기다린다.<br>• 작업 우선순위가 높은 요청을 먼저 처리하고 같은 우선순위이면 먼저 요청한 작업을 우선한다.<br>• 로봇이 공간을 벗어나거나 작업이 취소되면 예약을 해제한다.<br>• RMF 교통 조정과 별개로 사람이나 즉시 장애물에 대한 정지는 Pinky의 Nav2·안전 기능이 수행한다. |
| SR_10 | 입고, 출고 | FMS | 다량 물품 작업 분할 기능 | Low | UR_01, UR_02, UR_11 | FMS는 기본 기능에서 구성한 창고별 작업 묶음을 여러 Pinky에 분할 할당하여 다량 물품 주문의 전체 완료 시간을 줄인다.<br>• 이 확장 기능에서는 주문 1건에 여러 Pinky를 배정할 수 있다.<br>• 각 작업 묶음은 Pinky의 예상 출발 위치, 기존 작업 완료 시각, 배터리 상태 및 포장대까지의 이동 시간을 기준으로 배정한다.<br>• 같은 창고의 작업 묶음은 나누지 않고 한 Pinky가 처리하며 하나의 작업 묶음을 중복 할당하지 않는다.<br>• 배터리가 부족한 Pinky에는 포장대와 가까운 창고처럼 이동 거리가 짧은 작업 묶음을 우선 배정한다.<br>• 현재 가능한 Pinky가 없어도 예상 완료·복귀 시각이 가장 빠른 Pinky의 다음 작업으로 미리 예약한다.<br>• 모든 Pinky가 담당 물품을 지정 위치에 전달한 경우에만 주문 전체를 완료 처리한다. |
| SR_11 | 입고, 출고 | OMX | 물품 파지 기능 | High | UR_13 | OMX는 물품의 위치와 식별 정보가 확인되면 물품을 파지하고 파지 성공을 확인한 후 다음 적재 단계로 진행한다.<br>• FMS는 기존 NDJSON/TCP 연결을 통해 작업 ID, 주문 ID, 물품 ID와 대상 선반·슬롯을 OMX에 전달한다.<br>• OMX는 DB에 저장된 선반·슬롯 정보와 ArUco로 보정한 사전 등록 파지 좌표를 사용하며, 해당 위치의 QR 정보가 작업 대상 물품과 일치하는 경우에만 파지한다.<br>• 입고 작업은 물품을 실은 Pinky가 OMX 작업 위치에 도착하고 두 로봇이 준비된 후 파지를 시작한다.<br>• 출고 작업은 FMS의 사전 파지 명령에 따라 Pinky 도착 전에 물품을 파지하고 안전 대기 자세에서 기다린다.<br>• 파지 동작과 들어 올림을 정상 완료하지 못하면 다음 적재 동작을 수행하지 않고 파지 실패를 전송한다.<br>• 출고용 사전 파지와 Pinky 도착 후 적재는 서로 다른 명령 단계로 구현한다. |
| SR_12 | 입고, 출고 | YOLO | 공통 물품 위치·존재 인식 기능 | Low | UR_01, UR_02, UR_13 | YOLO는 물품 종류와 관계없이 공통 물품 클래스로 물품의 존재 여부와 영상 내 위치를 인식하여 사전 등록 좌표만으로 파지하기 어려운 경우 OMX의 보조 위치 정보로 제공한다.<br>• 고정 카메라 또는 OMX 카메라 영상에서 공통 `item` 클래스의 존재 여부, 바운딩 박스 중심점과 신뢰도를 출력한다.<br>• ArUco로 보정한 카메라 좌표와 선반·슬롯 기준 평면을 사용하여 검출 중심점을 OMX 작업 좌표로 변환한다.<br>• 물품 ID는 YOLO가 판단하지 않으며 QR 정보가 작업 대상 물품과 일치할 때만 검출 좌표를 사용할 수 있다.<br>• 기본 파지는 사전 등록 좌표를 우선 사용하고 위치 이탈 또는 반복 파지 실패 시에만 이 기능을 사용한다.<br>• 여러 물품 중 대상을 하나로 결정할 수 없거나 신뢰도가 기준보다 낮으면 좌표를 제공하지 않는다. |
| SR_13 | 입고, 출고 | OMX | 파지 실패 재시도 기능 | High | UR_13 | OMX는 최초 파지에 실패하면 같은 물품을 안전 자세에서 다시 확인하고 설정된 횟수만큼 재파지한다.<br>• 재시도 전 그리퍼를 열고 사전 등록된 관측 자세로 복귀한다.<br>• 매 시도마다 ArUco 위치와 QR 물품 ID를 다시 확인한다.<br>• 초기 구현의 재시도 횟수는 3회로 설정하고 설정 파일에서 변경할 수 있도록 한다.<br>• 같은 좌표로 반복하지 않고 허용 범위 안에서 사전 등록된 보정 좌표를 순서대로 사용한다.<br>• 설정 횟수 이후에도 실패하면 동작을 멈추고 최종 파지 실패 처리로 전환한다. |
| SR_14 | 입고, 출고 | OMX | 바구니 위치·자세 보정 기능 | High | UR_01, UR_02, UR_13 | OMX는 고정 카메라 영상에서 인식한 Pinky 바구니의 외곽 네 모서리를 기준으로 바구니 위치와 회전을 계산하고 파지·적재 자세를 보정한다.<br>• 물품에 가려질 수 있는 바구니 내부 마커는 사용하지 않고 물품보다 바깥쪽에 보이는 바구니 테두리를 YOLO OBB로 인식해 네 꼭짓점을 구한다.<br>• 사전에 등록한 바구니 크기와 카메라 보정값을 사용하여 네 모서리를 OMX 기준 좌표로 변환한다.<br>• 보정 결과는 바구니 내부의 사전 등록 파지·적재 좌표에 평행이동과 회전으로 적용한다.<br>• 바구니 외곽을 안정적으로 인식하지 못하거나 보정량이 허용 범위를 넘으면 OMX를 움직이지 않고 Pinky 재정차를 요청한다.<br>• Pinky는 항상 같은 작업 위치에 정차하도록 하고 이 기능은 남은 정차 오차만 보정한다. |
| SR_15 | 입고, 출고 | OMX | 다중 물품 임시 적재 기능 | High | UR_01, UR_02, UR_13 | OMX는 같은 창고에서 처리할 물품이 2개 이상이면 파지한 물품을 등록된 임시 선반에 순서대로 준비한 뒤 Pinky 또는 지정 선반으로 옮긴다.<br>• 물품이 1개이면 파지한 상태로 안전 대기 자세를 유지할 수 있다.<br>• 물품이 2개 이상이면 빈 임시 슬롯에 내려놓고 다음 물품을 처리한다.<br>• 임시 슬롯에는 작업 ID, 주문 ID와 물품 ID를 연결해 다른 작업이 사용하지 못하도록 예약한다.<br>• 다시 파지할 때 QR을 확인하여 해당 임시 슬롯의 예약 물품과 일치해야 한다.<br>• 빈 임시 슬롯이 없으면 추가 물품을 파지하지 않고 현재 준비된 물품 처리까지 기다린다. |
| SR_16 | 입고, 출고 | OMX | 로봇팔 사람 충돌 방지 기능 | High | UR_09, UR_13 | OMX는 작업 영역 안에 사람이 들어오면 진행 중인 동작을 정지하고 사람이 벗어난 후 안전한 단계부터 작업을 재개한다.<br>• YOLO의 사람 검출 결과가 OMX 작업 금지 영역과 겹치면 그리퍼 상태를 유지한 채 관절 동작을 정지한다.<br>• 정지 중에는 새로운 파지·적재 명령을 시작하지 않는다.<br>• 사람이 연속된 확인 프레임 동안 작업 영역 밖에 있고 OMX 상태가 정상일 때만 재개한다.<br>• 물품을 들고 있으면 바로 놓지 않고 현재 자세를 유지하거나 등록된 안전 자세로 이동한다.<br>• 재개 시 완료된 단계는 반복하지 않는다. |
| SR_17 | 입고, 출고 | QR·ArUco | 물품 정보 일치 확인 기능 | High | UR_01, UR_02, UR_13 | QR·ArUco 처리기는 OMX가 파지하려는 물품과 활성 작업에 예약된 물품이 일치하는지 확인한다.<br>• FMS가 제공한 주문 ID, 예약 물품 ID와 대상 선반·슬롯을 기준 정보로 사용한다.<br>• QR에서 읽은 물품 ID가 예약 물품 ID와 일치하고 해당 예약이 같은 주문 ID에 속할 때만 파지를 승인한다.<br>• 입고 QR에는 상온·냉장·냉동 보관 방법을 포함하며 출고 대상 확인에는 예약 물품 ID를 사용한다.<br>• QR을 읽지 못하거나 정보가 일치하지 않으면 파지를 시작하지 않고 재인식한다.<br>• 반복 불일치는 해당 물품을 보류하고 FMS에 불일치 정보를 전달한다. |
| SR_18 | 입고, 출고 | QR·ArUco | 선반·슬롯 위치 확인 기능 | High | UR_01, UR_02, UR_13 | QR·ArUco 처리기는 OMX 작업 전에 카메라로 선반 마커를 확인하고 사전 등록된 선반·슬롯 좌표를 실제 관측 위치에 맞게 보정한다.<br>• 마커 ID, 실제 크기, 카메라 내부 파라미터와 `marker_to_slot` 변환을 설정 파일에 등록한다.<br>• 관측한 마커 ID가 작업 대상 선반과 일치할 때만 좌표 보정을 수행한다.<br>• 보정된 위치와 회전이 허용 오차 안이면 OMX에 파지·적재 시작 자세를 제공한다.<br>• 마커를 찾지 못하거나 다른 마커가 검출되거나 오차가 기준을 넘으면 OMX 동작을 시작하지 않고 재인식한다. |
| SR_19 | 입고, 출고 | YOLO | 로봇팔 작업영역 사람 감지 기능 | High | UR_09, UR_13 | YOLO는 고정 카메라에서 OMX 작업 영역에 접근한 사람을 검출하여 OMX 안전 제어에 전달한다.<br>• 카메라별 OMX 작업 금지 영역을 다각형 ROI로 사전 등록한다.<br>• 검출 결과에는 카메라 ID, 시각, 사람 바운딩 박스, 신뢰도와 ROI 중첩 여부를 포함한다.<br>• 한 프레임의 오검출을 줄이기 위해 설정된 연속 프레임 조건을 만족할 때 사람 진입 이벤트를 전송한다.<br>• 사람이 검출되지 않는 경우에도 OMX의 자체 관절·작업공간 제한은 계속 적용한다. |
| SR_20 | 입고, 출고 | YOLO | Pinky 주행경로 사람 감지 기능 | High | UR_09 | YOLO는 Pinky 전방 영상에서 사람을 검출하고 주행 경로와 겹치는 사람 정보를 Pinky 안전 제어에 전달한다.<br>• 검출 결과에는 Pinky ID, 프레임 시각, 사람 바운딩 박스, 신뢰도와 추적 ID를 포함한다.<br>• Pinky에서 수신한 영상은 RTSP로 영상 서버에 전달하고 YOLO 결과만 경량 메시지로 반환한다.<br>• 연속 프레임에서 같은 사람을 추적하여 일시적인 오검출과 실제 접근을 구분한다.<br>• 즉시 정지 판단은 YOLO만 사용하지 않고 Pinky의 거리 센서와 Nav2 안전 상태를 함께 사용한다. |
| SR_21 | 입고, 출고 | FMS | 최종 파지 실패 보고 기능 | High | UR_13, UR_15 | FMS는 OMX의 정해진 재시도가 모두 실패하면 해당 물품 작업을 보류하고 관제 UI에 최종 파지 실패를 표시한다.<br>• 실패 정보에는 작업 ID, 주문 ID, 물품 ID, 선반·슬롯, OMX ID와 최종 실패 시각을 포함한다.<br>• 오류 원인을 세부 분류하도록 요구하지 않고 OMX가 제공한 마지막 결과를 그대로 기록한다.<br>• 최종 실패 시각을 기준으로 이전 설정 구간의 카메라 영상을 찾을 수 있도록 카메라 ID와 녹화 파일 경로를 함께 전달한다.<br>• 다른 물품 작업을 계속할 수 있으면 실패 물품만 보류하고, 계속할 수 없으면 해당 작업 묶음을 보류한다. |
| SR_22 | 입고, 출고 | Pinky | 미끄럼 감지·주행 보정 기능 | Low | UR_08, UR_09 | Pinky는 바퀴 오도메트리와 IMU의 이동량 차이를 이용해 미끄럼을 감지하고 속도를 낮춰 주행 오차를 줄인다.<br>• 직진·회전 명령 대비 오도메트리와 IMU 변화가 설정된 범위를 벗어나면 미끄럼으로 판단한다.<br>• 미끄럼이 감지되면 속도를 제한하고 Nav2에 현재 위치 기준 경로 재계획을 요청한다.<br>• 위치 오차가 계속 커지면 안전하게 정지하고 작업을 보류한다.<br>• 임계값은 상온·냉장·냉동 바닥에서 실제 주행 시험 후 설정 파일로 확정한다. |
| SR_23 | 입고, 출고 | Pinky | 사람 충돌 방지 주행 기능 | High | UR_09 | Pinky는 주행 경로에서 사람이 감지되면 안전거리를 유지하도록 감속 또는 정지하고 경로가 안전해진 후 이동을 재개한다.<br>• 전방 거리 센서의 정지 조건은 영상 인식 결과보다 우선 적용한다.<br>• 사람이 보호 영역 안에 들어오면 Nav2 목표를 유지한 채 속도 명령을 0으로 제한한다.<br>• 사람이 경로에서 벗어나고 거리 센서가 안전한 상태이면 현재 위치에서 경로를 다시 확인한 후 이동한다.<br>• 사람을 피하기 위해 등록되지 않은 구역으로 임의 진입하지 않는다. |
| SR_24 | 입고, 출고 | Pinky | 물품 운반 기능 | High | UR_01, UR_02, UR_14 | Pinky는 물품을 실은 후 창고 선반 작업 위치, 포장대 또는 작업자 요청 전달 위치로 이동하고 도착·정차 상태를 전송한다.<br>• FMS가 지정한 목적지와 RMF/Fleet Adapter가 승인한 경로를 Nav2 목표로 사용한다.<br>• 이동 중에는 물품을 내리거나 자동 하차 동작을 수행하지 않는다.<br>• 목적지 허용 반경과 방향 조건을 만족한 뒤 정차한 경우에만 도착 상태를 전송한다.<br>• 목적지 공간이 예약 중이면 지정된 대기 노드에서 기다린다. |
| SR_25 | 입고, 출고 | Pinky | 대기·충전소 복귀 기능 | High | UR_11 | Pinky는 작업이 없거나 배터리 복귀 조건을 만족하면 FMS가 지정한 대기·충전소 위치로 이동한다.<br>• 복귀 위치는 RMF 지도에 등록된 대기 또는 충전 노드 중 FMS가 지정한다.<br>• 물품을 운반 중이면 예상 소비 전력으로 현재 전달 작업을 완료할 수 있는지 먼저 판단한다.<br>• 작업 완료가 가능하면 지정 위치까지 전달한 후 복귀하고, 불가능하면 안전 위치에서 작업을 보류한다.<br>• 복귀는 지정 위치 정차까지이며 충전 단자 접촉이나 충전 시작 제어는 수행하지 않는다. |
| SR_26 | 입고, 출고 | VLM+RL | 주행 예외 복구 기능 | Low | UR_08, UR_09 | VLM+RL은 Pinky가 Nav2의 기본 재계획으로 해결하지 못한 정지·통로 차단 상황에서 허용된 복구 행동 중 하나를 제안한다.<br>• Nav2의 기본 장애물 회피와 복구를 먼저 실행하고 반복 실패 또는 진행 정체가 확인된 경우에만 호출한다.<br>• VLM은 선택된 영상, YOLO 결과, Nav2 상태와 local costmap 요약을 받아 위험과 후보 행동을 구조화된 값으로 출력한다.<br>• RL은 정지 유지, 등록 대기 노드 이동, 허용 경로 재시도 같은 제한된 후보 중 하나만 선택한다.<br>• 후보 좌표는 지도·TF·costmap과 안전 영역 검사를 통과해야 실행할 수 있다.<br>• VLM+RL은 직접 속도 명령을 만들거나 Pinky의 안전 정지를 해제할 수 없다. |
| SR_27 | 입고, 출고 | FMS | 배터리 기반 작업 제한 기능 | Medium | UR_11 | FMS는 Pinky의 현재 배터리와 예상 이동 시간을 고려해 작업 완료와 대기·충전소 복귀가 가능한 작업만 배정한다.<br>• 배터리 상태를 정상, 작업 제한, 복귀 필요의 세 단계로 설정한다.<br>• 작업 제한 상태의 Pinky에는 현재 위치와 포장대에서 가까운 창고의 짧은 작업을 우선 배정한다.<br>• 예상 작업 소비량과 복귀 여유량을 합한 값보다 배터리가 적으면 새 작업을 배정하지 않는다.<br>• 단계별 기준값은 실제 Pinky 운행 시간을 측정한 후 설정 파일에서 조정한다. |
| SR_28 | 입고, 출고 | FMS | 로봇 준비상태 동기화 기능 | High | UR_06, UR_13 | FMS는 입고·출고 인수인계 작업에서 Pinky와 OMX가 모두 준비 완료 상태일 때만 물품 이동 동작을 시작시킨다.<br>• Pinky는 작업 위치 정차와 바구니 자세 확인 후 준비 완료를 전송한다.<br>• OMX는 대상 물품 파지 또는 입고 물품 접근 준비를 완료한 후 준비 완료를 전송한다.<br>• FMS는 같은 작업 ID에 대한 두 준비 상태를 모두 확인한 뒤 적재·하차 시작 명령을 전송한다.<br>• 한쪽이 준비되지 않았으면 준비된 로봇은 현재 안전 상태에서 기다리고 동작을 시작하지 않는다.<br>• 작업이 취소되거나 대상 로봇이 바뀌면 기존 준비 상태를 무효화한다. |
| SR_29 | 입고, 출고 | FMS | 작업 단계 통합 관리 기능 | High | UR_01, UR_02, UR_06, UR_15 | FMS는 입고·출고 작업을 명시적인 단계와 상태로 관리하고 완료 이벤트에 따라 다음 단계를 한 번만 실행한다.<br>• 작업 상태는 대기, 배정, 실행, 보류, 완료, 실패로 관리한다.<br>• 각 단계에는 작업 ID, 단계 ID, 실행 로봇, 시작·완료 시각과 결과를 기록한다.<br>• Pinky와 OMX의 완료 이벤트가 현재 작업 ID와 단계 ID에 일치할 때만 다음 단계로 진행한다.<br>• 같은 완료 이벤트를 다시 받아도 다음 단계를 중복 실행하지 않는다.<br>• 보류 후 재개할 때는 마지막 정상 완료 단계의 다음 단계부터 수행한다. |
| SR_30 | 입고, 출고 | FMS, Pinky, OMX | 통신 단절 안전정지·작업복구 기능 | Low | UR_12 | 확장 범위에서 FMS, Pinky 또는 OMX의 작업 통신이 끊기면 로봇은 현재 물품을 안전하게 유지하고 마지막 완료 단계부터 복구할 수 있도록 한다.<br>• Pinky는 안전하게 정지하고 OMX는 물품을 들고 있으면 등록된 안전 자세를 유지한다.<br>• 각 로봇은 작업 ID와 마지막 완료 단계만 로컬에 보관한다.<br>• 통신 복구 후 FMS의 작업 단계와 로봇의 마지막 완료 단계를 비교한다.<br>• 상태가 일치하면 다음 단계부터 재개하고 일치하지 않으면 작업을 보류한다.<br>• 이 기능은 기본 시연 범위에서 제외하고 핵심 작업 완료 후 구현한다. |
| SR_31 | 입고 | QR·ArUco | 입고 QR 인식 기능 | Low | UR_01 | 입고 QR 처리기는 입고 물품의 QR에서 물품 ID, 유통기한과 상온·냉장·냉동 보관 방법을 읽는다.<br>• QR 형식과 필수 필드를 사전에 정의하고 유효한 값만 입고 정보로 전달한다.<br>• 같은 QR을 여러 번 읽어도 동일 물품을 중복 등록하지 않도록 스캔 ID를 사용한다.<br>• QR을 읽지 못하면 정해진 횟수만 재촬영하고 계속 실패하면 수동 등록 대상으로 보류한다.<br>• 기본 시나리오는 QR 등록 완료 후 시작하며 이 기능은 시간 여유가 있을 때 OMX 또는 고정 카메라로 자동화한다. |
| SR_32 | 입고 | DB | 입고 물품 정보 자동 등록 기능 | Low | UR_01, UR_15 | DB는 정상적으로 해독된 입고 QR 정보를 입고 접수 상태로 등록한다.<br>• 물품 ID, 물품명, 유통기한, 보관 방법, 수량과 등록 시각을 저장한다.<br>• 동일 스캔 ID 또는 물품 ID의 중복 등록을 막는다.<br>• 등록 직후에는 선반 위치를 확정하지 않고 적재 예정 상태로 둔다.<br>• 기본 시나리오에서는 작업자가 등록을 완료한 것으로 가정하며 자동 등록은 확장 범위로 구현한다. |
| SR_33 | 입고 | FMS | 입고 정보 검수 기능 | Low | UR_01 | FMS는 QR로 등록한 입고 물품 정보와 사전에 입력된 입고 예정 정보를 비교하여 운영자의 검수를 보조한다.<br>• 물품 ID, 상품명과 수량을 비교 대상으로 사용한다.<br>• 정보가 일치하면 입고 작업 생성 대상으로 전달한다.<br>• 정보가 다르거나 예정 정보가 없으면 자동 수정하지 않고 검수 보류 상태로 표시한다.<br>• 이 기능 없이도 등록된 DB 정보를 기준으로 기본 입고 작업을 시작할 수 있다. |
| SR_34 | 입고 | FMS | QR 보관 방법 기반 구역 결정 기능 | High | UR_01 | FMS는 입고 QR에 기록된 보관 방법을 기준으로 물품의 상온·냉장·냉동 보관 구역을 결정한다.<br>• QR 값은 사전에 정의한 상온, 냉장, 냉동 코드 중 하나여야 한다.<br>• DB의 다른 물품 속성으로 보관 방법을 임의 추론하지 않는다.<br>• 보관 방법 코드가 없거나 허용 값과 다르면 구역을 배정하지 않고 입고 보류로 처리한다.<br>• 결정된 보관 구역은 선반·슬롯 검색 조건으로 사용한다. |
| SR_35 | 입고 | FMS | 입고 선반·슬롯 배정 기능 | High | UR_01 | FMS는 QR로 결정한 보관 구역 안에서 사용 가능한 선반·슬롯을 찾아 입고 물품에 예약한다.<br>• 사용 가능 상태인 슬롯 중 사전에 정한 선반·슬롯 순서가 빠른 위치를 우선 선택한다.<br>• 선택한 슬롯은 해당 입고 작업 ID로 예약하여 다른 작업이 동시에 배정받지 못하게 한다.<br>• 작업이 취소되거나 적재가 실패해 보류되면 슬롯 예약 상태를 갱신한다.<br>• 같은 보관 구역에 빈 슬롯이 없으면 물품을 입고 대기 위치에 두고 관제 UI에 공간 부족을 표시한다. |
| SR_36 | 입고 | FMS | 입고 전처리 자동화 기능 | Low | UR_01, UR_06 | FMS는 입고 QR 인식, DB 등록, 보관 구역·선반 결정 및 Pinky 작업 생성을 연속 처리한다.<br>• QR과 DB 등록이 완료된 물품만 자동 처리 대상으로 사용한다.<br>• 같은 창고로 이동할 물품은 하나의 작업 묶음으로 구성한다.<br>• 기본 작업 할당 규칙에 따라 입고 위치로 이동할 Pinky를 예약한다.<br>• 어느 단계에서든 입력 정보가 유효하지 않으면 이후 단계를 실행하지 않고 입고 보류 상태로 둔다.<br>• 이 기능은 QR·DB 등록 이후부터 시작하는 기본 입고 시나리오가 안정된 뒤 구현한다. |
| SR_37 | 입고 | OMX | 지정 선반 적재 기능 | High | UR_01, UR_13 | OMX는 Pinky에서 파지한 입고 물품을 FMS가 지정한 선반·슬롯에 적재한다.<br>• 선반 ArUco와 슬롯 좌표를 확인하고 물품 QR이 입고 작업 대상과 일치할 때만 적재한다.<br>• 물품을 파지한 뒤 등록된 안전 경로를 따라 선반의 pre-place 자세로 이동한다.<br>• 물품을 놓고 그리퍼를 연 뒤 선반 밖 안전 자세로 후퇴한 경우 적재 완료를 전송한다.<br>• 적재 동작을 완료하지 못하면 원본 재고를 변경하지 않고 재배치 절차를 수행한다.<br>• 설정 횟수 이후에도 실패하면 해당 물품만 적재 실패·보류로 보고한다. |
| SR_38 | 입고 | DB | 입고 위치·재고 갱신 기능 | High | UR_01, UR_15 | DB는 OMX의 지정 선반 적재 완료 결과를 받은 후 해당 물품의 재고와 위치를 확정한다.<br>• 물품 ID, 수량, 보관 구역, 선반·슬롯, 유통기한과 적재 완료 시각을 저장한다.<br>• 작업 중이거나 임시 선반에 있는 물품은 최종 입고 재고로 반영하지 않는다.<br>• 동일 작업 ID와 물품 ID의 완료 결과를 한 번만 반영한다.<br>• 주문 묶음의 일부 물품이 실패하면 성공한 물품만 입고 완료하고 실패 물품은 보류 상태로 유지한다. |
| SR_39 | 출고 | FMS | 주문 접수 기능 | High | UR_02 | FMS는 주문을 수신하면 재고와 보관 위치를 확인하고 실제 출고할 물품을 작업 대상으로 확정한다.<br>• 주문 ID, 물품별 요청 수량, 출고 방식, 목적지를 입력으로 사용한다.<br>• 재고가 충분하면 물품을 출고 작업에 예약하고 원본 재고 수량은 아직 변경하지 않는다.<br>• 재고가 부족하고 부분출고가 선택되었으면 가능한 물품만 확정한다.<br>• 재고가 부족하고 전체출고가 선택되었으면 주문을 취소하고 로봇 작업을 생성하지 않는다.<br>• 확정된 주문은 작업 단계 데이터에 대기 상태로 등록한다. |
| SR_40 | 출고 | FMS | 유통기한 기반 출고 물품 선정 기능 | High | UR_03 | FMS는 동일 상품의 재고가 여러 개이면 유통기한이 가장 빠른 물품부터 출고 대상으로 선정한다.<br>• 출고 가능한 상태이고 다른 작업에 예약되지 않은 물품만 후보로 사용한다.<br>• 유통기한을 오름차순으로 정렬하고 같은 날짜이면 선반·슬롯 순서가 빠른 물품을 선택한다.<br>• 선정한 물품 ID와 선반·슬롯을 주문 ID에 예약한다.<br>• 파지 전에 QR로 선정 물품과 실제 물품의 일치 여부를 다시 확인한다. |
| SR_41 | 출고 | FMS | 긴급 주문 우선 처리 기능 | Medium | UR_04 | FMS는 긴급 표시가 있는 출고 주문을 일반 주문보다 먼저 스케줄링한다.<br>• 진행 중인 안전한 파지·적재·운반 작업을 강제로 중단하지 않고 다음 배정 순서부터 긴급 주문을 우선한다.<br>• 긴급 주문끼리는 유통기한이 빠른 물품을 먼저 처리한다.<br>• 같은 우선순위와 유통기한이면 먼저 접수된 주문을 우선한다.<br>• 긴급 표시와 우선순위 변경은 작업 이력에 기록한다. |
| SR_42 | 출고 | FMS | 작업자 요청 우선 처리 기능 | Low | UR_04, UR_05 | FMS는 작업자 간 전달, 누락 물품 전달 또는 우선 주문 요청을 일반 대기 작업보다 먼저 배정할 수 있도록 한다.<br>• 요청에는 요청 유형, 물품, 수량, 출발 위치와 전달 위치를 포함한다.<br>• 진행 중인 작업을 중단하지 않고 다음 작업 배정 시 우선순위를 적용한다.<br>• 같은 작업자 요청끼리는 접수 시각이 빠른 요청을 우선한다.<br>• 이 기능은 기본 입고·출고 시나리오 완료 후 구현하는 확장 기능으로 한다. |
| SR_43 | 출고 | FMS, RMF/Fleet Adapter | 포장대 사용 상태 관리 기능 | Medium | UR_14 | FMS와 RMF/Fleet Adapter는 포장대를 예약 가능한 작업 공간으로 관리하여 한 시각에 하나의 주문만 사용하도록 한다.<br>• 포장대 상태는 사용 가능, 예약, 사용 중으로 관리한다.<br>• 출고 작업에 포장대를 배정하면 주문 ID와 Pinky ID로 예약한다.<br>• Pinky가 포장대에 도착하면 사용 중으로 변경하고 인계 완료 또는 작업 취소 후 예약을 해제한다.<br>• 먼저 예약된 포장대를 다른 Pinky가 사용할 수 없도록 RMF 진입 순서를 조정한다. |
| SR_44 | 출고 | YOLO | 포장대 작업자 부재 감지 기능 | Medium | UR_14 | YOLO는 포장대 고정 카메라에서 작업자 존재 여부를 감지하여 FMS의 포장대 선택에 제공한다.<br>• 카메라별 포장대 작업 영역을 ROI로 등록하고 사람 검출 결과가 ROI와 겹치는지 판단한다.<br>• 설정된 연속 프레임 동안 사람이 보이면 작업자 있음, 보이지 않으면 작업자 부재로 전달한다.<br>• 포장대 물품이나 다른 구역의 사람은 작업자로 계산하지 않는다.<br>• 작업자 부재 결과는 포장대 예약 상태를 직접 변경하지 않고 FMS가 대기·이동 결정에 사용한다. |
| SR_45 | 출고 | Pinky, FMS | 포장대 대기·재배정 기능 | Medium | UR_14 | Pinky와 FMS는 배정된 포장대에 작업자가 없으면 사용 가능한 다른 포장대로 이동하거나 지정 포장대에서 대기한다.<br>• 작업자가 있는 사용 가능한 포장대가 있으면 FMS가 기존 예약을 해제하고 새 포장대를 예약한다.<br>• 모든 포장대에 작업자가 없으면 처음 배정된 포장대 또는 가까운 대기 노드로 이동한다.<br>• FMS는 관제 UI에 작업자 배치 필요 상태를 표시한다.<br>• 작업자가 확인되면 같은 주문과 물품 상태를 유지한 채 인계를 재개한다. |
| SR_46 | 출고 | OMX | Pinky 물품 적재 기능 | High | UR_02, UR_13 | OMX는 Pinky와 OMX의 준비 완료가 확인되면 출고 물품을 Pinky 바구니의 등록된 적재 위치에 놓는다.<br>• 물품이 1개이면 사전 파지 상태에서 바로 적재하고 여러 개이면 임시 선반의 물품을 하나씩 적재한다.<br>• 바구니 네 모서리 기반 보정 좌표와 사전 등록된 빈 적재 위치를 사용한다.<br>• 물품 QR과 주문의 예약 물품 ID가 일치할 때만 적재한다.<br>• 물품을 놓고 그리퍼를 연 뒤 바구니 밖 안전 자세로 후퇴한 경우 적재 완료를 전송한다.<br>• 적재 동작에 실패하면 해당 물품을 보류하고 다음 물품의 처리 가능 여부를 FMS에 전달한다. |
| SR_47 | 출고 | OMX | 적재 인수인계 확인 기능 | High | UR_13, UR_15 | OMX는 Pinky 적재 동작이 끝난 후 실제 실행 결과와 물품 목록을 확인하여 FMS에 인수인계 완료를 전송한다.<br>• 그리퍼 열림, 적재 자세 도달과 안전 자세 후퇴가 모두 완료되어야 한다.<br>• 완료 메시지에는 작업 ID, 주문 ID, Pinky ID와 적재한 물품 ID를 포함한다.<br>• FMS는 예정 물품 목록과 완료 메시지의 물품 목록이 일치할 때만 운반 단계를 시작한다.<br>• 물품 목록이 다르면 Pinky를 출발시키지 않고 적재 확인 보류 상태로 둔다. |
| SR_48 | 출고 | Pinky | 포장대·작업자 전달 위치 운반 기능 | High | UR_02, UR_14 | Pinky는 출고 물품을 배정된 포장대 또는 작업자 요청 전달 위치까지 운반한다.<br>• OMX 적재 완료와 FMS의 운반 시작 승인을 받은 후 출발한다.<br>• RMF/Fleet Adapter가 승인한 경로를 따라 이동하고 Nav2가 로컬 장애물을 회피한다.<br>• 목적지에 도착하면 지정 방향으로 정차한 상태를 유지한다.<br>• Pinky는 물품을 자동 하차하지 않으며 이후 처리는 작업자 또는 OMX가 수행한다. |
| SR_49 | 출고 | Pinky | 포장 준비완료 표시 기능 | Medium | UR_14 | Pinky는 포장대 또는 작업자 전달 위치에 정차한 뒤 물품 인계 대기 상태를 LED 또는 화면으로 표시한다.<br>• 이동 중과 인계 대기 상태를 서로 다른 표시로 구분한다.<br>• 사람 위급상황의 빨간 LED와 부저가 일반 인계 표시보다 우선한다.<br>• 인계 완료 또는 작업 취소 후 일반 대기 표시로 복귀한다.<br>• 표시 상태는 Pinky의 작업 상태와 함께 FMS에 전송한다. |
| SR_50 | 출고 | 관제 UI, DB | 전달 완료 입력·기록 기능 | High | UR_14, UR_15 | 관제 UI는 작업자 또는 운영자가 주문 물품의 전달 완료를 입력하면 DB에 주문과 작업 결과를 기록한다.<br>• 완료 입력에는 주문 ID, Pinky ID, 전달 위치와 입력 시각을 포함한다.<br>• 이미 완료된 주문에 같은 입력을 반복해도 결과를 중복 반영하지 않는다.<br>• 전달 완료 입력 전에는 Pinky를 인계 대기 상태로 유지한다.<br>• 일부 물품만 전달되었으면 완료된 물품과 보류 물품을 구분하여 입력한다. |
| SR_51 | 출고 | FMS, DB | 출고 결과 확정 기능 | High | UR_02, UR_15 | FMS와 DB는 전달 완료 결과를 기준으로 출고 성공, 부분출고, 피킹 실패 또는 적재 실패 상태를 확정한다.<br>• 성공적으로 전달된 물품만 원본 재고 수량에서 차감하고 출고 이력에 추가한다.<br>• 피킹·적재 실패 또는 보류 물품은 원본 재고 위치와 수량을 유지한다.<br>• 주문 ID, 물품별 결과, 사용 로봇, 이동 경로와 단계별 작업 시간을 기록한다.<br>• 주문의 모든 물품 결과가 확정된 후 주문 전체 상태를 완료, 부분완료 또는 실패로 갱신한다.<br>• 결과 확정 후 Pinky에 대기·충전소 복귀 작업을 배정한다. |
| SR_52 | 비상상황 | YOLO | 사람 위급상황 감지 기능 | High | UR_10 | YOLO는 Pinky 또는 고정 카메라 영상에서 사람이 쓰러진 것으로 의심되는 자세와 움직임 정지를 감지한다.<br>• 사람 검출 후 서 있거나 걷는 자세와 다른 낮은 자세를 일정 프레임 동안 추적한다.<br>• 비정상 자세에서 설정된 시간 동안 움직임이 없을 때만 쓰러짐 의심 이벤트를 생성한다.<br>• 이벤트에는 카메라 ID, 저장 구역, 감지 위치, 감지 시각과 추적 ID를 포함한다.<br>• 사람이 정상적으로 움직이거나 자세를 회복하면 일반 감시 상태를 유지한다.<br>• 화재, 정전과 설비 고장은 이 비상상황 감지 범위에 포함하지 않는다. |
| SR_53 | 비상상황 | 관제 UI | 사람 위급상황 알림 기능 | High | UR_10 | 관제 UI는 사람 쓰러짐 의심 이벤트를 수신하면 발생 위치와 영상을 운영자가 즉시 확인할 수 있도록 경고한다.<br>• 창고 지도에 발생 구역과 카메라 위치를 강조하고 감지 시각을 표시한다.<br>• 해당 카메라의 실시간 영상과 감지 직전 녹화 구간으로 이동할 수 있도록 한다.<br>• 경고는 일반 작업 오류보다 높은 우선순위로 표시하고 운영자가 확인한 시각을 기록한다.<br>• 비상 해제 승인 전까지 경고와 해당 구역 차단 상태를 유지한다. |
| SR_54 | 비상상황 | FMS, RMF/Fleet Adapter, Pinky | 비상 대응 구역·로봇 동작 제어 기능 | High | UR_09, UR_10 | FMS와 RMF/Fleet Adapter는 사람 위급상황 발생 위치를 비상 대응 구역으로 설정하고 주변 Pinky의 진입과 작업을 제한한다.<br>• 감지한 Pinky는 안전거리를 유지해 정지하고 빨간 LED와 부저를 작동한다.<br>• 고정 카메라가 감지했으면 FMS는 발생 구역 주변 Pinky의 접근을 금지한다.<br>• RMF/Fleet Adapter는 해당 구역을 임시 진입 금지 영역으로 적용하고 다른 Pinky의 경로를 우회시킨다.<br>• 비상 대응 구역 안에 있는 Pinky는 정지하고 새로운 작업 목표를 실행하지 않는다.<br>• 비상 해제 승인 전까지 진입 금지와 비상 표시를 유지한다. |
| SR_55 | 비상상황 | FMS | 비상 영향 작업 보류·재할당 기능 | High | UR_10, UR_12 | FMS는 사람 위급상황으로 중단된 작업의 마지막 안전 완료 단계와 물품 상태를 기록하고 이어서 수행 가능한 작업만 재할당한다.<br>• 영향받은 작업의 주문 ID, 물품 위치, 파지·적재 상태와 마지막 완료 단계를 기록한다.<br>• 물품 상태가 확인되고 다른 Pinky가 이어받을 수 있으면 마지막 완료 단계의 다음 단계부터 재할당한다.<br>• 물품이 로봇에 실려 있거나 파지 중이어서 상태 확인이 필요하면 관리자 개입 필요 상태로 보류한다.<br>• 완료된 파지·적재·운반 단계를 반복하지 않는다.<br>• 비상 대응 구역 안의 로봇에는 새 작업을 배정하지 않는다. |
| SR_56 | 비상상황 | 관제 UI, FMS | 비상 대응 해제 승인 기능 | High | UR_07, UR_10 | 관제 UI는 지정 관리자가 현장 대응 완료를 확인한 뒤 사람 위급상황 대응 모드 해제를 승인할 수 있도록 한다.<br>• 해제 요청에는 비상 이벤트 ID와 승인 시각을 기록한다.<br>• 승인 전에는 발생 구역 차단, 로봇 정지와 비상 표시를 유지한다.<br>• 해제 승인 시 FMS는 비상 구역을 해제하지만 중단된 작업을 즉시 재개하지 않는다.<br>• 영향받은 로봇은 먼저 대기·충전소 복귀와 상태 점검 절차로 전환한다. |
| SR_57 | 비상상황 | Pinky, FMS | 비상 해제 후 복귀·재투입 기능 | High | UR_10, UR_12 | 사람 위급상황이 해제되면 영향받은 Pinky는 지정 대기·충전소로 복귀하고 FMS는 상태 점검을 통과한 로봇만 새 작업에 투입한다.<br>• 비상 해제 후 영향받은 Pinky는 기존 목적지가 아니라 지정 대기·충전소 위치로 이동한다.<br>• 복귀 후 물품 적재 상태, 통신, 배터리와 필수 센서 상태를 점검한다.<br>• 모든 점검 항목이 정상인 Pinky만 작업 가능 상태로 변경한다.<br>• 물품이 남아 있거나 점검에 실패한 Pinky는 작업 불가 또는 관리자 확인 필요 상태로 유지한다.<br>• 정상 로봇도 중단 작업을 자동 재개하지 않고 FMS의 새 작업 할당을 기다린다. |

## EXPLAINCODE: 기능별 시작 파일과 workflow

아래 표는 구현을 읽거나 수정할 때 **가장 먼저 열 파일**과 다음 흐름을 지정한다. `→`는
호출/상태 전달 순서이며, 실제 장비 adapter 또는 runtime 검증이 필요한 지점은 마지막에 적었다.
Low 항목은 현재 목표에서 제외하므로 구현 시작 파일을 만들지 않았다.

| SR | 첫 시작 파일 | 코드 workflow / 확인할 테스트 |
| --- | --- | --- |
| SR_01 | `control_tower/gateway/http_server.py` | `http_server.py → operations_feed.py → ui/operations/index.html → operations.js`; `test_operations_http_server.py` |
| SR_02 | `control_tower/task_manager/lifecycle.py` | `lifecycle.py → gateway/authorization.py → audit_repository.py`; `test_task_lifecycle.py` |
| SR_03 | `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/status_node.py` | `status_node.py → status.py → gateway_node.py`; OMX는 `gateway/omx_status.py`; `test_omx_status.py` |
| SR_04 | `vision_system/recording_server/recorder.py` | `recorder.py → catalog.py → pick_failure_report.py`; `test_recorder.py`, `test_recording_catalog.py` |
| SR_05 | `vision_system/training/dataset_policy.py` | `dataset_policy.py → vision_perception/augmentation/generate_augmentation_candidates.py`; `test_dataset_policy.py` |
| SR_06 | `control_tower/fleet_manager/inventory_workflow.py` | `reserve_* → OMX/Pinky 완료 event → finalize_inbound/outbound`; `test_inventory_workflow.py` |
| SR_07 | `control_tower/fleet_manager/dispatch_workflow.py` | `dispatch_workflow.py → Pinky eta.py → OMX schedule`; `test_dispatch_workflow.py`, `test_eta_policy.py` |
| SR_08 | `control_tower/fleet_manager/dispatch_workflow.py` | `reassign() → completed_steps → 다음 stage`; `test_dispatch_workflow.py` |
| SR_09 | `control_tower/rmf_adapter/traffic_reservation.py` | `traffic_reservation.py → waiting node → RMF runtime adapter`; `test_traffic_reservation.py` |
| SR_10 | 확장 범위 (Low) | 주문 다중 Pinky 분할 구현 없음 |
| SR_11 | `control_tower/task_manager/omx_workflow.py` | `marker policy → omx_workflow.py → gateway/omx_protocol.py → OMX/MoveIt adapter`; `test_omx_workflow.py` |
| SR_12 | 확장 범위 (Low) | 공통 물품 YOLO 좌표 보조 구현 없음 |
| SR_13 | `control_tower/task_manager/omx_workflow.py` | `pick_result → retry offset → ITEM_HELD`; `test_omx_workflow.py` |
| SR_14 | `vision_system/object_worker/basket_correction.py` | `YOLO OBB corners → bounded correction → REQUEST_PINKY_REPOSITION`; `test_basket_correction.py` |
| SR_15 | `control_tower/task_manager/omx_workflow.py` | `temporary slot reserve → QR 재확인 → release`; `test_omx_workflow.py` |
| SR_16 | `control_tower/task_manager/omx_workflow.py` | `person ROI event → PAUSED_FOR_PERSON → safe resume`; `test_omx_workflow.py` |
| SR_17 | `vision_system/marker_worker/policy.py` | `QR order/item 확인 → pick authorization → OMX`; `test_marker_policy.py` |
| SR_18 | `vision_system/marker_worker/policy.py` | `ArUco marker ID/pose → tolerance gate → OMX`; `test_marker_policy.py` |
| SR_19 | `vision_system/person_worker/policy.py` | `detector/tracker observation → ROI 연속 frame → OMX pause`; 명시 ROI 테스트 |
| SR_20 | `vision_system/person_worker/policy.py` | `Pinky camera person observation → ROI/track event → Pinky safety 입력`; 명시 ROI 테스트 |
| SR_21 | `control_tower/task_manager/pick_failure_report.py` | `OMX final failure → catalog evidence lookup → UI hold`; `test_pick_failure_report.py` |
| SR_22 | 확장 범위 (Low) | IMU/odometry 미끄럼 판단 구현 없음 |
| SR_23 | `trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/safety_supervisor_node.py` | `/cmd_vel_nav,/scan,/range,person → policy.py → /cmd_vel`; `test_pinky_sr_policies.py` |
| SR_24 | `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py` | `ExecuteTransport → NavigateToPose → arrival.py → WAITING_HANDOVER`; `test_pinky_sr_policies.py` |
| SR_25 | `control_tower/fleet_manager/battery_policy.py` | `battery policy → return command → Pinky workflow.py`; `test_battery_policy.py` |
| SR_26 | 확장 범위 (Low) | VLM+RL 예외 복구는 설계 문서만 있음 |
| SR_27 | `control_tower/fleet_manager/battery_policy.py` | `status() / can_accept_new_job() → dispatch`; `test_battery_policy.py` |
| SR_28 | `control_tower/task_manager/handover_gate.py` | `Pinky ready + OMX ready → allow load/unload`; `test_handover_gate.py` |
| SR_29 | `control_tower/task_manager/stage_engine.py` | `matching completion event → next stage once → hold/resume`; `test_stage_engine.py` |
| SR_30 | 확장 범위 (Low) | 통신 단절 복구는 기본 시연 범위 제외 |
| SR_31 | 확장 범위 (Low) | 입고 QR 자동 스캔/등록 구현 없음 |
| SR_32 | 확장 범위 (Low) | 입고 QR DB 자동 등록 구현 없음 |
| SR_33 | 확장 범위 (Low) | 입고 예정 정보 자동 검수 구현 없음 |
| SR_34 | `control_tower/fleet_manager/storage_assignment.py` | `QR storage code → zone assignment → inbound hold`; `test_storage_assignment.py` |
| SR_35 | `control_tower/fleet_manager/inventory_workflow.py` | `zone → first empty slot reserve → finalize/cancel`; `test_inventory_workflow.py` |
| SR_36 | 확장 범위 (Low) | 입고 전처리 자동 orchestration 구현 없음 |
| SR_37 | `control_tower/task_manager/omx_workflow.py` | `marker/QR 승인 → place shelf result → inbound finalize`; `test_omx_workflow.py` |
| SR_38 | `control_tower/fleet_manager/inventory_workflow.py` | `OMX shelf complete → finalize_inbound once → lot/location`; `test_inventory_workflow.py` |
| SR_39 | `control_tower/fleet_manager/order_intake.py` | `requested/available → full/partial/cancel → reserve_outbound`; `test_order_intake.py` |
| SR_40 | `control_tower/fleet_manager/inventory_workflow.py` | `available lot → expiry/shelf/slot FEFO sort → reservation`; `test_inventory_workflow.py` |
| SR_41 | `control_tower/fleet_manager/dispatch_workflow.py` | `priority → request time → next available robot`; `test_dispatch_workflow.py` |
| SR_42 | 확장 범위 (Low) | 작업자 요청 우선 queue 구현 없음 |
| SR_43 | `control_tower/fleet_manager/packing_station.py` | `AVAILABLE → RESERVED → IN_USE → release`; `test_packing_station_policy.py` |
| SR_44 | `vision_system/person_worker/policy.py` | `packing ROI → consecutive frames → worker_present input`; 명시 ROI 테스트 |
| SR_45 | `control_tower/fleet_manager/packing_station.py` | `worker absence → reassign/wait decision → Pinky workflow.reassign`; `test_packing_station_policy.py` |
| SR_46 | `control_tower/task_manager/omx_workflow.py` | `ready gate → basket correction/QR → load complete`; `test_omx_workflow.py` |
| SR_47 | `control_tower/gateway/omx_protocol.py` | `omx_result ID 검증 → handover gate → transport allow`; `test_omx_protocol.py` |
| SR_48 | `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/fleet_node.py` | `load approval → Nav2 transport → stationary → handover wait`; `test_pinky_sr_policies.py` |
| SR_49 | `trihouse_pinky/trihouse_pinky_io/trihouse_pinky_io/destination_display.py` | `FMS destination code → LCD label`; 위험 LED는 `indicator.py`; `test_pinky_sr_policies.py` |
| SR_50 | `control_tower/task_manager/outbound_result.py` | `operator item result → order outcome → inventory finalize`; `test_outbound_result.py` |
| SR_51 | `control_tower/fleet_manager/inventory_workflow.py` | `delivered lots only → finalize_outbound once → return assignment`; `test_outbound_result.py` |
| SR_52 | `docs/scenario/sr52-fall-detection-research-plan.md` | 조사 계획: tracker/pose → temporal verifier → operator approval. **코드 작성 보류** |
| SR_53 | `control_tower/gateway/operations_feed.py` | `incident open → priority event → UI alert`; `test_operations_feed.py` |
| SR_54 | `control_tower/task_manager/emergency_workflow.py` | `incident polygon → deny target → Pinky emergency/keep-out`; `test_emergency_workflow.py` |
| SR_55 | `control_tower/task_manager/lifecycle.py` | `emergency hold → cargo/state 확인 → reassign or admin intervention`; `test_task_lifecycle.py` |
| SR_56 | `control_tower/gateway/authorization.py` | `ADMIN release → audit_repository approval → emergency workflow`; `test_authorization.py` |
| SR_57 | `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/recovery_health.py` | `return waypoint → health telemetry check → IDLE or UNAVAILABLE`; `test_pinky_sr_policies.py` |

전체 명시 테스트 명령, 실제 장비에서 이어 확인할 workflow, 파일별 한국어 주석의 읽는 순서는
`docs/setup/trihouse-code-guide.md`를 따른다.

## 참고 자료

- `docs/scenario/입고_workflow.pdf`
- `docs/scenario/출고_workflow.pdf`의 `출고 v2`
- `docs/scenario/비상상황_workflow.pdf` 중 사람 위급상황 흐름
- `docs/scenario/User Requirements.md`
- `docs/setup/pinky-control-tower-vision-implementation-checklist.html`
- `docs/setup/2026-08-06-pinky-vision-streaming-design.md`
- `docs/setup/system_environment/2026-08-05-robot-arm-imitation-safe-operation-draft.md`
- `docs/vlm_rl/2026-08-07-vlm-rl-recovery-architecture-design.md`
- <https://github.com/open-rmf/rmf>
- <https://pinklab.art/pinky-pro/>
- <https://docs.robotis.com/docs/systems/omx/introduction/>
- <https://github.com/ROBOTIS-GIT/cyclo_intelligence>
