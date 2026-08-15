import 'package:flutter/material.dart';

import 'core/fleet_engine.dart';
import 'package:robo_core/robo_core_sqlite.dart';
import 'ui/app_shell.dart';
import 'ui/theme.dart';

void main() {
  runApp(const RoboControlApp());
}

/// 3온도 물류센터 로봇 관제센터.
class RoboControlApp extends StatefulWidget {
  const RoboControlApp({super.key});

  @override
  State<RoboControlApp> createState() => _RoboControlAppState();
}

class _RoboControlAppState extends State<RoboControlApp> {
  late final SqliteDataStore _store = SqliteDataStore(AppDatabase.open());
  late final FleetEngine _engine = FleetEngine(store: _store);

  @override
  void initState() {
    super.initState();
    debugPrint('데이터베이스: ${_store.path}');
    _engine.start();
  }

  @override
  void dispose() {
    _engine.dispose();
    _store.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'RoboSapiens 물류 관제센터',
      debugShowCheckedModeBanner: false,
      theme: buildControlRoomTheme(),
      home: EngineScope(engine: _engine, child: const ControlCenterShell()),
    );
  }
}
