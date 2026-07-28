import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

import 'base/proactive_vision_service_base.dart';
import 'config_service.dart';

class ProactiveVisionWatcher {
  static const _triggerConfidenceThreshold = 0.75;
  static const _assistantApiUrl = 'http://127.0.0.1:18790/proactive-command';
  static const _privacyBlockedApps = {
    'Control Center',
    'control_center',
    '语音助手控制中心',
    'ASSISTANT-X-OPENCLAW',
    'Assistant-X-OpenClaw',
    'assistant-x-openclaw',
    '1Password',
    'Keychain Access',
    'Passwords',
    'System Settings',
    'System Preferences',
  };
  static const _privacyBlockedBundleIdentifiers = {
    'cn.rubintry.assistant.ctrl.center.controlCenter',
    'com.jarvis.control-center',
  };

  final ConfigService _configService;
  final ProactiveVisionServiceBase _visionService;
  final void Function(String message)? onLog;
  final _stateController =
      StreamController<ProactiveVisionWatcherSnapshot>.broadcast();

  Timer? _timer;
  bool _running = false;
  bool _busy = false;
  int? _lastScreenSignature;
  DateTime? _lastSampleAt;
  final _durationStates = <String, _DurationHitState>{};
  String _lastMessage = '未启动';
  final _logs = <String>[];
  GlobalConfig? _config;

  ProactiveVisionWatcher({
    required ConfigService configService,
    required ProactiveVisionServiceBase visionService,
    this.onLog,
  }) : _configService = configService,
       _visionService = visionService;

  bool get isRunning => _running;

  ProactiveVisionWatcherSnapshot get snapshot => ProactiveVisionWatcherSnapshot(
    running: _running,
    busy: _busy,
    lastSampleAt: _lastSampleAt,
    lastMessage: _lastMessage,
    logs: List.unmodifiable(_logs),
  );

  Stream<ProactiveVisionWatcherSnapshot> get stateStream =>
      _stateController.stream;

  Future<void> startFromSavedConfig() async {
    _log('主动视觉启动检查：读取配置');
    final config = await _configService.load();
    if (!config.proactiveVisionEnabled) {
      stop();
      _log('主动视觉未启用，随助手启动跳过');
      return;
    }
    start(config);
  }

  void start(GlobalConfig config) {
    if (_running &&
        _config?.proactiveVisionOllamaUrl == config.proactiveVisionOllamaUrl &&
        _config?.proactiveVisionModel == config.proactiveVisionModel &&
        _config?.proactiveVisionIntervalSeconds ==
            config.proactiveVisionIntervalSeconds &&
        _listEquals(
          _config?.proactiveVisionTriggers ?? const [],
          config.proactiveVisionTriggers,
        ) &&
        _listEquals(
          _config?.proactiveVisionIgnoredApps ?? const [],
          config.proactiveVisionIgnoredApps,
        )) {
      _log('主动视觉已在运行，保持当前 watcher');
      return;
    }
    stop();
    _config = config;
    _running = true;
    _log('主动视觉随助手启动，采样间隔 ${_interval.inSeconds}s');
    _runTick();
    _timer = Timer.periodic(_interval, (_) => _runTick());
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
    _running = false;
    _busy = false;
    _resetDurationStates();
    _lastMessage = '未启动';
    _emitState();
  }

  Duration get _interval {
    final seconds = (_config?.proactiveVisionIntervalSeconds ?? 20).clamp(
      5,
      3600,
    );
    return Duration(seconds: seconds);
  }

