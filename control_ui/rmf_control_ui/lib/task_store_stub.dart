/// 웹 빌드용 대체 구현. 브라우저에서는 `mysql` 클라이언트를 실행할 수 없다.
library;

Future<String?> loadSavedTasks(String mapName) async => null;

Future<void> saveTasks(String mapName, String contents) async {}

Future<String> loadPendingOrders() async => '[]';

Future<void> markOrderDispatched(String orderId, String taskId) async {}
