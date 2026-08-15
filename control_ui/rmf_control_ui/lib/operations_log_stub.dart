/// 웹 빌드용 대체 구현. 브라우저에서는 `mysql` 클라이언트를 실행할 수 없다.
/// 운영 분석은 기록이 MySQL 에만 있으므로 웹에서는 빈 화면이 된다.
library;

import 'operations_log_models.dart';

Future<List<OperationMonth>> loadOperationMonths() async => const [];

Future<List<OperationDay>> loadOperationDays(int year, int month) async =>
    const [];

Future<List<OperationEntry>> loadOperationEntries(DateTime day) async =>
    const [];

Future<void> recordMapProjectChanges(
  String mapName,
  List<MapProjectChange> changes,
) async {}