  Future<void> _runTick() async {
    final config = _config;
    if (!_running || _busy || config == null) return;
    _busy = true;
    _lastSampleAt = DateTime.now();
    _lastMessage = '采样中';
    _log('主动视觉采样中');
    _emitState();
    try {
      final status = await _visionService.checkStatus(
        ollamaUrl: config.proactiveVisionOllamaUrl,
        model: config.proactiveVisionModel,
      );
      if (!status.ready) {
        _log('主动视觉能力未就绪，静默跳过：${status.message}');
        return;
      }

      final foreground = await _visionService.getForegroundAppInfo();
      if (_isPrivacyBlocked(foreground, config)) {
        _log('主动视觉跳过前台 App：${foreground.name}');
        return;
      }
      if (await _maybeDispatchElapsedDurationHit(config, foreground)) {
        return;
      }
      _resetContinuousHitIfForegroundChanged(config, foreground);

      final snapshot = await _visionService.captureScreenSnapshot();
      if (_lastScreenSignature == snapshot.signature) {
        if (await _maybeDispatchUnchangedDurationHit(config)) {
          return;
        }
        final waitingMessage = _durationWaitingMessage(config);
        _log(waitingMessage ?? '主动视觉屏幕变化不明显，跳过');
        return;
      }
      _lastScreenSignature = snapshot.signature;

      _log('主动视觉主人在场判断暂未实现：本轮仅打印占位，不拦截');
      debugPrint('[主动视觉] owner-present check placeholder: not enforced');

      final result = await _visionService.analyzeSnapshot(
        ollamaUrl: config.proactiveVisionOllamaUrl,
        model: config.proactiveVisionModel,
        prompt: _watcherPrompt(config, foreground),
        pngBytes: snapshot.pngBytes,
      );
      final decision = _parseDecision(result.response);
      if (!decision.shouldTrigger) {
        if (!_hasActiveDurationHitFor(config, foreground)) {
          _resetDurationStatesForForeground(config, foreground);
        }
        _log(
          '主动视觉未触发：${decision.summary.isEmpty ? '模型未给出触发事件' : decision.summary}',
        );
        return;
      }

      _log(
        '主动视觉命中 ${decision.confidence.toStringAsFixed(2)}：${decision.summary}',
      );
      final gate = _durationGate(config, decision, foreground);
      if (!gate.allowed) {
        _log(gate.message);
        return;
      }
      _log('主动视觉持续条件已满足，准备唤醒 Jarvis');
      if (await _dispatchTrigger(decision)) {
        _resetDurationState(gate.triggerKey);
      }
    } catch (e) {
      _log('主动视觉本轮异常，静默跳过：$e');
    } finally {
      _busy = false;
      _emitState();
    }
  }

  bool _isPrivacyBlocked(ForegroundAppInfo app, GlobalConfig config) {
    final bundleIdentifier = app.bundleIdentifier.trim();
    if (bundleIdentifier.isNotEmpty &&
        _privacyBlockedBundleIdentifiers.contains(bundleIdentifier)) {
      return true;
    }
    final name = app.name.trim();
    final ignored = {
      ..._privacyBlockedApps,
      ...config.proactiveVisionIgnoredApps,
    };
    if (bundleIdentifier.isNotEmpty &&
        ignored.any((item) => item.trim() == bundleIdentifier)) {
      return true;
    }
    if (name.isEmpty) return false;
    final lowerName = name.toLowerCase();
    return ignored.any((blocked) {
      final lowerBlocked = blocked.toLowerCase();
      if (lowerBlocked.isEmpty) return false;
      return lowerName == lowerBlocked || lowerName.contains(lowerBlocked);
    });
  }

