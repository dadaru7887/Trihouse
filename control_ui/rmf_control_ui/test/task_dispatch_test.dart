import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/task_dispatch.dart';

/// 로봇이 모자라 대기가 쌓였을 때 어느 작업을 먼저 내보내는지 정한다.
///
/// 화면 목록은 새 작업이 위로 오도록 앞에 끼워 넣기 때문에, 그 순서를 그대로
/// 쓰면 나중에 들어온 주문이 먼저 처리된다. 실제로 그렇게 동작하고 있었다.
void main() {
  ({String id, DateTime at}) task(String id, int minute) =>
      (id: id, at: DateTime(2026, 8, 8, 10, minute));

  List<String> order(List<({String id, DateTime at})> tasks) => [
    for (final entry in dispatchOrder(tasks, (task) => task.at)) entry.id,
  ];

  test('먼저 만들어진 작업이 먼저 나간다', () {
    expect(order([task('A', 1), task('B', 2), task('C', 3)]), ['A', 'B', 'C']);
  });

  test('목록이 새 작업부터 담겨 있어도 생성 순서대로 나간다', () {
    // _mockTasks 는 insert(0, …) 로 쌓이므로 최신이 앞이다. 이 순서를 그대로
    // 배차하던 것이 이번 문제였다.
    expect(order([task('C', 3), task('B', 2), task('A', 1)]), ['A', 'B', 'C']);
  });

  test('생성 시각이 같으면 넘겨받은 순서를 지킨다', () {
    final same = [task('먼저', 5), task('나중', 5)];
    expect(order(same), ['먼저', '나중']);
    expect(order(same.reversed.toList()), ['나중', '먼저']);
  });

  test('빈 목록과 한 건은 그대로 둔다', () {
    expect(order([]), isEmpty);
    expect(order([task('혼자', 7)]), ['혼자']);
  });

  test('원본 목록은 건드리지 않는다', () {
    final original = [task('C', 3), task('A', 1)];
    final copy = [...original];
    dispatchOrder(original, (task) => task.at);
    expect(original, copy, reason: '화면 표시 순서가 배차 때문에 바뀌면 안 된다');
  });

  group('긴급도 우선', () {
    ({String id, DateTime at, int weight}) urgent(
      String id,
      int minute,
      int weight,
    ) => (id: id, at: DateTime(2026, 8, 8, 10, minute), weight: weight);

    List<String> byUrgency(
      List<({String id, DateTime at, int weight})> tasks,
    ) => [
      for (final entry in dispatchOrder(
        tasks,
        (task) => task.at,
        priority: (task) => task.weight,
      ))
        entry.id,
    ];

    test('나중에 들어온 긴급 주문이 먼저 나간다', () {
      expect(byUrgency([urgent('보통-먼저', 1, 1), urgent('긴급-나중', 9, 3)]), [
        '긴급-나중',
        '보통-먼저',
      ]);
    });

    test('같은 긴급도끼리는 오래 기다린 쪽이 먼저다', () {
      expect(
        byUrgency([
          urgent('높음-나중', 8, 2),
          urgent('높음-먼저', 2, 2),
          urgent('긴급', 5, 3),
          urgent('낮음', 1, 0),
        ]),
        ['긴급', '높음-먼저', '높음-나중', '낮음'],
      );
    });

    test('priority 를 넘기지 않으면 순수 선입선출이다', () {
      expect(
        [
          for (final entry in dispatchOrder([
            urgent('긴급', 9, 3),
            urgent('보통', 1, 1),
          ], (task) => task.at))
            entry.id,
        ],
        ['보통', '긴급'],
      );
    });
  });
}
