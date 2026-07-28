import 'dart:async';

import 'package:flutter/material.dart';

import '../services/base/proactive_vision_service_base.dart';
import '../services/config_service.dart';
import '../services/proactive_vision_prompt.dart';
import '../services/proactive_vision_watcher.dart';
import '../services/service_factory.dart';
import '../theme.dart';

class ProactiveVisionPage extends StatefulWidget {
  const ProactiveVisionPage({super.key});

  @override
  State<ProactiveVisionPage> createState() => _ProactiveVisionPageState();
}

class _ProactiveVisionPageState extends State<ProactiveVisionPage> {
  final _configService = ConfigService();
  final _visionService = ServiceFactory.proactiveVisionService;
  final _ollamaUrlController = TextEditingController();
  final _modelController = TextEditingController();
  final _promptController = TextEditingController();
  final _intervalController = TextEditingController();
  final _appSearchController = TextEditingController();
  final List<TextEditingController> _triggerControllers = [];
  StreamSubscription<ProactiveVisionWatcherSnapshot>? _watcherSubscription;
  Timer? _appSearchDebounce;
  final _appSearchQueryNotifier = ValueNotifier<String>('');
  final _appsExpandedNotifier = ValueNotifier<bool>(false);
  final _ignoredAppsRevision = ValueNotifier<int>(0);
  final _appSelectionFilterNotifier = ValueNotifier<_AppSelectionFilter>(
    _AppSelectionFilter.all,
  );
  final _formRevision = ValueNotifier<int>(0);

  GlobalConfig? _config;
  GlobalConfig? _savedConfig;
  ProactiveVisionWatcherSnapshot _watcherSnapshot =
      ServiceFactory.proactiveVisionWatcher.snapshot;
  ProactiveVisionStatus? _status;
  List<InstalledApplicationInfo> _installedApps = const [];
  Set<String> _ignoredApps = {};
  String? _error;
  bool _loading = true;
  bool _saving = false;
  bool _checking = false;
  bool _enabled = false;

  @override
  void initState() {
    super.initState();
    _ollamaUrlController.addListener(_onFormTextChanged);
    _modelController.addListener(_onFormTextChanged);
    _promptController.addListener(_onFormTextChanged);
    _intervalController.addListener(_onFormTextChanged);
    _appSearchController.addListener(_onAppSearchChanged);
    _watcherSubscription = ServiceFactory.proactiveVisionWatcher.stateStream
        .listen((snapshot) {
          if (!mounted) return;
          setState(() => _watcherSnapshot = snapshot);
        });
    _load();
  }

  @override
  void dispose() {
    _watcherSubscription?.cancel();
    _appSearchDebounce?.cancel();
    _appSearchQueryNotifier.dispose();
    _appsExpandedNotifier.dispose();
    _ignoredAppsRevision.dispose();
    _appSelectionFilterNotifier.dispose();
    _formRevision.dispose();
    _ollamaUrlController.dispose();
    _modelController.dispose();
    _promptController.dispose();
    _intervalController.dispose();
    _appSearchController.dispose();
    for (final controller in _triggerControllers) {
      controller.dispose();
    }
    super.dispose();
  }

  void _onFormTextChanged() {
    _formRevision.value += 1;
  }

