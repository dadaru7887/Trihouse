import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import 'rmf_project_config.dart';
import 'workcell_policy_store.dart';

class WorkcellPolicyPage extends StatefulWidget {
  const WorkcellPolicyPage({
    super.key,
    required this.projectName,
    required this.robots,
    required this.onChanged,
  });

  final String? projectName;
  final List<RmfProjectRobot> robots;
  final ValueChanged<List<WorkcellPolicy>> onChanged;

  @override
  State<WorkcellPolicyPage> createState() => _WorkcellPolicyPageState();
}

class _WorkcellPolicyPageState extends State<WorkcellPolicyPage> {
  List<WorkcellPolicy> _policies = const [];
  List<WorkcellPolicy> _globalPolicies = const [];
  bool _loading = false;

  List<RmfProjectRobot> get _workcells =>
      widget.robots.where((robot) => !robot.isMobile).toList();

  @override
  void initState() {
    super.initState();
    _reload();
  }

  @override
  void didUpdateWidget(covariant WorkcellPolicyPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.projectName != widget.projectName) _reload();
  }

  Future<void> _reload() async {
    final project = widget.projectName;
    if (project == null || project.isEmpty) {
      final globals = await loadGlobalWorkcellPolicies();
      if (!mounted) return;
      setState(() {
        _policies = const [];
        _globalPolicies = globals
          ..sort((a, b) => b.createdAt.compareTo(a.createdAt));
      });
      return;
    }
    setState(() => _loading = true);
    final results = await Future.wait([
      loadWorkcellPolicies(project),
      loadGlobalWorkcellPolicies(),
    ]);
    final policies = results[0];
    final globals = results[1];
    if (!mounted) return;
    setState(() {
      _policies = policies..sort((a, b) => b.createdAt.compareTo(a.createdAt));
      _globalPolicies = globals
        ..sort((a, b) => b.createdAt.compareTo(a.createdAt));
      _loading = false;
    });
    widget.onChanged(List.unmodifiable(_policies));
  }

  Future<void> _upload() async {
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: const ['zip'],
      withData: true,
    );
    final file = picked?.files.singleOrNull;
    final bytes = file?.bytes;
    if (file == null || bytes == null || !mounted) return;
    await _registerArchive(file.name, Uint8List.fromList(bytes));
  }

  Future<void> _fromHuggingFace() async {
    final source = await showDialog<_HuggingFaceDraft>(
      context: context,
      builder: (_) => const _HuggingFaceDialog(),
    );
    if (source == null || !mounted) return;
    setState(() => _loading = true);
    try {
      final downloaded = await downloadHuggingFacePolicy(
        repositoryUrl: source.repositoryUrl,
      );
      if (!mounted) return;
      await _registerArchive(
        downloaded.fileName,
        downloaded.bytes,
        sourceRepository: downloaded.repositoryId,
        sourceRevision: downloaded.revision,
      );
    } catch (error) {
      _message('Hugging Face에서 불러오지 못했습니다: $error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _registerArchive(
    String archiveName,
    Uint8List bytes, {
    String? sourceRepository,
    String? sourceRevision,
  }) async {
    final project = widget.projectName;
    if (project == null || project.isEmpty) return;
    final archiveError = validatePolicyArchive(archiveName, bytes);
    if (archiveError != null) {
      _message(archiveError);
      return;
    }
    final draft = await showDialog<_PolicyDraft>(
      context: context,
      builder: (_) => _PolicyUploadDialog(
        archiveName: archiveName,
        archiveBytes: bytes.length,
        workcells: _workcells,
      ),
    );
    if (draft == null || !mounted) return;
    if (_policies.any(
      (policy) => policy.id == '${draft.name}@${draft.version}',
    )) {
      _message('같은 이름과 버전의 Policy가 이미 있습니다.');
      return;
    }
    final policy = WorkcellPolicy(
      name: draft.name,
      version: draft.version,
      objectType: draft.objectType,
      robotModel: draft.robotModel,
      archiveName: archiveName,
      archiveBytes: bytes.length,
      deployedWorkcells: draft.workcells,
      createdAt: DateTime.now(),
      sourceRepository: sourceRepository,
      sourceRevision: sourceRevision,
    );
    await saveWorkcellPolicy(project, policy, bytes);
    await _reload();
    _message('${policy.id} 등록 및 WorkCell 배포가 완료되었습니다.');
  }

  Future<void> _useLocal() async {
    final project = widget.projectName;
    if (project == null) return;
    final current = _policies.map((policy) => policy.id).toSet();
    final models = _workcells.map((robot) => robot.model).toSet();
    final available = _globalPolicies
        .where(
          (policy) =>
              !current.contains(policy.id) &&
              models.contains(policy.robotModel),
        )
        .toList();
    if (available.isEmpty) {
      _message('현재 WorkCell과 호환되는 미사용 로컬 Policy가 없습니다.');
      return;
    }
    final selected = await showDialog<WorkcellPolicy>(
      context: context,
      builder: (dialogContext) => SimpleDialog(
        title: const Text('로컬 Policy 선택'),
        children: [
          for (final policy in available)
            SimpleDialogOption(
              onPressed: () => Navigator.pop(dialogContext, policy),
              child: ListTile(
                title: Text(policy.id),
                subtitle: Text(
                  '모델: ${policy.robotModel} · ZIP ${(policy.archiveBytes / 1024 / 1024).toStringAsFixed(1)}MB',
                ),
              ),
            ),
        ],
      ),
    );
    if (selected == null || !mounted) return;
    final draft = await showDialog<_PolicyBindingDraft>(
      context: context,
      builder: (_) =>
          _PolicyBindingDialog(policy: selected, workcells: _workcells),
    );
    if (draft == null) return;
    await bindWorkcellPolicy(
      project,
      selected.copyWith(
        objectType: draft.objectType,
        deployedWorkcells: draft.workcells,
      ),
    );
    await _reload();
    _message('${selected.id}을 현재 프로젝트에 연결했습니다.');
  }

  Future<void> _remove(WorkcellPolicy policy) async {
    final project = widget.projectName;
    if (project == null) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('프로젝트에서 제거할까요?'),
        content: Text(
          '${policy.id}의 현재 프로젝트 연결만 제거합니다.\n'
          '전역 Policy 원본은 보관되어 다른 프로젝트에서 다시 사용할 수 있습니다.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('프로젝트에서 제거'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await deleteWorkcellPolicy(project, policy);
    await _reload();
    _message('${policy.id}을 현재 프로젝트에서 제거했습니다.');
  }

  Future<void> _showLibrary() async {
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('전역 WorkCell Policy 보관함'),
          content: SizedBox(
            width: 680,
            height: 420,
            child: _globalPolicies.isEmpty
                ? const Center(child: Text('보관된 Policy가 없습니다.'))
                : ListView.builder(
                    itemCount: _globalPolicies.length,
                    itemBuilder: (_, index) {
                      final policy = _globalPolicies[index];
                      return ListTile(
                        leading: const Icon(Icons.inventory_2_outlined),
                        title: Text(policy.id),
                        subtitle: Text(
                          '모델: ${policy.robotModel} · ZIP ${(policy.archiveBytes / 1024 / 1024).toStringAsFixed(1)}MB'
                          '${policy.sourceRepository == null ? '' : '\n${policy.sourceRepository} @ ${policy.sourceRevision}'}',
                        ),
                        trailing: IconButton(
                          tooltip: '전역 원본 삭제',
                          icon: const Icon(Icons.delete_forever_outlined),
                          onPressed: () async {
                            final references = await globalPolicyReferences(
                              policy.id,
                            );
                            if (!dialogContext.mounted) return;
                            if (references.isNotEmpty) {
                              _message(
                                '사용 중이어서 삭제할 수 없습니다: ${references.join(', ')}',
                              );
                              return;
                            }
                            await deleteGlobalWorkcellPolicy(policy);
                            _globalPolicies.removeAt(index);
                            setDialogState(() {});
                            _message('${policy.id} 전역 원본을 삭제했습니다.');
                          },
                        ),
                      );
                    },
                  ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('닫기'),
            ),
          ],
        ),
      ),
    );
    await _reload();
  }

  void _message(String text) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  @override
  Widget build(BuildContext context) {
    final noProject = widget.projectName == null;
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'WorkCell Policy 관리',
                      style: TextStyle(
                        fontSize: 24,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    SizedBox(height: 5),
                    Text('전역 Policy 보관 · 프로젝트별 연결 · WorkCell 배포'),
                  ],
                ),
              ),
              Wrap(
                spacing: 10,
                children: [
                  OutlinedButton.icon(
                    onPressed: noProject || _workcells.isEmpty || _loading
                        ? null
                        : _fromHuggingFace,
                    icon: const Icon(Icons.cloud_download_outlined),
                    label: const Text('Hugging Face에서 불러오기'),
                  ),
                  OutlinedButton.icon(
                    onPressed: noProject || _workcells.isEmpty || _loading
                        ? null
                        : _useLocal,
                    icon: const Icon(Icons.add_link),
                    label: const Text('로컬 Policy 사용'),
                  ),
                  OutlinedButton.icon(
                    onPressed: _loading ? null : _showLibrary,
                    icon: const Icon(Icons.inventory_2_outlined),
                    label: Text('전역 보관함 (${_globalPolicies.length})'),
                  ),
                  FilledButton.icon(
                    onPressed: noProject || _workcells.isEmpty || _loading
                        ? null
                        : _upload,
                    icon: const Icon(Icons.upload_file),
                    label: const Text('Policy ZIP 등록 및 배포'),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 18),
          if (noProject)
            const _Notice('먼저 프로젝트를 열어 주세요.')
          else if (_workcells.isEmpty)
            const _Notice('로봇 메뉴에서 설치 로봇(WorkCell)을 먼저 등록하세요.')
          else if (_loading)
            const Expanded(child: Center(child: CircularProgressIndicator()))
          else if (_policies.isEmpty)
            const Expanded(child: Center(child: Text('등록된 Policy가 없습니다.')))
          else
            Expanded(
              child: ListView.separated(
                itemCount: _policies.length,
                separatorBuilder: (_, _) => const SizedBox(height: 10),
                itemBuilder: (_, index) {
                  final policy = _policies[index];
                  return Card(
                    child: ListTile(
                      leading: CircleAvatar(
                        backgroundColor: policy.isDeployed
                            ? const Color(0xFFDCFCE7)
                            : const Color(0xFFFEF3C7),
                        child: Icon(
                          policy.isDeployed ? Icons.check : Icons.inventory_2,
                        ),
                      ),
                      title: Text(
                        policy.id,
                        style: const TextStyle(fontWeight: FontWeight.w800),
                      ),
                      subtitle: Text(
                        '물품: ${policy.objectType} · 모델: ${policy.robotModel}\n'
                        '배포: ${policy.deployedWorkcells.isEmpty ? '미배포' : policy.deployedWorkcells.join(', ')} '
                        '· ZIP ${(policy.archiveBytes / 1024 / 1024).toStringAsFixed(1)}MB'
                        '${policy.sourceRepository == null ? '' : '\nHugging Face: ${policy.sourceRepository} @ ${policy.sourceRevision}'}',
                      ),
                      isThreeLine: true,
                      trailing: IconButton(
                        tooltip: '현재 프로젝트에서 제거',
                        onPressed: () => _remove(policy),
                        icon: const Icon(Icons.link_off),
                      ),
                    ),
                  );
                },
              ),
            ),
        ],
      ),
    );
  }
}

