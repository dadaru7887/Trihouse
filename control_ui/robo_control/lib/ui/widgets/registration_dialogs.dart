import 'package:flutter/material.dart';

import '../../core/fleet_engine.dart';
import 'package:robo_core/models/enums.dart';
import 'package:robo_core/models/robot.dart';
import 'package:robo_core/models/warehouse.dart';
import '../theme.dart';

/// 등록/해제 대화상자 공통 껍데기.
class _DialogShell extends StatelessWidget {
  const _DialogShell({
    required this.title,
    required this.icon,
    required this.accent,
    required this.body,
    required this.actions,
  });

  final String title;
  final IconData icon;
  final Color accent;
  final Widget body;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: AppColors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: BorderSide(color: AppColors.border),
      ),
      child: Container(
        width: 420,
        padding: const EdgeInsets.all(18),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Row(
              children: <Widget>[
                Icon(icon, size: 16, color: accent),
                const SizedBox(width: 8),
                Text(
                  title,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            body,
            const SizedBox(height: 18),
            Row(mainAxisAlignment: MainAxisAlignment.end, children: actions),
          ],
        ),
      ),
    );
  }
}

class _Field extends StatelessWidget {
  const _Field({required this.label, required this.child});

  final String label;
  final Widget child;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: <Widget>[
        SizedBox(
          width: 86,
          child: Text(
            label,
            style: const TextStyle(color: AppColors.muted, fontSize: 11.5),
          ),
        ),
        Expanded(child: child),
      ],
    ),
  );
}

InputDecoration _inputDecoration(String hint) => InputDecoration(
  hintText: hint,
  hintStyle: const TextStyle(color: AppColors.muted, fontSize: 12),
  isDense: true,
  contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
  filled: true,
  fillColor: AppColors.page,
  enabledBorder: OutlineInputBorder(
    borderRadius: BorderRadius.circular(6),
    borderSide: BorderSide(color: AppColors.border),
  ),
  focusedBorder: OutlineInputBorder(
    borderRadius: BorderRadius.circular(6),
    borderSide: BorderSide(color: AppColors.series1.withValues(alpha: 0.7)),
  ),
);

/// 선택지 토글 그룹.
class _Choices<T> extends StatelessWidget {
  const _Choices({
    required this.options,
    required this.labelOf,
    required this.selected,
    required this.onSelect,
    this.colorOf,
  });

  final List<T> options;
  final String Function(T) labelOf;
  final Color Function(T)? colorOf;
  final T selected;
  final ValueChanged<T> onSelect;

  @override
  Widget build(BuildContext context) => Wrap(
    spacing: 6,
    runSpacing: 6,
    children: <Widget>[
      for (final o in options)
        InkWell(
          onTap: () => onSelect(o),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
            decoration: BoxDecoration(
              color: o == selected
                  ? (colorOf?.call(o) ?? AppColors.series1).withValues(alpha: 0.18)
                  : Colors.transparent,
              borderRadius: BorderRadius.circular(6),
              border: Border.all(
                color: o == selected
                    ? (colorOf?.call(o) ?? AppColors.series1).withValues(alpha: 0.6)
                    : AppColors.border,
              ),
            ),
            child: Text(
              labelOf(o),
              style: TextStyle(
                color: o == selected ? AppColors.textPrimary : AppColors.muted,
                fontSize: 11.5,
                fontWeight: o == selected ? FontWeight.w600 : FontWeight.w400,
              ),
            ),
          ),
        ),
    ],
  );
}

/// 로봇 신규 등록 대화상자.
class AddRobotDialog extends StatefulWidget {
  const AddRobotDialog({super.key, required this.engine});

  final FleetEngine engine;

  static Future<void> show(BuildContext context, FleetEngine engine) =>
      showDialog<void>(
        context: context,
        builder: (_) => AddRobotDialog(engine: engine),
      );

  @override
  State<AddRobotDialog> createState() => _AddRobotDialogState();
}

enum _ZoneRating {
  warm('상온·냉장'),
  all('전 구획(냉동 포함)');

  const _ZoneRating(this.label);

  final String label;

  Set<TempZone> get zones => this == _ZoneRating.all
      ? const <TempZone>{TempZone.ambient, TempZone.chilled, TempZone.frozen}
      : const <TempZone>{TempZone.ambient, TempZone.chilled};
}

class _AddRobotDialogState extends State<AddRobotDialog> {
  final TextEditingController _name = TextEditingController();
  String _model = 'RSX-220';
  _ZoneRating _rating = _ZoneRating.warm;
  bool _reserve = false;

