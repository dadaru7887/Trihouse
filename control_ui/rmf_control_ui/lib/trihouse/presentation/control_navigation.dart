import 'package:flutter/material.dart';

import 'shared.dart';

enum ControlDestination { dashboard, maps, robots, tasks, operations }

extension ControlDestinationLabel on ControlDestination {
  String get label => switch (this) {
    ControlDestination.dashboard => '대시보드',
    ControlDestination.maps => '맵 관리',
    ControlDestination.robots => '로봇',
    ControlDestination.tasks => '작업',
    ControlDestination.operations => '운영 분석',
  };

  IconData get icon => switch (this) {
    ControlDestination.dashboard => Icons.dashboard_outlined,
    ControlDestination.maps => Icons.map_outlined,
    ControlDestination.robots => Icons.smart_toy_outlined,
    ControlDestination.tasks => Icons.assignment_outlined,
    ControlDestination.operations => Icons.analytics_outlined,
  };
}

class ControlNavigationRail extends StatelessWidget {
  const ControlNavigationRail({
    super.key,
    required this.selected,
    required this.onSelected,
  });

  final ControlDestination selected;
  final ValueChanged<ControlDestination> onSelected;

  @override
  Widget build(BuildContext context) => Container(
    width: 236,
    color: controlNavy,
    child: Column(
      children: [
        const SizedBox(height: 24),
        const _Logo(),
        const SizedBox(height: 28),
        for (final destination in ControlDestination.values)
          _NavItem(
            destination: destination,
            selected: destination == selected,
            onTap: () => onSelected(destination),
          ),
        const Spacer(),
        const Padding(
          padding: EdgeInsets.all(20),
          child: Row(
            children: [
              Icon(Icons.lock_outline, size: 16, color: Color(0xFF94A3B8)),
              SizedBox(width: 8),
              Expanded(
                child: Text(
                  'FMS Gateway 보안 세션',
                  style: TextStyle(color: Color(0xFF94A3B8), fontSize: 12),
                ),
              ),
            ],
          ),
        ),
      ],
    ),
  );
}

class _Logo extends StatelessWidget {
  const _Logo();

  @override
  Widget build(BuildContext context) => const Padding(
    padding: EdgeInsets.symmetric(horizontal: 22),
    child: Row(
      children: [
        DecoratedBox(
          decoration: BoxDecoration(color: controlBlue, shape: BoxShape.circle),
          child: Padding(
            padding: EdgeInsets.all(9),
            child: Icon(Icons.hub_outlined, color: Colors.white, size: 22),
          ),
        ),
        SizedBox(width: 12),
        Expanded(
          child: Text(
            'Trihouse\nControl',
            style: TextStyle(
              height: 1.12,
              color: Colors.white,
              fontWeight: FontWeight.w800,
              fontSize: 17,
            ),
          ),
        ),
      ],
    ),
  );
}

class _NavItem extends StatelessWidget {
  const _NavItem({
    required this.destination,
    required this.selected,
    required this.onTap,
  });

  final ControlDestination destination;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
    child: Material(
      color: selected ? const Color(0xFF1E40AF) : Colors.transparent,
      borderRadius: BorderRadius.circular(10),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
          child: Row(
            children: [
              Icon(
                destination.icon,
                color: selected ? Colors.white : const Color(0xFF94A3B8),
                size: 21,
              ),
              const SizedBox(width: 13),
              Text(
                destination.label,
                style: TextStyle(
                  color: selected ? Colors.white : const Color(0xFFCBD5E1),
                  fontWeight: selected ? FontWeight.w800 : FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

class ControlTopBar extends StatelessWidget {
  const ControlTopBar({super.key, required this.destination});

  final ControlDestination destination;

  @override
  Widget build(BuildContext context) => Container(
    height: 66,
    padding: const EdgeInsets.symmetric(horizontal: 28),
    decoration: const BoxDecoration(
      color: Colors.white,
      border: Border(bottom: BorderSide(color: Color(0xFFE2E8F0))),
    ),
    child: Row(
      children: [
        Text(
          destination.label,
          style: const TextStyle(
            color: controlNavy,
            fontWeight: FontWeight.w800,
            fontSize: 16,
          ),
        ),
        const Spacer(),
        const _StatusDot(),
        const SizedBox(width: 8),
        const Text(
          'Gateway 연결',
          style: TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
        ),
        const SizedBox(width: 18),
        const CircleAvatar(
          radius: 16,
          backgroundColor: Color(0xFFEFF6FF),
          child: Icon(Icons.person_outline, size: 19, color: controlBlue),
        ),
      ],
    ),
  );
}

class _StatusDot extends StatelessWidget {
  const _StatusDot();

  @override
  Widget build(BuildContext context) => Container(
    width: 9,
    height: 9,
    decoration: const BoxDecoration(
      color: Color(0xFF16A34A),
      shape: BoxShape.circle,
    ),
  );
}
