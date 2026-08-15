/// 웹 빌드용 대체 구현. 브라우저에서는 벤더 파일을 읽을 수 없다.
library;

const String nav2ParamsEnvironmentKey = 'PINKY_NAV2_PARAMS';

String? findVendorNav2ParamsPath() => null;

String? readVendorNav2Params() => null;