  String _watcherPrompt(GlobalConfig config, ForegroundAppInfo app) {
    final appText = app.name.isEmpty ? '未知 App' : app.name;
    final triggers = config.proactiveVisionTriggers
        .asMap()
        .entries
        .map((entry) => '${entry.key + 1}. ${entry.value}')
        .join('\n');
    return '''
你是 Jarvis 的主动视觉守门员。当前前台 App：$appText。

任务：判断当前屏幕是否满足“需要主动提醒主人或触发 Agent 指令”的关键条件。
触发条件列表：
$triggers

忽略：普通网页浏览、静态桌面、无明显变化的代码/文档、广告、低价值通知。

时长要求：
- 如果触发条件包含“30分钟以上、2小时以上、持续 N 分钟”等时长要求，只判断当前画面是否属于该场景。
- 不要根据单张截图断言已经达到持续时长；持续时长由外层 watcher 统计。
- 这类场景尚未达到时长时，也可以返回 trigger=true 表示“当前画面属于该场景”，summary 必须写成“用户正在……”，不要写“已经持续……分钟”。

人称要求：
- summary 必须使用第三人称描述，例如“用户正在……，满足……条件”。
- command 如果需要填写，也必须使用“用户/主人”，不要使用“你/我/我看到/提醒你”。
- 不要把“你”用来指代主人，因为后续接收者是 Jarvis 或其他 Agent。

请只返回 JSON，不要返回 Markdown：
{
  "trigger": true 或 false,
  "trigger_index": 命中的触发条件序号，从 1 开始；不确定时可省略,
  "confidence": 0.0 到 1.0,
  "action": "speak" 或 "agent_command" 或 "none",
  "summary": "用户正在……，因此满足……条件",
  "command": "可选，用第三人称写给主人或 Agent 的简短指令"
}
''';
  }

  _VisionDecision _parseDecision(String response) {
    final sanitized = _removeThinkBlocks(response);
    for (final candidate in _jsonObjectCandidates(
      sanitized,
    ).toList().reversed) {
      try {
        final decoded =
            jsonDecode(_stripJsonLineComments(candidate))
                as Map<String, dynamic>;
        final decision = _decisionFromMap(decoded);
        if (decision != null) return decision;
      } catch (_) {
        continue;
      }
    }
    for (final candidate in _jsonObjectCandidates(response).toList().reversed) {
      try {
        final decoded =
            jsonDecode(_stripJsonLineComments(candidate))
                as Map<String, dynamic>;
        final decision = _decisionFromMap(decoded);
        if (decision != null) return decision;
      } catch (_) {
        continue;
      }
    }
    final looseDecision = _parseLooseDecision(response);
    if (looseDecision != null) return looseDecision;
    return _VisionDecision.noop(response);
  }

  String _removeThinkBlocks(String response) {
    return response.replaceAll(
      RegExp(r'<think>[\s\S]*?</think>', caseSensitive: false),
      '',
    );
  }

  _VisionDecision? _decisionFromMap(Map<String, dynamic> decoded) {
    if (!decoded.containsKey('trigger') &&
        !decoded.containsKey('confidence') &&
        !decoded.containsKey('summary')) {
      return null;
    }
    return _VisionDecision(
      trigger: decoded['trigger'] == true,
      confidence: _readConfidence(decoded['confidence']),
      triggerIndex: _readTriggerIndex(decoded),
      action: decoded['action']?.toString() ?? 'none',
      summary: decoded['summary']?.toString() ?? '',
      command: decoded['command']?.toString() ?? '',
    );
  }

  _VisionDecision? _parseLooseDecision(String response) {
    final triggerMatch = RegExp(
      r'["“]?trigger["”]?\s*[:：]\s*(true|false)',
      caseSensitive: false,
    ).allMatches(response).lastOrNull;
    final confidenceMatch = RegExp(
      r'["“]?confidence["”]?\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)',
      caseSensitive: false,
    ).allMatches(response).lastOrNull;
    if (triggerMatch == null && confidenceMatch == null) return null;
    return _VisionDecision(
      trigger: (triggerMatch?.group(1) ?? '').toLowerCase() == 'true',
      confidence: _readConfidence(confidenceMatch?.group(1)),
      triggerIndex: _readLooseTriggerIndex(response),
      action: _lastLooseStringField(response, 'action') ?? 'none',
      summary: _lastLooseStringField(response, 'summary') ?? response.trim(),
      command: _lastLooseStringField(response, 'command') ?? '',
    );
  }