class _Notice extends StatelessWidget {
  const _Notice(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 24),
    child: Text(text, style: const TextStyle(color: Color(0xFFB45309))),
  );
}

class _HuggingFaceDraft {
  const _HuggingFaceDraft(this.repositoryUrl);
  final String repositoryUrl;
}

class _HuggingFaceDialog extends StatefulWidget {
  const _HuggingFaceDialog();
  @override
  State<_HuggingFaceDialog> createState() => _HuggingFaceDialogState();
}

class _HuggingFaceDialogState extends State<_HuggingFaceDialog> {
  final _repository = TextEditingController();

  @override
  void dispose() {
    _repository.dispose();
    super.dispose();
  }

  void _submit() {
    if (parseHuggingFaceRepository(_repository.text) == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('올바른 Hugging Face 모델 주소를 입력하세요.')),
      );
      return;
    }
    Navigator.pop(context, _HuggingFaceDraft(_repository.text.trim()));
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Hugging Face에서 Policy 불러오기'),
    content: SizedBox(
      width: 520,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(
            controller: _repository,
            autofocus: true,
            decoration: const InputDecoration(
              labelText: 'Hugging Face 모델 주소 *',
              hintText: 'https://huggingface.co/owner/policy',
              helperText: '주소를 입력하면 저장소의 policy 파일을 자동으로 내려받습니다.',
            ),
          ),
          const SizedBox(height: 12),
          const Align(
            alignment: Alignment.centerLeft,
            child: Text(
              '비공개 저장소는 앱 실행 환경에 HF_TOKEN을 설정하세요. '
              '토큰은 Policy 정보에 저장되지 않습니다.',
              style: TextStyle(fontSize: 12, color: Color(0xFF64748B)),
            ),
          ),
        ],
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('취소'),
      ),
      FilledButton(onPressed: _submit, child: const Text('다운로드')),
    ],
  );
}

