/// `ros2` 를 불러 노드·토픽·서비스·액션을 들여다본다.
///
/// 값과 형식은 `ros2_inspect_models.dart` 에 있고, 실제로 명령을 돌리는 것은
/// 플랫폼별 구현이 한다. 웹에서는 프로세스를 띄울 수 없다.
library;

export 'ros2_inspect_models.dart';
export 'ros2_inspect_stub.dart' if (dart.library.io) 'ros2_inspect_io.dart';