  static const List<String> _models = <String>['RSX-200', 'RSX-220', 'RSX-300C'];

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final nextId = 'RS-${(widget.engine.robots.length + 1).toString().padLeft(2, '0')}';
    return _DialogShell(
      title: '로봇 등록',
      icon: Icons.add_circle_outline,
      accent: AppColors.series1,
      body: Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          _Field(
            label: '호출명',
            child: TextField(
              controller: _name,
              autofocus: true,
              style: const TextStyle(color: AppColors.textPrimary, fontSize: 12.5),
              decoration: _inputDecoration('예: 인디아'),
            ),
          ),
          _Field(
            label: '모델',
            child: _Choices<String>(
              options: _models,
              labelOf: (m) => m,
              selected: _model,
              onSelect: (m) => setState(() {
                _model = m;
                // 냉동 대응 모델은 전 구획 등급을 기본값으로 맞춘다.
                if (m.endsWith('C')) _rating = _ZoneRating.all;
              }),
            ),
          ),
          _Field(
            label: '대응 구획',
            child: _Choices<_ZoneRating>(
              options: _ZoneRating.values,
              labelOf: (r) => r.label,
              colorOf: (r) => r == _ZoneRating.all
                  ? AppColors.series7
                  : AppColors.series1,
              selected: _rating,
              onSelect: (r) => setState(() => _rating = r),
            ),
          ),
          _Field(
            label: '투입 방식',
            child: _Choices<bool>(
              options: const <bool>[false, true],
              labelOf: (v) => v ? '예비 대기' : '즉시 투입',
              selected: _reserve,
              onSelect: (v) => setState(() => _reserve = v),
            ),
          ),
          const SizedBox(height: 2),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
            decoration: BoxDecoration(
              color: AppColors.page,
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: AppColors.border),
            ),
            child: Row(
              children: <Widget>[
                const Icon(Icons.info_outline, size: 13, color: AppColors.muted),
                const SizedBox(width: 7),
                Expanded(
                  child: Text(
                    'ID는 $nextId로 자동 부여되며, 대기 구역에 배치된 뒤 배터리 100%로 '
                    '시작합니다. 홈 충전소는 대응 구획에 맞춰 자동 배정됩니다.',
                    style: const TextStyle(
                      color: AppColors.muted,
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
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('취소', style: TextStyle(fontSize: 12)),
        ),
        const SizedBox(width: 6),
        FilledButton(
          onPressed: () {
            final name = _name.text.trim();
            widget.engine.addRobot(
              name: name.isEmpty ? '신규기' : name,
              model: _model,
              zoneRating: _rating.zones,
              reserve: _reserve,
            );
            Navigator.of(context).pop();
          },
          style: FilledButton.styleFrom(
            backgroundColor: AppColors.series1,
            foregroundColor: Colors.white,
          ),
          child: const Text('등록', style: TextStyle(fontSize: 12)),
        ),
      ],
    );
  }
}

/// 로봇 등록 해제 확인 대화상자.
class RemoveRobotDialog extends StatelessWidget {
  const RemoveRobotDialog({
    super.key,
    required this.engine,
    required this.robot,
  });

  final FleetEngine engine;
  final Robot robot;

  static Future<void> show(
    BuildContext context,
    FleetEngine engine,
    Robot robot,
  ) => showDialog<void>(
    context: context,
    builder: (_) => RemoveRobotDialog(engine: engine, robot: robot),
  );

  @override
  Widget build(BuildContext context) {
    final task = robot.taskId == null ? null : engine.tasks[robot.taskId];
    return _DialogShell(
      title: '${robot.id} 등록 해제',
      icon: Icons.remove_circle_outline,
      accent: AppColors.critical,
      body: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            '${robot.id}(${robot.name}, ${robot.model})를 플릿에서 제거합니다.',
            style: const TextStyle(color: AppColors.textSecondary, fontSize: 12.5),
          ),
          const SizedBox(height: 12),
          if (task != null) ...<Widget>[
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
              decoration: BoxDecoration(
                color: AppColors.warning.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(6),
                border: Border.all(
                  color: AppColors.warning.withValues(alpha: 0.45),
                ),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  const Icon(
                    Icons.warning_amber_outlined,
                    size: 14,
                    color: AppColors.warning,
                  ),
                  const SizedBox(width: 7),
                  Expanded(
                    child: Text(
                      '진행 중인 ${task.id}(${(task.progress * 100).toStringAsFixed(0)}%)는 '
                      '안전 종료 후 대기열로 반환되어 다른 로봇에 재할당됩니다.',
                      style: const TextStyle(
                        color: AppColors.warning,
                        fontSize: 11.5,
                        height: 1.4,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 10),
          ],
          const Text(
            '점유 중인 태스크 리스·랙 슬롯·충전소는 모두 회수됩니다.',
            style: TextStyle(color: AppColors.muted, fontSize: 11.5, height: 1.4),
          ),
        ],
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('취소', style: TextStyle(fontSize: 12)),
        ),
        const SizedBox(width: 6),
        FilledButton(
          onPressed: () {
            engine.removeRobot(robot);
            Navigator.of(context).pop();
          },
          style: FilledButton.styleFrom(
            backgroundColor: AppColors.critical,
            foregroundColor: Colors.white,
          ),
          child: const Text('등록 해제', style: TextStyle(fontSize: 12)),
        ),
      ],
    );
  }
}

