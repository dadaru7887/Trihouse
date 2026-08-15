import 'package:robo_core/robo_core.dart';

import 'store_factory_memory.dart'
    if (dart.library.ffi) 'store_factory_sqlite.dart';

/// 플랫폼에 맞는 저장소를 만든다.
///
/// * 네이티브(Android·데스크톱) — 관제센터와 같은 SQLite 원장에 직접 붙는다.
/// * 웹 — `dart:ffi`를 쓸 수 없어 인메모리 데모 저장소를 쓴다.
///   실제 서비스에서는 서버 API를 호출하는 [DataStore] 구현으로 바꾼다.
DataStore createStore() => createPlatformStore();

/// 이 빌드가 관제센터 원장에 직접 연결되어 있는지.
bool get isConnectedToCenter => platformStoreIsShared;
