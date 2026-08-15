import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/map_project_store.dart';
import 'package:rmf_control_ui/operations_log.dart';
import 'package:rmf_control_ui/operations_log_models.dart';

/// 운영 분석이 읽는 기록.
///
/// 설정을 언제 바꿨는지와 그날 무슨 일이 있었는지를 같은 시간축에 놓는다.
/// 어제까지 되던 것이 오늘 안 되면 그 사이에 무엇을 바꿨는지 함께 봐야 한다.
void main() {
  group('기록 갈래', () {
    test('모르는 값은 사건으로 읽는다', () {
      // 나중에 갈래가 늘어도 화면이 죽지 않아야 한다.
      expect(OperationLogKind.parse('setting'), OperationLogKind.setting);
      expect(OperationLogKind.parse('task'), OperationLogKind.task);
      expect(OperationLogKind.parse('무엇'), OperationLogKind.event);
    });

    test('갈래마다 이름이 다르다', () {
      final labels = OperationLogKind.values.map((k) => k.label).toSet();
      expect(labels.length, OperationLogKind.values.length);
    });
  });

  group('제목 다듬기', () {
    test('설정 기록을 사람 말로 바꾼다', () {
      // 표에 든 값을 그대로 보여 주면 robot·added·PK-01 처럼 기계 말이 된다.
      expect(
        formatEntryTitle(OperationLogKind.setting, 'robot\tadded\tPK-01'),
        '로봇 등록 추가 · PK-01',
      );
      expect(
        formatEntryTitle(OperationLogKind.setting, 'fleet\tchanged\tpinky'),
        '플릿 설정 변경 · pinky',
      );
      expect(
        formatEntryTitle(
          OperationLogKind.setting,
          'file\tremoved\trobots/PK-01/robot.yaml',
        ),
        '설정 파일 삭제 · robots/PK-01/robot.yaml',
      );
    });

    test('운영 기록은 건드리지 않는다', () {
      expect(
        formatEntryTitle(OperationLogKind.task, 'TSK-0001 멸균우유 출고'),
        'TSK-0001 멸균우유 출고',
      );
    });

    test('모양이 어긋난 값도 그대로 보여 준다', () {
      // 못 알아본다고 빈칸으로 두면 무슨 기록인지 알 수 없게 된다.
      expect(formatEntryTitle(OperationLogKind.setting, '깨진값'), '깨진값');
    });
  });

  group('달 요약', () {
    test('갈래별 건수를 더해 총계를 낸다', () {
      const month = OperationMonth(
        year: 2026,
        month: 8,
        counts: {
          OperationLogKind.setting: 3,
          OperationLogKind.task: 8,
          OperationLogKind.incident: 1,
        },
      );
      expect(month.total, 12);
      expect(month.label, '2026년 8월');
      expect(month.key, '2026-08');
    });

    test('한 자리 달도 두 자리로 맞춘다', () {
      // 문자열로 정렬하므로 2026-9 가 2026-10 뒤로 가면 안 된다.
      const nine = OperationMonth(year: 2026, month: 9, counts: {});
      const ten = OperationMonth(year: 2026, month: 10, counts: {});
      expect(nine.key, '2026-09');
      expect([ten.key, nine.key]..sort(), ['2026-09', '2026-10']);
    });
  });

  group('설정 변경', () {
    test('한 일을 한글로 알린다', () {
      const added = MapProjectChange(
        category: 'robot',
        action: 'added',
        target: 'PK-01',
        summary: '',
      );
      expect(added.categoryLabel, '로봇 등록');
      expect(added.actionLabel, '추가');
    });
  });

  final enabled = Platform.environment['RUN_MYSQL_OPERATIONS_TEST'] == '1';

  group('MySQL 왕복', () {
    const project = '_운영기록_시험';

    // 설정 기록은 맵 프로젝트에 딸린다(외래 키). 시험용 프로젝트를 스스로
    // 만들고 지운다 — 손으로 만들어 둔 것에 기대면 다음 사람이 못 돌린다.
    setUpAll(() async {
      await saveMapProject(
        mapName: project,
        payloadJson: '{"mapName":"$project"}',
      );
    });
    tearDownAll(() async {
      // 프로젝트를 지우면 그 설정 기록도 함께 사라진다(CASCADE).
      await deleteMapProject(project);
    });

    test('설정 변경을 남기고 그날 기록에서 찾는다', () async {
      // 기록이 남지 않으면 운영 분석에 설정 축이 통째로 비어 보인다.
      await recordMapProjectChanges(project, const [
        MapProjectChange(
          category: 'robot',
          action: 'added',
          target: '시험-01',
          summary: '시험용 로봇 · 이동 로봇',
        ),
      ]);
      final entries = await loadOperationEntries(DateTime.now());
      final mine = entries.where(
        (entry) =>
            entry.kind == OperationLogKind.setting &&
            entry.title.contains('시험-01'),
      );
      expect(mine, isNotEmpty, reason: '방금 남긴 설정 기록이 보여야 한다');
      expect(mine.first.title, '로봇 등록 추가 · 시험-01');
      expect(mine.first.detail, '시험용 로봇 · 이동 로봇');
      expect(mine.first.project, project);
    });

    test('빈 목록이면 아무것도 남기지 않는다', () async {
      // 저장을 누를 때마다 줄이 늘면 무엇이 실제로 달라졌는지 오히려 안 보인다.
      final before = (await loadOperationEntries(
        DateTime.now(),
      )).where((entry) => entry.kind == OperationLogKind.setting).length;
      await recordMapProjectChanges(project, const []);
      final after = (await loadOperationEntries(
        DateTime.now(),
      )).where((entry) => entry.kind == OperationLogKind.setting).length;
      expect(after, before);
    });

    test('없는 프로젝트에 남기려 해도 죽지 않는다', () async {
      // 저장이 끝난 뒤에 기록을 남긴다. 여기서 예외가 나면 이미 저장된
      // 프로젝트를 두고 실패했다고 알리게 된다.
      await recordMapProjectChanges('_없는_프로젝트_', const [
        MapProjectChange(
          category: 'robot',
          action: 'added',
          target: 'X',
          summary: '',
        ),
      ]);
    });

    test('달과 날짜 요약이 서로 맞는다', () async {
      final months = await loadOperationMonths();
      expect(months, isNotEmpty);
      // 최근 달이 먼저 온다.
      for (var i = 1; i < months.length; i++) {
        expect(months[i - 1].key.compareTo(months[i].key), greaterThan(0));
      }
      final month = months.first;
      final days = await loadOperationDays(month.year, month.month);
      expect(days, isNotEmpty);
      // 날짜별 합이 그 달의 총계와 같아야 한다. 어긋나면 어느 한쪽이 기록을
      // 빠뜨리고 있다는 뜻이다.
      final sum = days.fold(0, (total, day) => total + day.total);
      expect(sum, month.total);
      // 날짜는 오름차순.
      for (var i = 1; i < days.length; i++) {
        expect(days[i - 1].date.isBefore(days[i].date), isTrue);
      }
    });

    test('하루치 기록은 시각 순이다', () async {
      final months = await loadOperationMonths();
      final days = await loadOperationDays(
        months.first.year,
        months.first.month,
      );
      final entries = await loadOperationEntries(days.last.date);
      for (var i = 1; i < entries.length; i++) {
        expect(
          entries[i - 1].at.isAfter(entries[i].at),
          isFalse,
          reason: '설정과 운영을 섞어 놓았으므로 시각 순이어야 흐름이 읽힌다',
        );
      }
    });
  }, skip: enabled ? false : 'MySQL 운영 기록 테스트 환경이 설정되지 않았습니다.');
}
