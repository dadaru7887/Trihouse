import 'database_migration_models.dart';

Future<DatabaseMigrationResult> migrateDatabaseSchema() async =>
    const DatabaseMigrationResult(fromVersion: null, toVersion: 0, applied: []);
