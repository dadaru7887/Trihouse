import 'package:flutter/material.dart';

import '../api/fms_api_client.dart';

const controlNavy = Color(0xFF111827);
const controlBlue = Color(0xFF2563EB);
const controlSlate = Color(0xFF64748B);

class PageHeading extends StatelessWidget {
  const PageHeading({
    super.key,
    required this.title,
    required this.description,
    this.actions = const [],
  });

  final String title;
  final String description;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) => Row(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.headlineMedium),
            const SizedBox(height: 6),
            Text(description),
          ],
        ),
      ),
      ...actions,
    ],
  );
}

class GatewayFailurePanel extends StatelessWidget {
  const GatewayFailurePanel({super.key, required this.error, this.onRetry});

  final Object error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    debugPrint('FMS Gateway request failed: $error');
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: const Color(0xFFFEF2F2),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFFECACA)),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline, color: Color(0xFFB91C1C)),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              fmsApiUserMessage(error),
              style: const TextStyle(color: Color(0xFF7F1D1D)),
            ),
          ),
          if (onRetry != null)
            OutlinedButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh, size: 18),
              label: const Text('다시 시도'),
            ),
        ],
      ),
    );
  }
}

/// 운영 WebSocket 이 붙어 있는지 한눈에 보이게 한다. 화면이 멈춘 것인지 원장이
/// 조용한 것인지 구분하지 못하면 시연 중에 판단할 수 없다.
class LiveBadge extends StatelessWidget {
  const LiveBadge({super.key, required this.connected, this.stale = false});

  final bool connected;
  final bool stale;

  @override
  Widget build(BuildContext context) {
    final color = connected ? const Color(0xFF16A34A) : const Color(0xFFDC2626);
    return Row(
      key: const Key('live-badge'),
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(
          connected ? Icons.circle : Icons.circle_outlined,
          size: 10,
          color: color,
        ),
        const SizedBox(width: 6),
        Text(
          connected ? (stale ? '갱신 중' : '실시간') : '연결 끊김',
          style: TextStyle(color: color, fontWeight: FontWeight.w700),
        ),
      ],
    );
  }
}

class DashboardPanel extends StatelessWidget {
  const DashboardPanel({
    super.key,
    required this.title,
    required this.icon,
    required this.child,
  });

  final String title;
  final IconData icon;
  final Widget child;

  @override
  Widget build(BuildContext context) => Container(
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: const Color(0xFFE2E8F0)),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(18, 16, 18, 12),
          child: Row(
            children: [
              Icon(icon, size: 19, color: controlBlue),
              const SizedBox(width: 8),
              Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
            ],
          ),
        ),
        const Divider(height: 1),
        Expanded(child: child),
      ],
    ),
  );
}