class _PolicyDraft {
  const _PolicyDraft(
    this.name,
    this.version,
    this.objectType,
    this.robotModel,
    this.workcells,
  );
  final String name;
  final String version;
  final String objectType;
  final String robotModel;
  final List<String> workcells;
}

class _PolicyBindingDraft {
  const _PolicyBindingDraft(this.objectType, this.workcells);
  final String objectType;
  final List<String> workcells;
}

class _PolicyBindingDialog extends StatefulWidget {
  const _PolicyBindingDialog({required this.policy, required this.workcells});
  final WorkcellPolicy policy;
  final List<RmfProjectRobot> workcells;

  @override
  State<_PolicyBindingDialog> createState() => _PolicyBindingDialogState();
}

class _PolicyBindingDialogState extends State<_PolicyBindingDialog> {
  final _object = TextEditingController();
  final Set<String> _targets = {};

  @override
  void dispose() {
    _object.dispose();
    super.dispose();
  }

  void _submit() {
    if (_object.text.trim().isEmpty || _targets.isEmpty) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('물품과 배포할 WorkCell을 선택하세요.')));
      return;
    }
    Navigator.pop(
      context,
      _PolicyBindingDraft(_object.text.trim(), _targets.toList()),
    );
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text('${widget.policy.id} 프로젝트 연결'),
    content: SizedBox(
      width: 520,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(
            controller: _object,
            decoration: const InputDecoration(labelText: '집을 물품 *'),
          ),
          const SizedBox(height: 12),
          for (final cell in widget.workcells.where(
            (cell) => cell.model == widget.policy.robotModel,
          ))
            CheckboxListTile(
              value: _targets.contains(cell.robotId),
              title: Text('${cell.displayName} (${cell.robotId})'),
              onChanged: (checked) => setState(() {
                if (checked == true) {
                  _targets.add(cell.robotId);
                } else {
                  _targets.remove(cell.robotId);
                }
              }),
            ),
        ],
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('취소'),
      ),
      FilledButton(onPressed: _submit, child: const Text('연결 및 배포')),
    ],
  );
}

