/// SQLite 저장소 구현 — **네이티브 전용**(`dart:ffi` 사용).
///
/// 웹 타깃에서는 임포트할 수 없다. 웹·모바일 클라이언트는 서버 API를 쓰는
/// 다른 [DataStore] 구현을 사용해야 한다.
library;

export 'data/app_database.dart';
export 'data/sqlite_repositories.dart';