/// 작업자 등록 대화상자.
class AddWorkerDialog extends StatefulWidget {
  const AddWorkerDialog({super.key, required this.engine});

  final FleetEngine engine;

  static Future<void> show(BuildContext context, FleetEngine engine) =>
      showDialog<void>(
        context: context,
        builder: (_) => AddWorkerDialog(engine: engine),
      );

  @override
  State<AddWorkerDialog> createState() => _AddWorkerDialogState();
}

class _AddWorkerDialogState extends State<AddWorkerDialog> {
  final TextEditingController _name = TextEditingController();
  String _role = '피킹';
  TempZone _zone = TempZone.ambient;

  static const List<String> _roles = <String>['피킹', '검수', '포장', '지게차', '안전 관리'];

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return _DialogShell(
      title: '작업자 등록',
      icon: Icons.person_add_alt,
      accent: AppColors.series5,
      body: Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          _Field(
            label: '이름',
            child: TextField(
              controller: _name,
              autofocus: true,
              style: const TextStyle(color: AppColors.textPrimary, fontSize: 12.5),
              decoration: _inputDecoration('예: 오지훈'),
            ),
          ),
          _Field(
            label: '담당 업무',
            child: _Choices<String>(
              options: _roles,
              labelOf: (r) => r,
              colorOf: (_) => AppColors.series5,
              selected: _role,
              onSelect: (r) => setState(() => _role = r),
            ),
          ),
          _Field(
            label: '배치 구획',
            child: _Choices<TempZone>(
              options: TempZone.values,
              labelOf: (z) => z.label,
              colorOf: AppColors.zoneColor,
              selected: _zone,
              onSelect: (z) => setState(() => _zone = z),
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
            decoration: BoxDecoration(
              color: AppColors.page,
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: AppColors.border),
            ),
            child: const Row(
              children: <Widget>[
                Icon(Icons.shield_outlined, size: 13, color: AppColors.muted),
                SizedBox(width: 7),
                Expanded(
                  child: Text(
                    '등록 즉시 안전 필드 감시 대상이 되어, 주변 로봇이 보호 필드 1.7 m에서 '
                    '정지하고 경고 필드 4 m에서 감속합니다.',
                    style: TextStyle(
                      color: AppColors.muted,
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
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('취소', style: TextStyle(fontSize: 12)),
        ),
        const SizedBox(width: 6),
        FilledButton(
          onPressed: () {
            final name = _name.text.trim();
            widget.engine.addWorker(
              name: name.isEmpty ? '신규 작업자' : name,
              role: _role,
              zone: _zone,
            );
            Navigator.of(context).pop();
          },
          style: FilledButton.styleFrom(
            backgroundColor: AppColors.series5,
            foregroundColor: Colors.white,
          ),
          child: const Text('등록', style: TextStyle(fontSize: 12)),
        ),
      ],
    );
  }
}

/// 작업자 해제 확인 대화상자.
class RemoveWorkerDialog extends StatelessWidget {
  const RemoveWorkerDialog({
    super.key,
    required this.engine,
    required this.worker,
  });

  final FleetEngine engine;
  final Worker worker;

  static Future<void> show(
    BuildContext context,
    FleetEngine engine,
    Worker worker,
  ) => showDialog<void>(
    context: context,
    builder: (_) => RemoveWorkerDialog(engine: engine, worker: worker),
  );

  @override
  Widget build(BuildContext context) {
    return _DialogShell(
      title: '${worker.id} 해제',
      icon: Icons.person_remove_alt_1_outlined,
      accent: AppColors.critical,
      body: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            '${worker.name}(${worker.role}, ${worker.zone.label})를 현장 인원에서 제외합니다.',
            style: const TextStyle(color: AppColors.textSecondary, fontSize: 12.5),
          ),
          const SizedBox(height: 10),
          Text(
            worker.inDistress
                ? '위급 상태로 등록되어 있어, 해제 시 관련 안전 상황도 함께 종료됩니다.'
                : '해당 작업자를 기준으로 계산되던 안전 필드가 사라집니다.',
            style: TextStyle(
              color: worker.inDistress ? AppColors.warning : AppColors.muted,
              fontSize: 11.5,
              height: 1.4,
            ),
          ),
        ],
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('취소', style: TextStyle(fontSize: 12)),
        ),
        const SizedBox(width: 6),
        FilledButton(
          onPressed: () {
            engine.removeWorker(worker);
            Navigator.of(context).pop();
          },
          style: FilledButton.styleFrom(
            backgroundColor: AppColors.critical,
            foregroundColor: Colors.white,
          ),
          child: const Text('해제', style: TextStyle(fontSize: 12)),
        ),
      ],
    );
  }
}
