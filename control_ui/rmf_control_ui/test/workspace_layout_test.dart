import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/workspace_layout_io.dart';

void main() {
  test('고정 구조의 실제 디렉터리는 경고하지 않는다', () async {
    final temp = await Directory.systemTemp.createTemp('robosapiens-layout-');
    addTearDown(() => temp.delete(recursive: true));
    final root = Directory('${temp.path}/robosapiens');
    root.createSync();
    File('${root.path}/rmf_ws/install/setup.bash').createSync(recursive: true);
    File(
      '${root.path}/robot_model/pinky_pro/pinky_description/package.xml',
    ).createSync(recursive: true);
    File(
      '${root.path}/robot_model/open_manipulator/src/open_manipulator/'
      'open_manipulator_description/package.xml',
    ).createSync(recursive: true);

    expect(
      await workspaceLayoutWarnings(
        homePath: temp.path,
        detectedRootPath: root.path,
      ),
      isEmpty,
    );
  });

  test('누락 디렉터리와 심볼릭 링크를 경고한다', () async {
    final temp = await Directory.systemTemp.createTemp('robosapiens-layout-');
    addTearDown(() => temp.delete(recursive: true));
    final root = Directory('${temp.path}/robosapiens');
    root.createSync();
    final outside = Directory('${temp.path}/outside');
    outside.createSync();
    Link('${root.path}/rmf_ws').createSync(outside.path);

    final warnings = await workspaceLayoutWarnings(
      homePath: temp.path,
      detectedRootPath: root.path,
    );
    expect(warnings, anyElement(contains('심볼릭 링크')));
    expect(warnings, anyElement(contains('robot_model/pinky_pro')));
    expect(warnings, anyElement(contains('robot_model/open_manipulator')));
  });

  test('robot_model 상위 디렉터리의 심볼릭 링크도 경고한다', () async {
    final temp = await Directory.systemTemp.createTemp('robosapiens-layout-');
    addTearDown(() => temp.delete(recursive: true));
    final root = Directory('${temp.path}/robosapiens');
    root.createSync();
    final outside = Directory('${temp.path}/models');
    outside.createSync();
    Link('${root.path}/robot_model').createSync(outside.path);

    final warnings = await workspaceLayoutWarnings(
      homePath: temp.path,
      detectedRootPath: root.path,
    );
    expect(
      warnings,
      anyElement(allOf(contains('robot_model'), contains('심볼릭 링크'))),
    );
  });
}
