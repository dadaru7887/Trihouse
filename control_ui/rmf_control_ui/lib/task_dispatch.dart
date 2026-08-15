/// 대기 중인 작업을 어떤 순서로 내보낼지 정한다.
library;

/// 배차 순서를 세운다. 긴급도가 높은 것이 먼저, 같으면 먼저 만들어진 것이 먼저.
///
/// 화면의 작업 목록은 새 작업이 위로 오도록 앞에 끼워 넣는다(`insert(0, …)`).
/// 그 순서를 그대로 배차에 쓰면 나중에 들어온 주문이 먼저 처리되고 기다리던
/// 주문이 뒤로 밀린다. 목록을 보여 주는 순서와 일을 내보내는 순서는 별개다.
///
/// [priority] 는 클수록 먼저 나간다. 넘기지 않으면 순수 선입선출이다. 같은
/// 긴급도끼리는 오래 기다린 쪽이 먼저 나가므로, 긴급 주문이 계속 들어와도 보통
/// 주문이 영원히 밀리는 일은 없다 — 다만 긴급이 끊기기 전까지는 뒤로 간다.
///
/// 생성 시각까지 같으면 넘겨받은 순서를 지킨다. `List.sort` 는 안정 정렬이
/// 아니라 같은 값끼리 뒤바뀔 수 있으므로 원래 자리를 함께 견준다.
List<T> dispatchOrder<T>(
  Iterable<T> tasks,
  DateTime Function(T task) createdAt, {
  int Function(T task)? priority,
}) {
  final indexed = tasks.toList().asMap().entries.toList()
    ..sort((a, b) {
      if (priority != null) {
        final byPriority = priority(b.value).compareTo(priority(a.value));
        if (byPriority != 0) return byPriority;
      }
      final byTime = createdAt(a.value).compareTo(createdAt(b.value));
      return byTime != 0 ? byTime : a.key.compareTo(b.key);
    });
  return [for (final entry in indexed) entry.value];
}
