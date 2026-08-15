import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'movable_dialog.dart';
import 'trihouse/api/fms_api.dart';
import 'trihouse/api/fms_api_client.dart';
import 'trihouse/presentation/control_shell.dart';
import 'trihouse/presentation/shared.dart';

void main() {
  const configuredBaseUrl = String.fromEnvironment('FMS_GATEWAY_BASE_URL');
  const credentialedCrossOrigin = bool.fromEnvironment(
    'FMS_GATEWAY_CROSS_ORIGIN_CREDENTIALS',
  );
  final configuration = GatewayClientConfiguration.resolve(
    pageUri: Uri.base,
    configuredBaseUrl: configuredBaseUrl,
    allowCredentialedCrossOrigin: credentialedCrossOrigin,
  );
  runApp(
    RmfControlApp(api: FmsApiClient.forBrowser(configuration: configuration)),
  );
}

class RmfControlApp extends StatelessWidget {
  const RmfControlApp({super.key, required this.api});

  final FmsApi api;

  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    title: 'Trihouse Control',
    theme: ThemeData(
      useMaterial3: true,
      fontFamily: 'sans-serif',
      scaffoldBackgroundColor: const Color(0xFFF5F7FA),
      colorScheme: ColorScheme.fromSeed(
        seedColor: controlBlue,
        brightness: Brightness.light,
        surface: Colors.white,
      ),
      textTheme: const TextTheme(
        headlineMedium: TextStyle(
          color: controlNavy,
          fontWeight: FontWeight.w800,
          letterSpacing: -0.8,
        ),
        titleMedium: TextStyle(color: controlNavy, fontWeight: FontWeight.w700),
        bodyMedium: TextStyle(color: controlSlate),
      ),
    ),
    home: ControlAppShell(api: api),
  );
}

Future<void> showWaypointErrorDialog(
  BuildContext context, {
  required String title,
  required String message,
}) => showMovableDialog<void>(
  context: context,
  builder: (_) => _CopyableErrorDialog(title: title, message: message),
);

class _CopyableErrorDialog extends StatefulWidget {
  const _CopyableErrorDialog({required this.title, required this.message});

  final String title;
  final String message;

  @override
  State<_CopyableErrorDialog> createState() => _CopyableErrorDialogState();
}

class _CopyableErrorDialogState extends State<_CopyableErrorDialog> {
  static const double _minWidth = 320;
  static const double _minHeight = 140;
  double _width = 520;
  double _height = 240;

  @override
  Widget build(BuildContext context) {
    final screen = MediaQuery.sizeOf(context);
    final maxWidth = math.max(_minWidth, screen.width - 120);
    final maxHeight = math.max(_minHeight, screen.height - 220);
    final width = _width.clamp(_minWidth, maxWidth);
    final height = _height.clamp(_minHeight, maxHeight);
    return AlertDialog(
      title: Row(
        children: [
          const Icon(Icons.error_outline, color: Color(0xFFDC2626)),
          const SizedBox(width: 10),
          Expanded(child: Text(widget.title)),
        ],
      ),
      content: SizedBox(
        width: width,
        height: height,
        child: Stack(
          children: [
            Positioned.fill(
              child: Container(
                decoration: BoxDecoration(
                  color: const Color(0xFFFEF2F2),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: const Color(0xFFFECACA)),
                ),
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(14, 14, 14, 26),
                  child: SelectableText(widget.message),
                ),
              ),
            ),
            Positioned(
              right: 0,
              bottom: 0,
              child: MouseRegion(
                cursor: SystemMouseCursors.resizeDownRight,
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onPanUpdate: (details) => setState(() {
                    _width = (width + details.delta.dx).clamp(
                      _minWidth,
                      maxWidth,
                    );
                    _height = (height + details.delta.dy).clamp(
                      _minHeight,
                      maxHeight,
                    );
                  }),
                  child: const Padding(
                    padding: EdgeInsets.all(6),
                    child: Icon(Icons.open_in_full, size: 15),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton.icon(
          onPressed: () async {
            await Clipboard.setData(ClipboardData(text: widget.message));
            if (!context.mounted) return;
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('오류 내용을 클립보드에 복사했습니다.')),
            );
          },
          icon: const Icon(Icons.content_copy_outlined, size: 18),
          label: const Text('복사'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('닫기'),
        ),
      ],
    );
  }
}