  String? _lastLooseStringField(String response, String field) {
    final pattern = RegExp(
      '["“]?$field["”]?\\s*[:：]\\s*["“]([^"”\\n\\r]*)["”]',
      caseSensitive: false,
    );
    final matches = pattern.allMatches(response).toList();
    if (matches.isEmpty) return null;
    final value = matches.last.group(1)?.trim();
    return value == null || value.isEmpty ? null : value;
  }

  Iterable<String> _jsonObjectCandidates(String response) sync* {
    var depth = 0;
    var start = -1;
    var inString = false;
    var escaping = false;

    for (var i = 0; i < response.length; i++) {
      final char = response[i];
      if (inString) {
        if (escaping) {
          escaping = false;
        } else if (char == r'\') {
          escaping = true;
        } else if (char == '"') {
          inString = false;
        }
        continue;
      }

      if (char == '"') {
        inString = true;
      } else if (char == '{') {
        if (depth == 0) start = i;
        depth += 1;
      } else if (char == '}') {
        if (depth == 0) continue;
        depth -= 1;
        if (depth == 0 && start >= 0) {
          yield response.substring(start, i + 1);
          start = -1;
        }
      }
    }
  }

  String _stripJsonLineComments(String candidate) {
    final buffer = StringBuffer();
    var inString = false;
    var escaping = false;

    for (var i = 0; i < candidate.length; i++) {
      final char = candidate[i];
      if (inString) {
        buffer.write(char);
        if (escaping) {
          escaping = false;
        } else if (char == r'\') {
          escaping = true;
        } else if (char == '"') {
          inString = false;
        }
        continue;
      }

      if (char == '"') {
        inString = true;
        buffer.write(char);
      } else if (char == '/' &&
          i + 1 < candidate.length &&
          candidate[i + 1] == '/') {
        while (i < candidate.length && candidate[i] != '\n') {
          i += 1;
        }
        if (i < candidate.length) buffer.write('\n');
      } else {
        buffer.write(char);
      }
    }

    return buffer.toString();
  }

  double _readConfidence(Object? value) {
    if (value is num) return value.toDouble();
    final parsed = double.tryParse(value?.toString() ?? '');
    if (parsed == null) return 0;
    return parsed;
  }

  int? _readTriggerIndex(Map<String, dynamic> decoded) {
    final value = decoded['trigger_index'] ?? decoded['triggerIndex'];
    if (value is int) return value;
    return int.tryParse(value?.toString() ?? '');
  }

  int? _readLooseTriggerIndex(String response) {
    final match = RegExp(
      r'["“]?(trigger_index|triggerIndex)["”]?\s*[:：]\s*([0-9]+)',
      caseSensitive: false,
    ).allMatches(response).lastOrNull;
    return int.tryParse(match?.group(2) ?? '');
  }

  _DurationGateResult _durationGate(
    GlobalConfig config,
    _VisionDecision decision,
    ForegroundAppInfo app,
  ) {
    final requirements = _matchingDurationRequirements(config, decision);
    if (requirements.isEmpty) {
      return const _DurationGateResult.allowed();
    }

    final now = DateTime.now();
    _DurationRequirement? closestRequirement;
    _DurationHitState? closestState;
    Duration? closestRemaining;
    for (final requirement in requirements) {
      final key = _durationHitKey(requirement, app);
      final state = _durationStates.putIfAbsent(
        key,
        () => _DurationHitState(startedAt: now),
      );
      state
        ..decision = decision
        ..foregroundApp = app
        ..trigger = requirement.trigger;
      final elapsed = now.difference(state.startedAt);
      if (elapsed >= requirement.duration) {
        return _DurationGateResult.allowed(triggerKey: key);
      }
      final remaining = requirement.duration - elapsed;
      if (closestRemaining == null || remaining < closestRemaining) {
        closestRemaining = remaining;
        closestRequirement = requirement;
        closestState = state;
      }
    }

    final elapsed = now.difference(closestState!.startedAt);
    return _DurationGateResult.blocked(
      '主动视觉场景「${closestRequirement!.trigger}」连续命中 ${_formatDuration(elapsed)}，未达到触发条件要求的 ${_formatDuration(closestRequirement.duration)}',
    );
  }

