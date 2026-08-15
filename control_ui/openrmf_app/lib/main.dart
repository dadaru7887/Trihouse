import 'package:flutter/material.dart';

import 'src/app.dart';
import 'src/backend_bootstrap.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  const apiUrl = String.fromEnvironment(
    'RMF_API_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );
  const apiToken = String.fromEnvironment(
    'RMF_API_TOKEN',
    defaultValue:
        'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.'
        'eyJzdWIiOiJzdHViIiwicHJlZmVycmVkX3VzZXJuYW1lIjoiYWRtaW4iLCJpYXQiOjE1MTYyMzkwMjIsImF1ZCI6InJtZl9hcGlfc2VydmVyIiwiaXNzIjoic3R1YiIsImV4cCI6MjA1MTIyMjQwMH0.'
        'zzX3zXp467ldkzmLVIadQ_AHr8M5uWVV43n4wEB0OhE',
  );
  const trajectoryUrl = String.fromEnvironment(
    'RMF_TRAJECTORY_SERVER_URL',
    defaultValue: 'ws://127.0.0.1:8006',
  );
  const autoStartBackend = bool.fromEnvironment(
    'RMF_AUTO_START',
    defaultValue: true,
  );
  BackendSupervisor? backend;
  try {
    backend = await bootstrapBackend(
      apiUrl: apiUrl,
      autoStart: autoStartBackend,
    );
  } catch (exception) {
    runApp(_StartupError(message: '$exception'));
    return;
  }
  runApp(
    OpenRmfApp(
      apiUrl: apiUrl,
      apiToken: apiToken,
      trajectoryUrl: trajectoryUrl,
      backend: backend,
    ),
  );
}

class _StartupError extends StatelessWidget {
  const _StartupError({required this.message});
  final String message;

  @override
  Widget build(BuildContext context) => MaterialApp(
    theme: ThemeData.dark(),
    home: Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(
                Icons.error_outline,
                size: 48,
                color: Colors.redAccent,
              ),
              const SizedBox(height: 16),
              const Text('Open-RMF 백엔드를 시작하지 못했습니다.'),
              const SizedBox(height: 8),
              SelectableText(message, textAlign: TextAlign.center),
            ],
          ),
        ),
      ),
    ),
  );
}
