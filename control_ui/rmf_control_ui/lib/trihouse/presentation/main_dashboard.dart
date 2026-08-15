import 'package:flutter/material.dart';

import '../api/fms_api.dart';
import '../api/fms_models.dart';
import 'shared.dart';

class MainDashboard extends StatefulWidget {
  const MainDashboard({super.key, required this.api});

  final FmsApi api;

  @override
  State<MainDashboard> createState() => _MainDashboardState();
}

class _MainDashboardState extends State<MainDashboard> {
  late Future<List<InventoryLotDto>> _inventory;

  @override
  void initState() {
    super.initState();
    _inventory = widget.api.listInventory();
  }

  void _refresh() => setState(() => _inventory = widget.api.listInventory());

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.all(28),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        PageHeading(
          title: '운영 대시보드',
          description: '창고 맵, 로봇, 작업과 재고 상태를 한 화면에서 확인합니다.',
          actions: [
            OutlinedButton.icon(
              onPressed: _refresh,
              icon: const Icon(Icons.refresh, size: 18),
              label: const Text('새로고침'),
            ),
          ],
        ),
        const SizedBox(height: 20),
        const Row(
          children: [
            _MetricCard(label: '운영 로봇', value: '—', icon: Icons.smart_toy),
            SizedBox(width: 12),
            _MetricCard(label: '진행 작업', value: '—', icon: Icons.route),
            SizedBox(width: 12),
            _MetricCard(
              label: '안전 이벤트',
              value: '—',
              icon: Icons.health_and_safety,
            ),
          ],
        ),
        const SizedBox(height: 18),
        Expanded(
          child: Row(
            children: [
              Expanded(
                flex: 2,
                child: DashboardPanel(
                  title: '실시간 운영 맵',
                  icon: Icons.map_outlined,
                  child: CustomPaint(
                    painter: _DashboardMapPainter(),
                    child: const Center(
                      child: Text(
                        'Gateway 운영 좌표 스트림',
                        style: TextStyle(color: controlSlate),
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 18),
              Expanded(
                child: Column(
                  children: [
                    Expanded(
                      child: DashboardPanel(
                        title: '재고',
                        icon: Icons.inventory_2_outlined,
                        child: FutureBuilder<List<InventoryLotDto>>(
                          future: _inventory,
                          builder: (context, snapshot) {
                            if (snapshot.hasError) {
                              return Padding(
                                padding: const EdgeInsets.all(14),
                                child: GatewayFailurePanel(
                                  error: snapshot.error!,
                                  onRetry: _refresh,
                                ),
                              );
                            }
                            if (!snapshot.hasData) {
                              return const Center(
                                child: CircularProgressIndicator(),
                              );
                            }
                            return ListView(
                              padding: const EdgeInsets.all(12),
                              children: [
                                for (final lot in snapshot.data!)
                                  ListTile(
                                    dense: true,
                                    leading: const Icon(
                                      Icons.inventory_2_outlined,
                                    ),
                                    title: Text(lot.productCode),
                                    subtitle: Text(lot.lotCode),
                                    trailing: Text(
                                      '가용 ${lot.availableQty} · 예약 ${lot.reservedQty}',
                                    ),
                                  ),
                              ],
                            );
                          },
                        ),
                      ),
                    ),
                    const SizedBox(height: 18),
                    const Expanded(
                      child: DashboardPanel(
                        title: '최근 작업 활동',
                        icon: Icons.history,
                        child: Center(child: Text('운영 이벤트 수신 대기')),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 18),
        const _QuickActions(),
      ],
    ),
  );
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({
    required this.label,
    required this.value,
    required this.icon,
  });

  final String label;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) => Expanded(
    child: Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Row(
        children: [
          CircleAvatar(
            backgroundColor: const Color(0xFFEFF6FF),
            child: Icon(icon, color: controlBlue),
          ),
          const SizedBox(width: 12),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: const TextStyle(color: controlSlate)),
              Text(
                value,
                style: const TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
        ],
      ),
    ),
  );
}

class _QuickActions extends StatelessWidget {
  const _QuickActions();

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 13),
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(13),
      border: Border.all(color: const Color(0xFFE2E8F0)),
    ),
    child: const Row(
      children: [
        Text('빠른 실행', style: TextStyle(fontWeight: FontWeight.w800)),
        SizedBox(width: 20),
        Chip(label: Text('맵 프로젝트 열기')),
        SizedBox(width: 8),
        Chip(label: Text('작업 조회')),
        SizedBox(width: 8),
        Chip(label: Text('운영 이벤트 보기')),
      ],
    ),
  );
}

class _DashboardMapPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = const Color(0xFFE2E8F0)
      ..strokeWidth = 1;
    for (var x = 0.0; x < size.width; x += 36) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), paint);
    }
    for (var y = 0.0; y < size.height; y += 36) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), paint);
    }
    canvas.drawCircle(
      Offset(size.width * .42, size.height * .55),
      9,
      Paint()..color = controlBlue,
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