  void _onAppSearchChanged() {
    _appSearchDebounce?.cancel();
    _appSearchDebounce = Timer(const Duration(milliseconds: 250), () {
      if (!mounted) return;
      _appSearchQueryNotifier.value = _appSearchController.text
          .trim()
          .toLowerCase();
    });
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final config = await _configService.load();
      _ollamaUrlController.text = config.proactiveVisionOllamaUrl;
      _modelController.text = config.proactiveVisionModel;
      _promptController.text = config.proactiveVisionPrompt;
      _intervalController.text = config.proactiveVisionIntervalSeconds
          .toString();
      _setTriggerControllers(config.proactiveVisionTriggers);
      final apps = await _visionService.listInstalledApplications();
      if (!mounted) return;
      setState(() {
        _config = config;
        _savedConfig = config;
        _installedApps = apps;
        _ignoredApps = config.proactiveVisionIgnoredApps.toSet();
        _enabled = config.proactiveVisionEnabled;
        _loading = false;
      });
      await _checkStatus();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _save() async {
    final config = _config;
    if (config == null) return;
    setState(() => _saving = true);
    try {
      final updated = config.copyWith(
        proactiveVisionEnabled: _enabled,
        proactiveVisionOllamaUrl: _ollamaUrlController.text.trim(),
        proactiveVisionModel: _modelController.text.trim(),
        proactiveVisionPrompt: _promptController.text.trim(),
        proactiveVisionIntervalSeconds: _intervalSeconds,
        proactiveVisionTriggers: _triggerList,
        proactiveVisionIgnoredApps: _ignoredAppList,
      );
      await _configService.save(updated);
      if (!mounted) return;
      setState(() {
        _config = updated;
        _savedConfig = updated;
      });
      if (_enabled) {
        ServiceFactory.proactiveVisionWatcher.start(updated);
      } else {
        ServiceFactory.proactiveVisionWatcher.stop();
      }
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('主动视觉配置已保存')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('保存失败：$e')));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _checkStatus() async {
    setState(() {
      _checking = true;
      _error = null;
    });
    try {
      final status = await _visionService.checkStatus(
        ollamaUrl: _ollamaUrl,
        model: _model,
      );
      if (!mounted) return;
      setState(() => _status = status);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  void _setEnabled(bool value) {
    setState(() => _enabled = value);
  }

  GlobalConfig? get _currentConfig {
    final base = _config;
    if (base == null) return null;
    return base.copyWith(
      proactiveVisionEnabled: _enabled,
      proactiveVisionOllamaUrl: _ollamaUrlController.text.trim(),
      proactiveVisionModel: _modelController.text.trim(),
      proactiveVisionPrompt: _promptController.text.trim(),
      proactiveVisionIntervalSeconds: _intervalSeconds,
      proactiveVisionTriggers: _triggerList,
      proactiveVisionIgnoredApps: _ignoredAppList,
    );
  }

  bool get _hasUnsavedChanges {
    final current = _currentConfig;
    return current != null && _savedConfig != null && current != _savedConfig;
  }

  Future<bool> _confirmLeave() async {
    if (!_hasUnsavedChanges) return true;
    final action = await showDialog<_LeaveAction>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('保存更改？'),
        content: const Text('主动视觉配置有未保存的更改，离开前是否保存？'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, _LeaveAction.cancel),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, _LeaveAction.discard),
            child: const Text('不保存'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, _LeaveAction.save),
            child: const Text('保存'),
          ),
        ],
      ),
    );
    if (action == _LeaveAction.save) {
      await _save();
      return !_hasUnsavedChanges;
    }
    return action == _LeaveAction.discard;
  }

  String get _ollamaUrl {
    final value = _ollamaUrlController.text.trim();
    return value.isEmpty ? 'http://127.0.0.1:11434' : value;
  }

  String get _model {
    final value = _modelController.text.trim();
    return value.isEmpty ? 'minicpm-v4.6:latest' : value;
  }

  int get _intervalSeconds {
    final parsed = int.tryParse(_intervalController.text.trim()) ?? 20;
    return parsed.clamp(5, 3600).toInt();
  }

  List<String> get _triggerList {
    final items = _triggerControllers
        .map((controller) => controller.text.trim())
        .where((line) => line.isNotEmpty)
        .toList();
    return items.isEmpty ? [defaultProactiveVisionTriggers.first] : items;
  }

  List<String> get _ignoredAppList {
    final items = _ignoredApps
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty)
        .toList();
    items.sort((a, b) => a.toLowerCase().compareTo(b.toLowerCase()));
    return items;
  }

  List<InstalledApplicationInfo> _filteredInstalledApps(
    String query,
    _AppSelectionFilter filter,
  ) {
    return _installedApps.where((app) {
      final selected = _ignoredApps.contains(_appIgnoreKey(app));
      if (filter == _AppSelectionFilter.selected && !selected) return false;
      if (filter == _AppSelectionFilter.unselected && selected) return false;
      if (query.isEmpty) return true;
      final fields = [
        app.name,
        app.bundleIdentifier,
        ...app.aliases,
      ].map((field) => field.toLowerCase());
      return fields.any((field) => field.contains(query));
    }).toList();
  }

  String _appIgnoreKey(InstalledApplicationInfo app) {
    final bundleIdentifier = app.bundleIdentifier.trim();
    return bundleIdentifier.isNotEmpty ? bundleIdentifier : app.name.trim();
  }

  void _toggleIgnoredApp(InstalledApplicationInfo app, bool selected) {
    final key = _appIgnoreKey(app);
    if (key.isEmpty) return;
    if (selected) {
      _ignoredApps.add(key);
    } else {
      _ignoredApps.remove(key);
    }
    _ignoredAppsRevision.value += 1;
  }

  TextEditingController _createTriggerController(String text) {
    final controller = TextEditingController(text: text);
    controller.addListener(_onFormTextChanged);
    return controller;
  }

  void _setTriggerControllers(List<String> triggers) {
    for (final controller in _triggerControllers) {
      controller.dispose();
    }
    final values = triggers
        .map((trigger) => trigger.trim())
        .where((trigger) => trigger.isNotEmpty)
        .toList();
    _triggerControllers
      ..clear()
      ..addAll(
        (values.isEmpty ? [defaultProactiveVisionTriggers.first] : values).map(
          _createTriggerController,
        ),
      );
  }

  void _addTrigger() {
    setState(() {
      _triggerControllers.add(_createTriggerController(''));
    });
  }

  void _removeTrigger(int index) {
    if (_triggerControllers.length <= 1) return;
    setState(() {
      final removed = _triggerControllers.removeAt(index);
      removed.dispose();
    });
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: !_hasUnsavedChanges,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        final navigator = Navigator.of(context);
        final shouldLeave = await _confirmLeave();
        if (!mounted || !shouldLeave) return;
        navigator.pop();
      },
      child: Scaffold(
        appBar: AppBar(
          title: const Text('主动视觉智能'),
          actions: [
            IconButton(
              tooltip: '重新检测',
              onPressed: _loading || _checking ? null : _checkStatus,
              icon: _checking
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.refresh),
            ),
            const SizedBox(width: 4),
          ],
        ),
        bottomNavigationBar: Padding(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
          child: Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _loading || _checking ? null : _checkStatus,
                  icon: const Icon(Icons.radar_outlined),
                  label: Text(_checking ? '检测中' : '检测能力'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: FilledButton.icon(
                  onPressed: _loading || _saving ? null : _save,
                  icon: _saving
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.save_outlined),
                  label: Text(_saving ? '保存中' : '保存配置'),
                ),
              ),
            ],
          ),
        ),
        body: _buildBody(),
      ),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(
        child: CircularProgressIndicator(color: AppColors.accent),
      );
    }

    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 24),
      children: [
        _statusPanel(),
        const SizedBox(height: 12),
        _configPanel(),
        const SizedBox(height: 12),
        _watcherPanel(),
        if (_error != null) ...[
          const SizedBox(height: 12),
          _messagePanel(Icons.error_outline, '错误', _error!, AppColors.danger),
        ],
      ],
    );
  }

  Widget _statusPanel() {
    final status = _status;
    return Panel(
      borderColor: status?.ready == true
          ? AppColors.success.withValues(alpha: 0.5)
          : AppColors.border,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                ReactorMark(
                  size: 38,
                  icon: status?.ready == true
                      ? Icons.visibility_outlined
                      : Icons.visibility_off_outlined,
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        status?.ready == true ? '主动视觉可用' : '主动视觉待就绪',
                        style: const TextStyle(
                          color: AppColors.textPrimary,
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        status?.message ?? '尚未检测本机能力。',
                        style: const TextStyle(
                          color: AppColors.textSecondary,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 14),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                _statusChip(
                  '平台',
                  _visionService.isSupported ? 'macOS 已接入' : '暂未支持',
                  _visionService.isSupported,
                ),
                _statusChip(
                  'Ollama',
                  status?.ollamaReachable == true ? '在线' : '离线',
                  status?.ollamaReachable == true,
                ),
                _statusChip(
                  '模型',
                  status?.modelAvailable == true ? _model : '未找到',
                  status?.modelAvailable == true,
                ),
                _statusChip(
                  '屏幕录制',
                  status?.screenPermissionGranted == true ? '已授权' : '未授权',
                  status?.screenPermissionGranted == true,
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _configPanel() {
    return Panel(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _sectionTitle(
              Icons.tune_outlined,
              '运行配置',
              '这是旁路增强；关闭或不可用时不会影响语音助手主链路。',
            ),
            const SizedBox(height: 14),
            SwitchListTile.adaptive(
              contentPadding: EdgeInsets.zero,
              title: const Text(
                '启用主动视觉智能',
                style: TextStyle(
                  color: AppColors.textPrimary,
                  fontWeight: FontWeight.w700,
                ),
              ),
              subtitle: const Text(
                '仅在 Ollama、模型和屏幕权限都可用时生效。',
                style: TextStyle(color: AppColors.textMuted, fontSize: 12),
              ),
              value: _enabled,
              activeThumbColor: AppColors.accent,
              activeTrackColor: AppColors.accent.withValues(alpha: 0.35),
              onChanged: _setEnabled,
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _ollamaUrlController,
              decoration: const InputDecoration(
                labelText: 'Ollama 地址',
                prefixIcon: Icon(Icons.http_outlined),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _modelController,
              decoration: const InputDecoration(
                labelText: '视觉模型',
                prefixIcon: Icon(Icons.memory_outlined),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _promptController,
              readOnly: true,
              minLines: 3,
              maxLines: 5,
              decoration: const InputDecoration(
                labelText: '主动视觉提示词模板',
                prefixIcon: Icon(Icons.chat_bubble_outline),
                helperText: '运行时会动态注入当前时间、前台 App 和各场景连续命中状态。',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _intervalController,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: '检查间隔（秒）',
                prefixIcon: Icon(Icons.timer_outlined),
                helperText: '最小 5 秒；保存后后台 watcher 会按新间隔重启。',
              ),
            ),
            const SizedBox(height: 12),
            _ignoredAppsGrid(),
            const SizedBox(height: 12),
            _triggerListEditor(),
          ],
        ),
      ),
    );
  }

  Widget _triggerListEditor() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.rule_outlined, color: AppColors.accent, size: 20),
            const SizedBox(width: 10),
            const Expanded(
              child: Text(
                '主动触发条件',
                style: TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 13,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
            OutlinedButton.icon(
              onPressed: _addTrigger,
              icon: const Icon(Icons.add, size: 18),
              label: const Text('添加'),
            ),
          ],
        ),
        const SizedBox(height: 6),
        const Text(
          'Watcher 会把这些条件写进 MiniCPM-V 判定提示词；至少保留 1 条。',
          style: TextStyle(color: AppColors.textMuted, fontSize: 12),
        ),
        const SizedBox(height: 12),
        ListView.separated(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          itemCount: _triggerControllers.length,
          separatorBuilder: (_, _) => const SizedBox(height: 10),
          itemBuilder: (context, index) {
            final canDelete = _triggerControllers.length > 1;
            return TextField(
              controller: _triggerControllers[index],
              minLines: 1,
              maxLines: 3,
              decoration: InputDecoration(
                labelText: '触发条件 ${index + 1}',
                prefixIcon: const Icon(Icons.drag_indicator_outlined),
                suffixIcon: IconButton(
                  tooltip: canDelete ? '删除触发条件' : '至少保留 1 条',
                  onPressed: canDelete ? () => _removeTrigger(index) : null,
                  icon: const Icon(Icons.delete_outline),
                ),
              ),
            );
          },
        ),
      ],
    );
  }

  Widget _ignoredAppsGrid() {
    return ValueListenableBuilder<int>(
      valueListenable: _ignoredAppsRevision,
      builder: (context, _, _) => ValueListenableBuilder<String>(
        valueListenable: _appSearchQueryNotifier,
        builder: (context, query, _) => ValueListenableBuilder<bool>(
          valueListenable: _appsExpandedNotifier,
          builder: (context, expanded, _) =>
              ValueListenableBuilder<_AppSelectionFilter>(
                valueListenable: _appSelectionFilterNotifier,
                builder: (context, filter, _) {
                  final filteredApps = _filteredInstalledApps(query, filter);
                  final apps = !expanded && query.isEmpty
                      ? <InstalledApplicationInfo>[]
                      : filteredApps;
                  final selectedVisibleCount = _installedApps.where((app) {
                    final key = _appIgnoreKey(app);
                    return key.isNotEmpty && _ignoredApps.contains(key);
                  }).length;
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          const Icon(
                            Icons.visibility_off_outlined,
                            color: AppColors.accent,
                            size: 20,
                          ),
                          const SizedBox(width: 10),
                          const Expanded(
                            child: Text(
                              '忽略应用',
                              style: TextStyle(
                                color: AppColors.textPrimary,
                                fontSize: 13,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                          ),
                          Text(
                            '$selectedVisibleCount 已选',
                            style: const TextStyle(
                              color: AppColors.textMuted,
                              fontSize: 12,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 6),
                      const Text(
                        '主动视觉不会观察已勾选应用；Control Center 和主助手仍会默认忽略。',
                        style: TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 12,
                        ),
                      ),
                      const SizedBox(height: 12),
                      SegmentedButton<_AppSelectionFilter>(
                        segments: const [
                          ButtonSegment(
                            value: _AppSelectionFilter.all,
                            icon: Icon(Icons.apps_outlined),
                            label: Text('全部'),
                          ),
                          ButtonSegment(
                            value: _AppSelectionFilter.selected,
                            icon: Icon(Icons.check_box_outlined),
                            label: Text('已选'),
                          ),
                          ButtonSegment(
                            value: _AppSelectionFilter.unselected,
                            icon: Icon(Icons.check_box_outline_blank),
                            label: Text('未选'),
                          ),
                        ],
                        selected: {filter},
                        onSelectionChanged: (value) {
                          _appSelectionFilterNotifier.value = value.first;
                        },
                      ),
                      const SizedBox(height: 12),
                      ValueListenableBuilder<TextEditingValue>(
                        valueListenable: _appSearchController,
                        builder: (context, value, _) => TextField(
                          controller: _appSearchController,
                          decoration: InputDecoration(
                            labelText: '搜索应用',
                            prefixIcon: const Icon(Icons.search),
                            suffixIcon: value.text.isEmpty
                                ? null
                                : IconButton(
                                    tooltip: '清空搜索',
                                    onPressed: _appSearchController.clear,
                                    icon: const Icon(Icons.close),
                                  ),
                          ),
                        ),
                      ),
                      const SizedBox(height: 12),
                      Row(
                        children: [
                          Text(
                            '${filteredApps.length} 个应用',
                            style: const TextStyle(
                              color: AppColors.textMuted,
                              fontSize: 12,
                            ),
                          ),
                          const Spacer(),
                          IconButton(
                            tooltip: expanded ? '收起应用列表' : '展开应用列表',
                            onPressed: () {
                              _appsExpandedNotifier.value = !expanded;
                            },
                            icon: Icon(
                              expanded
                                  ? Icons.keyboard_arrow_up
                                  : Icons.keyboard_arrow_down,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      if (!expanded && query.isEmpty)
                        const SizedBox.shrink()
                      else if (apps.isEmpty)
                        Container(
                          width: double.infinity,
                          padding: const EdgeInsets.all(14),
                          decoration: BoxDecoration(
                            color: Colors.black.withValues(alpha: 0.12),
                            borderRadius: AppShape.borderRadius,
                            border: Border.all(
                              color: AppColors.borderBright.withValues(
                                alpha: 0.22,
                              ),
                            ),
                          ),
                          child: const Text(
                            '没有匹配的应用。',
                            style: TextStyle(
                              color: AppColors.textSecondary,
                              fontSize: 12,
                            ),
                          ),
                        )
                      else ...[
                        LayoutBuilder(
                          builder: (context, constraints) {
                            final width = constraints.maxWidth;
                            final columns = width >= 1040
                                ? 4
                                : width >= 760
                                ? 3
                                : width >= 500
                                ? 2
                                : 1;
                            return GridView.builder(
                              shrinkWrap: true,
                              physics: const NeverScrollableScrollPhysics(),
                              itemCount: apps.length,
                              gridDelegate:
                                  SliverGridDelegateWithFixedCrossAxisCount(
                                    crossAxisCount: columns,
                                    mainAxisSpacing: 10,
                                    crossAxisSpacing: 10,
                                    mainAxisExtent: 68,
                                  ),
                              itemBuilder: (context, index) {
                                final app = apps[index];
                                final key = _appIgnoreKey(app);
                                final selected = _ignoredApps.contains(key);
                                return _ignoredAppTile(app, selected);
                              },
                            );
                          },
                        ),
                      ],
                    ],
                  );
                },
              ),
        ),
      ),
    );
  }

  Widget _ignoredAppTile(InstalledApplicationInfo app, bool selected) {
    final aliases = app.aliases
        .map((alias) => alias.trim())
        .where((alias) => alias.isNotEmpty && alias != app.name)
        .toList();
    final displayName = aliases.isNotEmpty ? aliases.first : app.name;
    final subtitle = app.bundleIdentifier.trim();
    return InkWell(
      borderRadius: AppShape.borderRadius,
      onTap: () => _toggleIgnoredApp(app, !selected),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(
          color: selected
              ? AppColors.accent.withValues(alpha: 0.15)
              : Colors.black.withValues(alpha: 0.12),
          borderRadius: AppShape.borderRadius,
          border: Border.all(
            color: selected
                ? AppColors.accent.withValues(alpha: 0.5)
                : AppColors.borderBright.withValues(alpha: 0.22),
          ),
        ),
        child: Row(
          children: [
            Icon(
              selected ? Icons.check_box : Icons.check_box_outline_blank,
              color: selected ? AppColors.accent : AppColors.textMuted,
              size: 20,
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    displayName,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: selected
                          ? AppColors.textPrimary
                          : AppColors.textSecondary,
                      fontSize: 13,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  if (subtitle.isNotEmpty) ...[
                    const SizedBox(height: 3),
                    Text(
                      subtitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: AppColors.textMuted,
                        fontSize: 11,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _watcherPanel() {
    final snapshot = _watcherSnapshot;
    final running = snapshot.running;
    return Panel(
      borderColor: running
          ? AppColors.success.withValues(alpha: 0.45)
          : AppColors.border,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _sectionTitle(
              Icons.radar_outlined,
              '后台低频观察',
              '启用后每 $_intervalSeconds 秒采样；未就绪、无变化、隐私场景都会静默跳过。',
            ),
            const SizedBox(height: 14),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                _statusChip('Watcher', running ? '运行中' : '停止', running),
                _statusChip('采样间隔', '${_intervalSeconds}s', true),
                _statusChip(
                  '本轮状态',
                  snapshot.busy ? '处理中' : snapshot.lastMessage,
                  running,
                ),
                _statusChip(
                  '最近采样',
                  snapshot.lastSampleAt == null
                      ? '无'
                      : '${snapshot.lastSampleAt!.hour.toString().padLeft(2, '0')}:${snapshot.lastSampleAt!.minute.toString().padLeft(2, '0')}:${snapshot.lastSampleAt!.second.toString().padLeft(2, '0')}',
                  snapshot.lastSampleAt != null,
                ),
              ],
            ),
            if (snapshot.logs.isNotEmpty) ...[
              const SizedBox(height: 14),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.black.withValues(alpha: 0.18),
                  borderRadius: AppShape.borderRadius,
                  border: Border.all(
                    color: AppColors.borderBright.withValues(alpha: 0.26),
                  ),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final item in snapshot.logs)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 6),
                        child: Text(
                          item,
                          softWrap: true,
                          style: const TextStyle(
                            color: AppColors.textSecondary,
                            fontSize: 12,
                            height: 1.35,
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _sectionTitle(IconData icon, String title, String subtitle) {
    return Row(
      children: [
        Icon(icon, color: AppColors.accent, size: 20),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 14,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 3),
              Text(
                subtitle,
                style: const TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 12,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _statusChip(String label, String value, bool good) {
    final color = good ? AppColors.success : AppColors.warning;
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 360),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.11),
          borderRadius: AppShape.borderRadius,
          border: Border.all(color: color.withValues(alpha: 0.35)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              good ? Icons.check_circle_outline : Icons.info_outline,
              color: color,
              size: 16,
            ),
            const SizedBox(width: 8),
            Text(
              '$label：',
              style: const TextStyle(
                color: AppColors.textSecondary,
                fontSize: 12,
              ),
            ),
            Flexible(
              child: Text(
                value,
                softWrap: false,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  color: color,
                  fontSize: 12,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _messagePanel(IconData icon, String title, String body, Color color) {
    return Panel(
      borderColor: color.withValues(alpha: 0.45),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _sectionTitle(icon, title, '来自本地 Ollama 视觉模型的返回。'),
            const SizedBox(height: 12),
            LayoutBuilder(
              builder: (context, constraints) => ConstrainedBox(
                constraints: BoxConstraints(maxWidth: constraints.maxWidth),
                child: SelectableText(
                  body,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 13,
                    height: 1.55,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

enum _LeaveAction { cancel, discard, save }

enum _AppSelectionFilter { all, selected, unselected }
