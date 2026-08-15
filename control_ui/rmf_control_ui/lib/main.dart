import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'movable_dialog.dart';
import 'trihouse/api/fms_api.dart';
import 'trihouse/api/fms_api_client.dart';
import 'trihouse/api/fms_models.dart';

void main() {
  runApp(RmfControlApp(api: FmsApiClient(baseUri: _gatewayBaseUri())));
}

Uri _gatewayBaseUri() {
  const configured = String.fromEnvironment('FMS_GATEWAY_BASE_URL');
  return configured.isEmpty ? Uri.base : Uri.parse(configured);
}

class RmfControlApp extends StatelessWidget {
  const RmfControlApp({super.key, required this.api});

  final FmsApi api;

  @override
  Widget build(BuildContext context) {
    const navy = Color(0xFF111827);
    const blue = Color(0xFF2563EB);
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Trihouse Control',
      theme: ThemeData(
        useMaterial3: true,
        fontFamily: 'sans-serif',
        scaffoldBackgroundColor: const Color(0xFFF5F7FA),
        colorScheme: ColorScheme.fromSeed(
          seedColor: blue,
          brightness: Brightness.light,
          surface: Colors.white,
        ),
        textTheme: const TextTheme(
          headlineMedium: TextStyle(
            color: navy,
            fontWeight: FontWeight.w800,
            letterSpacing: -0.8,
          ),
          titleMedium: TextStyle(color: navy, fontWeight: FontWeight.w700),
          bodyMedium: TextStyle(color: Color(0xFF64748B)),
        ),
      ),
      home: ControlDashboard(api: api),
    );
  }
}

class ControlDashboard extends StatefulWidget {
  const ControlDashboard({super.key, required this.api});

  final FmsApi api;

  @override
  State<ControlDashboard> createState() => _ControlDashboardState();
}

class _ControlDashboardState extends State<ControlDashboard> {
  late Future<List<InventoryLotDto>> _inventory;
  int _selectedPage = 0;

  @override
  void initState() {
    super.initState();
    _inventory = widget.api.listInventory();
  }