class _PolicyUploadDialog extends StatefulWidget {
  const _PolicyUploadDialog({
    required this.archiveName,
    required this.archiveBytes,
    required this.workcells,
  });
  final String archiveName;
  final int archiveBytes;
  final List<RmfProjectRobot> workcells;
  @override
  State<_PolicyUploadDialog> createState() => _PolicyUploadDialogState();
}

class _PolicyUploadDialogState extends State<_PolicyUploadDialog> {
  final _name = TextEditingController();
  final _version = TextEditingController(text: '1.0.0');
  final _object = TextEditingController();
  String? _model;
  final Set<String> _targets = {};

  List<String> get _models =>
      widget.workcells.map((e) => e.model).toSet().toList();

  @override
  void initState() {
    super.initState();
    _model = _models.firstOrNull;
  }

  @override
  void dispose() {
    _name.dispose();
    _version.dispose();
    _object.dispose();
    super.dispose();
  }

  void _submit() {
    final error = validatePolicyName(_name.text);
    if (error != null ||
        _version.text.trim().isEmpty ||
        _object.text.trim().isEmpty ||
        _model == null ||
        _targets.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(error ?? '버전·물품·로봇 모델을 입력하고 배포할 WorkCell을 선택하세요.'),
        ),
      );
      return;
    }
    Navigator.pop(
      context,
      _PolicyDraft(
        _name.text.trim(),
        _version.text.trim(),
        _object.text.trim(),
        _model!,
        _targets.toList(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Policy 등록 및 배포'),
    content: SizedBox(
      width: 560,
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.folder_zip_outlined),
              title: Text(widget.archiveName),
              subtitle: Text(
                '${(widget.archiveBytes / 1024 / 1024).toStringAsFixed(1)}MB · ZIP 형식 확인 완료',
              ),
            ),
            TextField(
              controller: _name,
              decoration: const InputDecoration(labelText: 'Policy 이름 *'),
            ),
            TextField(
              controller: _version,
              decoration: const InputDecoration(labelText: '버전 *'),
            ),
            TextField(
              controller: _object,
              decoration: const InputDecoration(labelText: '집을 물품 *'),
            ),
            DropdownButtonFormField<String>(
              initialValue: _model,
              decoration: const InputDecoration(labelText: '호환 로봇팔 모델 *'),
              items: [
                for (final model in _models)
                  DropdownMenuItem(value: model, child: Text(model)),
              ],
              onChanged: (value) => setState(() => _model = value),
            ),
            const SizedBox(height: 14),
            const Align(
              alignment: Alignment.centerLeft,
              child: Text(
                '배포할 WorkCell *',
                style: TextStyle(fontWeight: FontWeight.w800),
              ),
            ),
            for (final cell in widget.workcells.where(
              (cell) => cell.model == _model,
            ))
              CheckboxListTile(
                value: _targets.contains(cell.robotId),
                title: Text('${cell.displayName} (${cell.robotId})'),
                subtitle: Text(cell.dataSource.label),
                onChanged: (checked) => setState(() {
                  if (checked == true) {
                    _targets.add(cell.robotId);
                  } else {
                    _targets.remove(cell.robotId);
                  }
                }),
              ),
          ],
        ),
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('취소'),
      ),
      FilledButton(onPressed: _submit, child: const Text('등록 및 배포')),
    ],
  );
}
