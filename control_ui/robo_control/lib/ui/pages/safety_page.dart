import 'package:flutter/material.dart';

import '../../core/fleet_engine.dart';
import 'package:robo_core/models/enums.dart';
import '../app_shell.dart';
import '../theme.dart';
import '../widgets/common.dart';
import '../widgets/registration_dialogs.dart';

/// 안전 관리: 상황 발령·해제, 자동 대응 조치, 인간-로봇 공존 상태.
class SafetyPage extends StatelessWidget {
  const SafetyPage({super.key});

  @override
  Widget build(BuildContext context) {
    final engine = EngineScope.of(context);

    return Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Expanded(
          flex: 3,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Panel(
                title: '안전 상황 발령',
                subtitle: '발령 시 사전 정의된 대응 시퀀스가 자동 실행됩니다',
                child: _IncidentControls(engine: engine),
              ),
              const SizedBox(height: 12),
              Expanded(
                child: Panel(
                  title: '안전 상황 이력',
                  subtitle:
                      '진행 중 ${engine.activeIncidents.length}건 · 누적 ${engine.incidents.length}건',
                  child: engine.incidents.isEmpty
                      ? const EmptyHint('기록된 안전 상황이 없습니다.')
                      : ListView.builder(
                          padding: EdgeInsets.zero,
                          itemCount: engine.incidents.length,
                          itemBuilder: (context, i) =>
                              _IncidentCard(engine: engine, index: i),
                        ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          flex: 2,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Panel(
                title: '인간-로봇 공존 정책',
                subtitle: '작업자 근접 시 속도 제한 및 정지 규칙',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: const <Widget>[
                    _Rule(
                      color: AppColors.critical,
                      icon: Icons.pan_tool_outlined,
                      title: '보호 필드 (반경 1.7m)',
                      body: '작업자가 진입하면 로봇은 즉시 정지합니다. 인계 작업 중이어도 동력을 차단하고 대기합니다.',
                    ),
                    _Rule(
                      color: AppColors.warning,
                      icon: Icons.slow_motion_video_outlined,
                      title: '경고 필드 (반경 4m)',
                      body: '최고 속도의 35%로 감속 주행하며, 통로 폭이 좁을 경우 작업자에게 우선권을 양보합니다.',
                    ),
                    _Rule(
                      color: AppColors.series1,
                      icon: Icons.volunteer_activism_outlined,
                      title: '전달 작업 안전 절차',
                      body: '작업자가 6m 이내에 도착해야 인계 스텝이 진행되며, 인계 중에는 정지 상태를 유지합니다.',
                    ),
                    _Rule(
                      color: AppColors.series3,
                      icon: Icons.alt_route_outlined,
                      title: '로봇 간 교통 제어',
                      body: '선행 로봇 5m 이내 접근 시 후행 로봇이 감속·양보하여 교차로 충돌을 방지합니다.',
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              Expanded(
                child: Panel(
                  title: '작업자 현황',
                  subtitle: '${engine.workers.length}명 · 위치 · 구획 · 최근접 로봇 거리',
                  trailing: TextButton.icon(
                    onPressed: () => AddWorkerDialog.show(context, engine),
                    style: TextButton.styleFrom(
                      foregroundColor: AppColors.series5,
                      padding: const EdgeInsets.symmetric(horizontal: 8),
                      minimumSize: Size.zero,
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                    icon: const Icon(Icons.person_add_alt, size: 14),
                    label: const Text('작업자 등록', style: TextStyle(fontSize: 11.5)),
                  ),
                  child: _WorkerList(engine: engine),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _IncidentControls extends StatelessWidget {
  const _IncidentControls({required this.engine});

  final FleetEngine engine;

  @override
  Widget build(BuildContext context) {
    Widget button(
      String label,
      IconData icon,
      Color color,
      VoidCallback onTap,
      String hint,
    ) {
      return SizedBox(
        width: 208,
        child: Tooltip(
          message: hint,
          child: OutlinedButton.icon(
            onPressed: onTap,
            style: OutlinedButton.styleFrom(
              foregroundColor: color,
              side: BorderSide(color: color.withValues(alpha: 0.5)),
              backgroundColor: color.withValues(alpha: 0.08),
              padding: const EdgeInsets.symmetric(vertical: 13, horizontal: 10),
              alignment: Alignment.centerLeft,
            ),
            icon: Icon(icon, size: 15),
            label: Text(
              label,
              style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
            ),
          ),
        ),
      );
    }

    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: <Widget>[
        button(
          '화재 발생',
          Icons.local_fire_department_outlined,
          AppColors.critical,
          () => engine.raiseIncident(
            IncidentType.fire,
            description: '물류센터 화재 감지기 작동',
          ),
          '전 로봇 작업 중지 → 비상 집결지 대피 → 신규 할당 중단',
        ),
        button(
          '작업자 위급',
          Icons.personal_injury_outlined,
          AppColors.critical,
          engine.raiseWorkerEmergency,
          '해당 작업자 반경 내 로봇 즉시 정지 및 구조 통로 확보',
        ),
        button(
          '냉동 구역 전원 차단',
          Icons.power_off_outlined,
          AppColors.serious,
          () => engine.raiseIncident(
            IncidentType.powerCut,
            zone: TempZone.frozen,
            description: '냉동 구역 배전반 차단 — 비상 조도 전환',
          ),
          '해당 구역 로봇 정지 · 조도 저하로 측위 신뢰도 하향',
        ),
        button(
          '냉장 구역 전원 차단',
          Icons.power_off_outlined,
          AppColors.serious,
          () => engine.raiseIncident(
            IncidentType.powerCut,
            zone: TempZone.chilled,
            description: '냉장 구역 배전반 차단 — 비상 조도 전환',
          ),
          '해당 구역 로봇 정지 · 태스크 할당 중단',
        ),
        button(
          '바닥 결빙·오염',
          Icons.ac_unit,
          AppColors.warning,
          () => engine.raiseIncident(
            IncidentType.spill,
            zone: TempZone.frozen,
            description: '냉동 구역 바닥 결빙으로 마찰계수 저하',
          ),
          '마찰계수 하향 반영 → 해당 구역 속도 자동 제한',
        ),
      ],
    );
  }
}

class _IncidentCard extends StatelessWidget {
  const _IncidentCard({required this.engine, required this.index});

  final FleetEngine engine;
  final int index;

  @override
  Widget build(BuildContext context) {
    final inc = engine.incidents[index];
    final color = AppColors.severityColor(inc.type.severity);

    return Container(
      margin: const EdgeInsets.only(bottom: 9),
      padding: const EdgeInsets.fromLTRB(11, 10, 11, 11),
      decoration: BoxDecoration(
        color: inc.active
            ? color.withValues(alpha: 0.07)
            : AppColors.page.withValues(alpha: 0.6),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: inc.active ? color.withValues(alpha: 0.45) : AppColors.border,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(AppColors.severityIcon(inc.type.severity), size: 14, color: color),
              const SizedBox(width: 7),
              Text(
                inc.type.label,
                style: TextStyle(
                  color: color,
                  fontSize: 12.5,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(width: 8),
              StatusChip(
                label: inc.active ? '진행 중' : '해제됨',
                color: inc.active ? color : AppColors.muted,
                compact: true,
              ),
              const Spacer(),
              Text(
                '${engine.timeLabel(inc.at)}'
                '${inc.clearedAt != null ? " → ${engine.timeLabel(inc.clearedAt!)}" : ""}',
                style: const TextStyle(
                  color: AppColors.muted,
                  fontSize: 10.5,
                  fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
                ),
              ),
              if (inc.active) ...<Widget>[
                const SizedBox(width: 8),
                TextButton(
                  onPressed: () => engine.clearIncident(inc.id),
                  style: TextButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    minimumSize: Size.zero,
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                  child: const Text('해제', style: TextStyle(fontSize: 11.5)),
                ),
              ],
            ],
          ),
          const SizedBox(height: 5),
          Text(
            inc.description,
            style: const TextStyle(color: AppColors.textSecondary, fontSize: 11.5),
          ),
          const SizedBox(height: 7),
          for (final a in inc.actions)
            Padding(
              padding: const EdgeInsets.only(bottom: 3),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Icon(
                    inc.active ? Icons.play_arrow : Icons.check,
                    size: 11,
                    color: inc.active ? color : AppColors.good,
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      a,
                      style: const TextStyle(
                        color: AppColors.textSecondary,
                        fontSize: 11,
                        height: 1.4,
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _Rule extends StatelessWidget {
  const _Rule({
    required this.color,
    required this.icon,
    required this.title,
    required this.body,
  });

  final Color color;
  final IconData icon;
  final String title;
  final String body;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 11),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Icon(icon, size: 14, color: color),
        const SizedBox(width: 9),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(
                title,
                style: TextStyle(
                  color: color,
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                body,
                style: const TextStyle(
                  color: AppColors.textSecondary,
                  fontSize: 11.5,
                  height: 1.45,
                ),
              ),
            ],
          ),
        ),
      ],
    ),
  );
}

class _WorkerList extends StatelessWidget {
  const _WorkerList({required this.engine});

  final FleetEngine engine;

  @override
  Widget build(BuildContext context) {
    return ListView.builder(
      padding: EdgeInsets.zero,
      itemCount: engine.workers.length,
      itemBuilder: (context, i) {
        final w = engine.workers[i];
        var nearest = double.infinity;
        String? nearestId;
        for (final r in engine.robots) {
          final d = (r.pos - w.pos).distance;
          if (d < nearest) {
            nearest = d;
            nearestId = r.id;
          }
        }
        final inProtective = nearest < 3.5;
        final inWarning = nearest < 8;
        final color = w.inDistress
            ? AppColors.critical
            : (inProtective
                  ? AppColors.serious
                  : (inWarning ? AppColors.warning : AppColors.good));

        return Padding(
          padding: const EdgeInsets.only(bottom: 9),
          child: Row(
            children: <Widget>[
              Icon(
                w.inDistress ? Icons.personal_injury_outlined : Icons.person_outline,
                size: 14,
                color: color,
              ),
              const SizedBox(width: 8),
              SizedBox(
                width: 74,
                child: Text(
                  w.name,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 11.5,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              SizedBox(
                width: 68,
                child: Text(
                  w.role,
                  style: const TextStyle(color: AppColors.muted, fontSize: 11),
                ),
              ),
              SizedBox(
                width: 44,
                child: Text(
                  w.zone.label,
                  style: TextStyle(
                    color: AppColors.zoneColor(w.zone),
                    fontSize: 11,
                  ),
                ),
              ),
              Expanded(
                child: Text(
                  nearestId == null
                      ? '—'
                      : '$nearestId ${nearest.toStringAsFixed(1)}u',
                  style: TextStyle(
                    color: color,
                    fontSize: 11,
                    fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
                  ),
                ),
              ),
              StatusChip(
                label: w.inDistress
                    ? '위급'
                    : (inProtective ? '보호 필드' : (inWarning ? '경고 필드' : '정상')),
                color: color,
                compact: true,
              ),
              const SizedBox(width: 2),
              IconButton(
                tooltip: '${w.name} 해제',
                onPressed: () => RemoveWorkerDialog.show(context, engine, w),
                padding: EdgeInsets.zero,
                constraints: const BoxConstraints.tightFor(width: 26, height: 26),
                icon: const Icon(
                  Icons.close,
                  size: 13,
                  color: AppColors.muted,
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}