  void _refreshInventory() {
    setState(() => _inventory = widget.api.listInventory());
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Row(
        children: [
          NavigationRail(
            extended: MediaQuery.sizeOf(context).width >= 960,
            selectedIndex: _selectedPage,
            onDestinationSelected: (value) {
              setState(() => _selectedPage = value);
            },
            leading: const Padding(
              padding: EdgeInsets.symmetric(vertical: 18),
              child: Icon(Icons.hub_outlined, size: 32),
            ),
            destinations: const [
              NavigationRailDestination(
                icon: Icon(Icons.dashboard_outlined),
                selectedIcon: Icon(Icons.dashboard),
                label: Text('대시보드'),
              ),
              NavigationRailDestination(
                icon: Icon(Icons.map_outlined),
                selectedIcon: Icon(Icons.map),
                label: Text('맵'),
              ),
              NavigationRailDestination(
                icon: Icon(Icons.receipt_long_outlined),
                selectedIcon: Icon(Icons.receipt_long),
                label: Text('주문'),
              ),
              NavigationRailDestination(
                icon: Icon(Icons.monitor_heart_outlined),
                selectedIcon: Icon(Icons.monitor_heart),
                label: Text('운영'),
              ),
            ],
          ),
          const VerticalDivider(width: 1),
          Expanded(
            child: SafeArea(
              child: switch (_selectedPage) {
                0 => _GatewayDashboard(
                  inventory: _inventory,
                  onRefresh: _refreshInventory,
                ),
                1 => const _PendingGatewayPage(
                  icon: Icons.map_outlined,
                  title: '맵 프로젝트',
                  detail: 'Gateway Draft API를 통해 지도를 관리합니다.',
                ),
                2 => const _PendingGatewayPage(
                  icon: Icons.receipt_long_outlined,
                  title: '출고 주문',
                  detail: 'Gateway가 상품 주문과 작업 계획을 관리합니다.',
                ),
                _ => const _PendingGatewayPage(
                  icon: Icons.monitor_heart_outlined,
                  title: '실시간 운영',
                  detail: 'Gateway WebSocket 운영 피드를 표시합니다.',
                ),
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _GatewayDashboard extends StatelessWidget {
  const _GatewayDashboard({required this.inventory, required this.onRefresh});

  final Future<List<InventoryLotDto>> inventory;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(32),
      children: [
        Text(
          'Trihouse Control',
          style: Theme.of(context).textTheme.headlineMedium,
        ),
        const SizedBox(height: 8),
        Text(
          'FMS Gateway에서 제공하는 운영 정보를 표시합니다.',
          style: Theme.of(context).textTheme.bodyLarge,
        ),
        const SizedBox(height: 28),
        Card(
          clipBehavior: Clip.antiAlias,
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text('재고', style: Theme.of(context).textTheme.titleLarge),
                    const Spacer(),
                    IconButton(
                      tooltip: '새로고침',
                      onPressed: onRefresh,
                      icon: const Icon(Icons.refresh),
                    ),
                  ],
                ),
                const Divider(),
                FutureBuilder<List<InventoryLotDto>>(
                  future: inventory,
                  builder: (context, snapshot) {
                    if (snapshot.connectionState != ConnectionState.done) {
                      return const Center(
                        child: Padding(
                          padding: EdgeInsets.all(24),
                          child: CircularProgressIndicator(),
                        ),
                      );
                    }
                    if (snapshot.hasError) {
                      return _GatewayError(
                        error: snapshot.error!,
                        onRetry: onRefresh,
                      );
                    }
                    final lots = snapshot.data ?? const [];
                    if (lots.isEmpty) {
                      return const Padding(
                        padding: EdgeInsets.symmetric(vertical: 20),
                        child: Text('표시할 재고 lot이 없습니다.'),
                      );
                    }
                    return Column(
                      children: [
                        for (final lot in lots) _InventoryLotTile(lot: lot),
                      ],
                    );
                  },
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _InventoryLotTile extends StatelessWidget {
  const _InventoryLotTile({required this.lot});

  final InventoryLotDto lot;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: const CircleAvatar(child: Icon(Icons.inventory_2_outlined)),
      title: Text(lot.productCode),
      subtitle: Text(
        [
          if (lot.itemName != null) lot.itemName!,
          lot.lotCode,
          if (lot.locationCode != null) lot.locationCode!,
        ].join(' · '),
      ),
      trailing: Text('가용 ${lot.availableQty} · 예약 ${lot.reservedQty}'),
    );
  }
}

class _GatewayError extends StatelessWidget {
  const _GatewayError({required this.error, required this.onRetry});

  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Gateway에서 재고를 불러오지 못했습니다.'),
          const SizedBox(height: 8),
          SelectableText('$error'),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: onRetry,
            icon: const Icon(Icons.refresh),
            label: const Text('다시 시도'),
          ),
        ],
      ),
    );
  }
}

class _PendingGatewayPage extends StatelessWidget {
  const _PendingGatewayPage({
    required this.icon,
    required this.title,
    required this.detail,
  });

  final IconData icon;
  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(icon, size: 48),
                const SizedBox(height: 18),
                Text(title, style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 10),
                Text(detail, textAlign: TextAlign.center),
              ],
            ),
          ),
        ),
      ),
    );
  }
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
                child: Scrollbar(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.fromLTRB(14, 14, 14, 26),
                    child: SelectableText(
                      widget.message,
                      style: const TextStyle(
                        color: Color(0xFF7F1D1D),
                        height: 1.5,
                      ),
                    ),
                  ),
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
                    child: Icon(
                      Icons.open_in_full,
                      size: 15,
                      color: Color(0xFFB91C1C),
                    ),
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
