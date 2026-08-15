/// 운영 분석 기록 저장소의 겉면.
///
/// 데스크톱에서는 `mysql` 클라이언트를 부르고, 웹에서는 빈 값을 돌려준다.
library;

export 'operations_log_stub.dart' if (dart.library.io) 'operations_log_io.dart';
