import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/task_store.dart';

void main() {
  final enabled = Platform.environment['RUN_MYSQL_READ_TEST'] == '1';

  test(
    'MySQL 미처리 주문을 자동 분류용 JSON으로 조회한다',
    () async {
      final orders = jsonDecode(await loadPendingOrders());
      expect(orders, isA<List<dynamic>>());
    },
    skip: enabled ? false : 'MySQL 읽기 테스트 환경이 설정되지 않았습니다.',
  );
}
