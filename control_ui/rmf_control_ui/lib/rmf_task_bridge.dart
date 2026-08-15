/// 앱과 RMF 사이의 작업 길. 겉면.
///
/// 데스크톱에서는 배포된 작업 다리 스크립트를 부르고, 웹에서는 아무것도 하지
/// 않는다.
library;

export 'rmf_task_bridge_stub.dart'
    if (dart.library.io) 'rmf_task_bridge_io.dart';
