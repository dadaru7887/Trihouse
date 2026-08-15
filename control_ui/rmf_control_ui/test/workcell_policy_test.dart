import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/workcell_policy.dart';

void main() {
  test('Hugging Face 주소와 repository ID를 정규화한다', () {
    expect(
      parseHuggingFaceRepository(
        'https://huggingface.co/2usang/act_trihouse-sandwich',
      ),
      '2usang/act_trihouse-sandwich',
    );
    expect(
      parseHuggingFaceRepository('2usang/act_trihouse-sandwich'),
      '2usang/act_trihouse-sandwich',
    );
    expect(parseHuggingFaceRepository('https://example.com/a/b'), isNull);
  });

  test('ZIP signature와 확장자를 검증한다', () {
    final zip = Uint8List.fromList([0x50, 0x4b, 0x03, 0x04]);
    expect(validatePolicyArchive('pick.zip', zip), isNull);
    expect(validatePolicyArchive('pick.bin', zip), isNotNull);
    expect(validatePolicyArchive('pick.zip', Uint8List(8)), isNotNull);
  });

  test('배포 완료된 policy만 작업 선택 목록에 넣는다', () {
    final deployed = WorkcellPolicy(
      name: 'can_pick',
      version: '2.1.0',
      objectType: '캔',
      robotModel: 'open_manipulator_x',
      archiveName: 'can.zip',
      archiveBytes: 100,
      deployedWorkcells: const ['OMX_01'],
      createdAt: DateTime(2026),
    );
    final waiting = WorkcellPolicy(
      name: 'box_pick',
      version: '1.0.0',
      objectType: '박스',
      robotModel: 'open_manipulator_x',
      archiveName: 'box.zip',
      archiveBytes: 100,
      deployedWorkcells: const [],
      createdAt: DateTime(2026),
    );
    expect(deployedPolicyIds([deployed, waiting]), ['can_pick@2.1.0']);
  });

  test('manifest에 고정된 policy 이름과 버전을 남긴다', () {
    final policy = WorkcellPolicy(
      name: 'can_pick',
      version: '2.1.0',
      objectType: '캔',
      robotModel: 'open_manipulator_x',
      archiveName: 'can.zip',
      archiveBytes: 100,
      deployedWorkcells: const ['OMX_01'],
      createdAt: DateTime(2026),
    );
    expect(policy.manifest('warehouse'), contains('can_pick@2.1.0'));
    final global = policy.copyWith(objectType: '', deployedWorkcells: const []);
    expect(global.id, policy.id);
    expect(global.isDeployed, isFalse);
    expect(global.globalManifest(), contains('"scope": "global"'));
  });
}
