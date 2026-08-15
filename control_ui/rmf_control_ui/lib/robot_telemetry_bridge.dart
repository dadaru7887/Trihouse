/// 로봇 위치 토픽 다리의 겉면.
///
/// 데스크톱에서는 `ros2 topic echo` 를 띄우고, 웹에서는 아무것도 하지 않는다.
library;

export 'robot_telemetry_bridge_stub.dart'
    if (dart.library.io) 'robot_telemetry_bridge_io.dart';