  String? _durationWaitingMessage(GlobalConfig config) {
    final active = _activeDurationStates(config);
    if (active.isEmpty) return null;
    final entry = active.first;
    final elapsed = DateTime.now().difference(entry.value.startedAt);
    final required = entry.key.duration;
    if (elapsed >= required) {
      return '主动视觉场景「${entry.key.trigger}」已连续命中 ${_formatDuration(elapsed)}，等待下一轮触发';
    }
    return '主动视觉场景「${entry.key.trigger}」连续命中 ${_formatDuration(elapsed)}，未达到 ${_formatDuration(required)}';
  }

  Future<bool> _maybeDispatchUnchangedDurationHit(GlobalConfig config) async {
    return _maybeDispatchReadyDurationState(config, null);
  }

  Future<bool> _maybeDispatchElapsedDurationHit(
    GlobalConfig config,
    ForegroundAppInfo app,
  ) async {
    return _maybeDispatchReadyDurationState(config, app);
  }

  Future<bool> _maybeDispatchReadyDurationState(
    GlobalConfig config,
    ForegroundAppInfo? app,
  ) async {
    final now = DateTime.now();
    for (final requirement in _durationRequirements(
      config.proactiveVisionTriggers,
    )) {
      final states = _durationStates.entries.where((entry) {
        final state = entry.value;
        if (state.trigger != requirement.trigger) return false;
        final stateApp = state.foregroundApp;
        if (stateApp == null || state.decision?.shouldTrigger != true) {
          return false;
        }
        if (app != null && entry.key != _durationHitKey(requirement, app)) {
          return false;
        }
        return now.difference(state.startedAt) >= requirement.duration;
      }).toList();
      if (states.isEmpty) continue;

      final entry = states.first;
      final decision = entry.value.decision!;
      _log('主动视觉场景「${requirement.trigger}」已达时长，使用持续观察记录触发：${decision.summary}');
      if (await _dispatchTrigger(decision)) {
        _resetDurationState(entry.key);
      }
      return true;
    }
    return false;
  }

  bool _hasActiveDurationHitFor(GlobalConfig config, ForegroundAppInfo app) {
    return _durationRequirements(config.proactiveVisionTriggers).any(
      (requirement) =>
          _durationStates.containsKey(_durationHitKey(requirement, app)),
    );
  }

  void _resetContinuousHitIfForegroundChanged(
    GlobalConfig config,
    ForegroundAppInfo app,
  ) {
    _resetDurationStatesExceptForeground(config, app);
  }

  List<_DurationRequirement> _durationRequirements(List<String> triggers) {
    final result = <_DurationRequirement>[];
    for (var i = 0; i < triggers.length; i++) {
      final trigger = triggers[i];
      final duration = _parseDurationRequirement(trigger);
      if (duration != null) {
        result.add(
          _DurationRequirement(
            index: i + 1,
            trigger: trigger,
            duration: duration,
          ),
        );
      }
    }
    return result;
  }

  List<_DurationRequirement> _matchingDurationRequirements(
    GlobalConfig config,
    _VisionDecision decision,
  ) {
    final requirements = _durationRequirements(config.proactiveVisionTriggers);
    final triggerIndex = decision.triggerIndex;
    if (triggerIndex == null) return requirements;
    final matched = requirements
        .where((requirement) => requirement.index == triggerIndex)
        .toList();
    return matched.isEmpty ? requirements : matched;
  }

