import 'package:robo_core/robo_core.dart';
import 'package:robo_core/robo_core_sqlite.dart';

/// 네이티브 빌드용 — 관제센터와 같은 SQLite 원장을 연다.
DataStore createPlatformStore() => SqliteDataStore(AppDatabase.open());

const bool platformStoreIsShared = true;
