/// 웹 빌드용 대체 구현. 브라우저에서는 프로세스를 띄울 수 없다.
library;

import 'ros2_inspect_models.dart';

const String _unsupported = '웹 빌드에서는 ros2 를 부를 수 없습니다. Linux 데스크톱 앱에서 실행하세요.';

Future<Ros2ListResult> ros2List(
  Ros2Kind kind,
  Ros2InspectRequest request,
) async =>
    const Ros2ListResult(success: false, items: [], message: _unsupported);

Future<Ros2DetailResult> ros2Detail(
  Ros2Kind kind,
  String name,
  Ros2InspectRequest request,
) async => const Ros2DetailResult(success: false, text: _unsupported);

Future<Ros2ValueResult> ros2TopicValue(
  String topic,
  Ros2InspectRequest request, {
  int waitSeconds = 5,
}) async =>
    const Ros2ValueResult(state: Ros2ValueState.failed, text: _unsupported);