  Duration? _parseDurationRequirement(String text) {
    final patterns = [
      RegExp(
        r'(\d+(?:\.\d+)?)\s*(分钟|分|min|mins|minute|minutes)',
        caseSensitive: false,
      ),
      RegExp(
        r'(\d+(?:\.\d+)?)\s*(小时|个小时|h|hr|hrs|hour|hours)',
        caseSensitive: false,
      ),
    ];
    for (final pattern in patterns) {
      final match = pattern.firstMatch(text);
      if (match == null) continue;
      final value = double.tryParse(match.group(1) ?? '');
      final unit = match.group(2)?.toLowerCase() ?? '';
      if (value == null || value <= 0) continue;
      if (unit.contains('小') ||
          unit == 'h' ||
          unit.startsWith('hr') ||
          unit.startsWith('hour')) {
        return Duration(seconds: (value * 3600).round());
      }
      return Duration(seconds: (value * 60).round());
    }
    return null;
  }

  Iterable<MapEntry<_DurationRequirement, _DurationHitState>>
  _activeDurationStates(GlobalConfig config) sync* {
    for (final requirement in _durationRequirements(
      config.proactiveVisionTriggers,
    )) {
      for (final entry in _durationStates.entries) {
        if (entry.value.trigger == requirement.trigger) {
          yield MapEntry(requirement, entry.value);
        }
      }
    }
  }

  String _durationHitKey(
    _DurationRequirement requirement,
    ForegroundAppInfo app,
  ) {
    final appKey = app.bundleIdentifier.trim().isNotEmpty
        ? app.bundleIdentifier.trim()
        : app.name.trim();
    final triggerKey = requirement.trigger.trim().toLowerCase();
    return '$appKey|$triggerKey';
  }

  void _resetDurationState(String key) {
    _durationStates.remove(key);
  }

  void _resetDurationStates() {
    _durationStates.clear();
  }

  void _resetDurationStatesForForeground(
    GlobalConfig config,
    ForegroundAppInfo app,
  ) {
    final keys = _durationRequirements(
      config.proactiveVisionTriggers,
    ).map((requirement) => _durationHitKey(requirement, app)).toSet();
    _durationStates.removeWhere((key, _) => keys.contains(key));
  }

  void _resetDurationStatesExceptForeground(
    GlobalConfig config,
    ForegroundAppInfo app,
  ) {
    final keys = _durationRequirements(
      config.proactiveVisionTriggers,
    ).map((requirement) => _durationHitKey(requirement, app)).toSet();
    _durationStates.removeWhere((key, _) => !keys.contains(key));
  }

  String _formatDuration(Duration duration) {
    if (duration.inHours > 0) {
      final minutes = duration.inMinutes.remainder(60);
      return minutes == 0
          ? '${duration.inHours}小时'
          : '${duration.inHours}小时$minutes分钟';
    }
    if (duration.inMinutes > 0) return '${duration.inMinutes}分钟';
    return '${duration.inSeconds}秒';
  }

  Future<bool> _dispatchTrigger(_VisionDecision decision) async {
    final summary = decision.summary.trim().isEmpty
        ? '用户当前屏幕上可能有需要处理的事情，满足主动视觉触发条件。'
        : decision.summary.trim();
    final command = decision.command.trim();
    final conditionText = command.isNotEmpty
        ? '$summary；建议动作：$command'
        : summary;
    final instruction = '以下是由主动视觉检测到的内容：$conditionText';
    try {
      final token = await _readAssistantApiToken();
      if (token.isEmpty) {
        _log('主动视觉投递失败：语音助手 API token 不可用');
        return false;
      }
      final client = HttpClient();
      final request = await client
          .postUrl(Uri.parse(_assistantApiUrl))
          .timeout(const Duration(seconds: 2));
      final body = utf8.encode(
        jsonEncode({
          'assistant_id': 'jarvis',
          'text': instruction,
          'source': 'proactive_vision',
          'summary': summary,
          'action': decision.action,
          'confidence': decision.confidence,
        }),
      );
      request.headers.contentType = ContentType.json;
      request.headers.set('X-Assistant-Token', token);
      request.contentLength = body.length;
      request.add(body);
      final response = await request.close().timeout(
        const Duration(seconds: 3),
      );
      final responseText = await response.transform(utf8.decoder).join();
      client.close(force: true);
      _log(
        response.statusCode == 200
            ? '主动视觉已真实唤醒 Jarvis 并投递指令'
            : '主动视觉投递失败：HTTP ${response.statusCode} ${responseText.trim()}',
      );
      return response.statusCode == 200;
    } catch (_) {
      _log('主动视觉投递失败：语音助手 API 未连接');
      return false;
    }
  }

