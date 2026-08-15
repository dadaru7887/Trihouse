/// RoboSapiens 물류 플랫폼 공용 계층 — **플랫폼 중립**.
///
/// 도메인 모델과 저장소 *인터페이스*만 담는다. 웹을 포함한 모든 타깃에서
/// 임포트할 수 있다. SQLite 구현은 `dart:ffi`가 필요하므로
/// [robo_core_sqlite.dart]로 분리했다.
library;

export 'data/memory_store.dart';
export 'data/repositories.dart';
export 'models/enums.dart';
export 'models/event.dart';
export 'models/inventory.dart';
export 'models/robot.dart';
export 'models/task.dart';
export 'models/warehouse.dart';
