import 'package:robo_core/robo_core.dart';

import 'demo_seed.dart';

/// 웹 빌드용 — 인메모리 저장소에 데모 카탈로그를 채운다.
DataStore createPlatformStore() {
  final store = MemoryDataStore();
  seedDemoCatalog(store);
  return store;
}

const bool platformStoreIsShared = false;