  Future<String> _readAssistantApiToken() async {
    final home =
        Platform.environment['HOME'] ??
        Platform.environment['USERPROFILE'] ??
        '';
    final path = Platform.isWindows
        ? '$home\\.openclaw\\workspace\\voice-assistant\\assistant-x-openclaw\\data\\runtime\\local_api.token'
        : '$home/.openclaw/workspace/voice-assistant/assistant-x-openclaw/data/runtime/local_api.token';
    try {
      return (await File(path).readAsString()).trim();
    } catch (_) {
      return '';
    }
  }

  void _log(String message) {
    final now = DateTime.now();
    final ts =
        '${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}:${now.second.toString().padLeft(2, '0')}';
    _lastMessage = message;
    _logs.insert(0, '[$ts] $message');
    if (_logs.length > 16) {
      _logs.removeRange(16, _logs.length);
    }
    onLog?.call(message);
    debugPrint(message);
    _emitState();
  }

  void _emitState() {
    if (!_stateController.isClosed) {
      _stateController.add(snapshot);
    }
  }
}

class ProactiveVisionWatcherSnapshot {
  final bool running;
  final bool busy;
  final DateTime? lastSampleAt;
  final String lastMessage;
  final List<String> logs;

  const ProactiveVisionWatcherSnapshot({
    required this.running,
    required this.busy,
    required this.lastSampleAt,
    required this.lastMessage,
    required this.logs,
  });
}

bool _listEquals<T>(List<T> a, List<T> b) {
  if (identical(a, b)) return true;
  if (a.length != b.length) return false;
  for (var i = 0; i < a.length; i++) {
    if (a[i] != b[i]) return false;
  }
  return true;
}

class _VisionDecision {
  final bool trigger;
  final double confidence;
  final int? triggerIndex;
  final String action;
  final String summary;
  final String command;

  const _VisionDecision({
    required this.trigger,
    required this.confidence,
    this.triggerIndex,
    required this.action,
    required this.summary,
    required this.command,
  });

  factory _VisionDecision.noop(String summary) {
    return _VisionDecision(
      trigger: false,
      confidence: 0,
      triggerIndex: null,
      action: 'none',
      summary: summary.trim(),
      command: '',
    );
  }

  bool get shouldTrigger =>
      trigger &&
      confidence >= ProactiveVisionWatcher._triggerConfidenceThreshold;
}

class _DurationRequirement {
  final int index;
  final String trigger;
  final Duration duration;

  const _DurationRequirement({
    required this.index,
    required this.trigger,
    required this.duration,
  });
}

class _DurationGateResult {
  final bool allowed;
  final String message;
  final String triggerKey;

  const _DurationGateResult._({
    required this.allowed,
    required this.message,
    required this.triggerKey,
  });

  const _DurationGateResult.allowed({String triggerKey = ''})
    : this._(allowed: true, message: '', triggerKey: triggerKey);

  const _DurationGateResult.blocked(String message)
    : this._(allowed: false, message: message, triggerKey: '');
}

class _DurationHitState {
  final DateTime startedAt;
  String trigger = '';
  _VisionDecision? decision;
  ForegroundAppInfo? foregroundApp;

  _DurationHitState({required this.startedAt});
}
