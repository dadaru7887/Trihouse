/// 3온도 물류센터 관제 시스템에서 공통으로 쓰는 열거형 정의.
library;

/// 3온도대(상온/냉장/냉동) 구획.
enum TempZone {
  ambient('상온', 'A', 15.0, 25.0),
  chilled('냉장', 'C', 0.0, 5.0),
  frozen('냉동', 'F', -25.0, -18.0);

  const TempZone(this.label, this.code, this.minC, this.maxC);

  final String label;
  final String code;
  final double minC;
  final double maxC;

  double get midC => (minC + maxC) / 2;
}

/// 로봇의 실시간 상태. 다른 로봇 및 관제 시스템에 공유되는 값이다.
enum RobotState {
  idle('대기', false),
  moving('주행', true),
  picking('집품', true),
  placing('하역', true),
  handover('작업자 인계', true),
  loading('적재 대기', true),
  yielding('보행자 양보', true),
  blocked('자원 대기', true),
  returning('충전소 복귀', false),
  charging('충전', false),
  powerSaving('절전', false),
  error('오류', false),
  estop('비상정지', false),
  standby('예비 대기', false);

  const RobotState(this.label, this.isWorking);

  final String label;
  final bool isWorking;
}

/// 태스크 종류.
enum TaskType {
  inbound('입고'),
  outbound('출고'),
  handover('작업자 전달'),
  relay('작업자 간 전달'),
  replenish('보충'),
  disposal('유통기한 회수');

  const TaskType(this.label);

  final String label;
}

/// 태스크 수명주기 상태.
enum TaskState {
  pending('할당 대기'),
  claimed('점유'),
  inProgress('진행 중'),
  blocked('보류'),
  done('완료'),
  failed('실패'),
  cancelled('취소');

  const TaskState(this.label);

  final String label;
}

/// 주문/태스크 긴급도.
enum Urgency {
  critical('긴급', 3),
  high('높음', 2),
  normal('보통', 1),
  low('낮음', 0);

  const Urgency(this.label, this.weight);

  final String label;
  final int weight;
}

/// 이벤트 심각도. 상태 색상은 이 값에만 대응한다.
enum Severity {
  info('정보'),
  warning('주의'),
  serious('경고'),
  critical('위험');

  const Severity(this.label);

  final String label;
}

/// 안전 상황 종류.
enum IncidentType {
  fire('화재', Severity.critical),
  powerCut('전원 차단', Severity.serious),
  workerEmergency('작업자 위급', Severity.critical),
  eStop('전체 비상정지', Severity.critical),
  spill('바닥 오염·결빙', Severity.warning);

  const IncidentType(this.label, this.severity);

  final String label;
  final Severity severity;
}

/// 주문 상태.
enum OrderState {
  open('접수'),
  working('처리 중'),
  fulfilled('완료'),
  partial('부분 완료'),
  failed('실패');

  const OrderState(this.label);

  final String label;
}
