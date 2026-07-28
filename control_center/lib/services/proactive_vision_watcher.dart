import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

import 'base/proactive_vision_service_base.dart';
import 'config_service.dart';
import 'proactive_vision_prompt.dart';

class ProactiveVisionWatcher {
  static const _triggerConfidenceThreshold = 0.75;
  static const _hitContinuityWindow = Duration(minutes: 1);
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
    _initializeDurationStates(config, DateTime.now());
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
        _logWithDurationProgress(config, '主动视觉能力未就绪，静默跳过：${status.message}');
        return;
      }

      final foreground = await _visionService.getForegroundAppInfo();
      if (_isPrivacyBlocked(foreground, config)) {
        _logWithDurationProgress(config, '主动视觉跳过前台 App：${foreground.name}');
        return;
      }
      _expireStaleDurationStates(DateTime.now());

      final snapshot = await _visionService.captureScreenSnapshot();

      _log('主动视觉主人在场判断暂未实现：本轮仅打印占位，不拦截');
      debugPrint('[主动视觉] owner-present check placeholder: not enforced');

      final result = await _visionService.analyzeSnapshot(
        ollamaUrl: config.proactiveVisionOllamaUrl,
        model: config.proactiveVisionModel,
        prompt: buildProactiveVisionPrompt(
          foregroundApp: foreground,
          triggers: config.proactiveVisionTriggers,
          currentTime: _lastSampleAt,
          triggerStates: _promptStatesForForeground(config, foreground),
        ),
        pngBytes: snapshot.pngBytes,
      );
      final decisions = _parseDecisions(result.response);
      final matches = decisions
          .where((decision) => decision.shouldTrigger)
          .toList();
      if (matches.isEmpty) {
        final summary = decisions
            .map((decision) => decision.summary.trim())
            .where((value) => value.isNotEmpty)
            .join('；');
        _logWithDurationProgress(
          config,
          '主动视觉本轮无场景命中：${summary.isEmpty ? '模型未给出有效场景判定' : summary}',
        );
        return;
      }

      var dispatched = 0;
      final matchedSummaries = <String>[];
      for (final decision in matches) {
        final normalized = _normalizeDecisionIndex(config, decision);
        if (normalized == null) continue;
        matchedSummaries.add(
          '#${normalized.triggerIndex} ${normalized.summary}',
        );
        _log(
          '主动视觉场景命中 #${normalized.triggerIndex} '
          '${normalized.confidence.toStringAsFixed(2)}：${normalized.summary}',
        );
        final requirement = _durationRequirementForDecision(config, normalized);
        if (requirement == null) {
          if (await _dispatchTrigger(normalized)) dispatched += 1;
          continue;
        }

        final state = _registerDurationHit(requirement, DateTime.now());
        if (state.elapsedDuration < requirement.duration) continue;

        _log('主动视觉条件 #${requirement.index} 已达持续时长，准备唤醒 Jarvis');
        if (await _dispatchTrigger(normalized)) {
          dispatched += 1;
          _startNextDurationCycle(_durationHitKey(requirement), DateTime.now());
        }
      }
      final resultText = dispatched > 0
          ? '主动视觉本轮已触发 $dispatched 个条件'
          : '主动视觉本轮场景命中：${matchedSummaries.join('；')}'
                '，持续时长尚未达标';
      _logWithDurationProgress(config, resultText);
    } catch (e) {
      _logWithDurationProgress(config, '主动视觉本轮异常，静默跳过：$e');
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

  List<_VisionDecision> _parseDecisions(String response) {
    final sanitized = _removeThinkBlocks(response);
    for (final candidate in _jsonObjectCandidates(
      sanitized,
    ).toList().reversed) {
      try {
        final decoded =
            jsonDecode(_stripJsonLineComments(candidate))
                as Map<String, dynamic>;
        final decisions = _decisionsFromMap(decoded);
        if (decisions != null) return decisions;
      } catch (_) {
        continue;
      }
    }
    for (final candidate in _jsonObjectCandidates(response).toList().reversed) {
      try {
        final decoded =
            jsonDecode(_stripJsonLineComments(candidate))
                as Map<String, dynamic>;
        final decisions = _decisionsFromMap(decoded);
        if (decisions != null) return decisions;
      } catch (_) {
        continue;
      }
    }
    final looseDecision = _parseLooseDecision(response);
    if (looseDecision != null) return [looseDecision];
    return [_VisionDecision.noop(response)];
  }

  String _removeThinkBlocks(String response) {
    return response.replaceAll(
      RegExp(r'<think>[\s\S]*?</think>', caseSensitive: false),
      '',
    );
  }

  List<_VisionDecision>? _decisionsFromMap(Map<String, dynamic> decoded) {
    final rawMatches = decoded['matches'];
    if (rawMatches is List) {
      return rawMatches
          .whereType<Map>()
          .map((raw) => Map<String, dynamic>.from(raw))
          .map(_decisionFromMatchMap)
          .whereType<_VisionDecision>()
          .toList();
    }
    final legacy = _decisionFromMatchMap(decoded, legacy: true);
    return legacy == null ? null : [legacy];
  }

  _VisionDecision? _decisionFromMatchMap(
    Map<String, dynamic> decoded, {
    bool legacy = false,
  }) {
    if (!decoded.containsKey('trigger') &&
        !decoded.containsKey('matched') &&
        !decoded.containsKey('confidence') &&
        !decoded.containsKey('summary')) {
      return null;
    }
    return _VisionDecision(
      trigger: legacy
          ? decoded['trigger'] == true
          : decoded['matched'] == true || decoded['trigger'] == true,
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

  _VisionDecision? _normalizeDecisionIndex(
    GlobalConfig config,
    _VisionDecision decision,
  ) {
    final triggerCount = config.proactiveVisionTriggers.length;
    final index = decision.triggerIndex;
    if (index != null && index >= 1 && index <= triggerCount) {
      return decision;
    }
    if (index == null && triggerCount == 1) {
      return _VisionDecision(
        trigger: decision.trigger,
        confidence: decision.confidence,
        triggerIndex: 1,
        action: decision.action,
        summary: decision.summary,
        command: decision.command,
      );
    }
    _log('主动视觉忽略无效场景序号：${index ?? '缺失'}');
    return null;
  }

  _DurationRequirement? _durationRequirementForDecision(
    GlobalConfig config,
    _VisionDecision decision,
  ) {
    final index = decision.triggerIndex;
    if (index == null) return null;
    return _durationRequirements(
      config.proactiveVisionTriggers,
    ).where((requirement) => requirement.index == index).firstOrNull;
  }

  _DurationHitState _registerDurationHit(
    _DurationRequirement requirement,
    DateTime now,
  ) {
    final state = _durationStates.putIfAbsent(
      _durationHitKey(requirement),
      () => _DurationHitState(startedAt: now)..trigger = requirement.trigger,
    );
    state.registerHit(now);
    return state;
  }

  String? _durationWaitingMessage(GlobalConfig config) {
    final now = DateTime.now();
    final messages = _durationRequirements(config.proactiveVisionTriggers).map((
      requirement,
    ) {
      final state = _durationStates[_durationHitKey(requirement)];
      final elapsed = state?.elapsedDuration ?? Duration.zero;
      final required = requirement.duration;
      final lastHitText = state?.lastHitAt == null
          ? '暂无'
          : _formatDuration(now.difference(state!.lastHitAt!));
      if (elapsed >= required) {
        return '主动视觉进度「${requirement.trigger}」：已持续 ${_formatDuration(elapsed)} / 目标 ${_formatDuration(required)} / 距上次命中 $lastHitText / 已达标';
      }
      return '主动视觉进度「${requirement.trigger}」：已持续 ${_formatDuration(elapsed)} / 目标 ${_formatDuration(required)} / 距上次命中 $lastHitText / 剩余 ${_formatDuration(required - elapsed)}';
    }).toList();
    return messages.isEmpty ? null : messages.join('；');
  }

  // Invariant: every final per-cycle status shows progress for every timed
  // condition, including conditions that have never matched.
  void _logWithDurationProgress(GlobalConfig config, String message) {
    final progress = _durationWaitingMessage(config);
    _log(progress == null ? message : '$message；$progress');
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

  List<ProactiveVisionPromptState> _promptStatesForForeground(
    GlobalConfig config,
    ForegroundAppInfo app,
  ) {
    return _durationRequirements(config.proactiveVisionTriggers)
        .map((requirement) {
          final state = _durationStates[_durationHitKey(requirement)];
          if (state == null) return null;
          return ProactiveVisionPromptState(
            index: requirement.index,
            trigger: requirement.trigger,
            lastHitAt: state.lastHitAt,
          );
        })
        .whereType<ProactiveVisionPromptState>()
        .toList();
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

  String _durationHitKey(_DurationRequirement requirement) {
    return requirement.trigger.trim().toLowerCase();
  }

  void _expireStaleDurationStates(DateTime now) {
    for (final state in _durationStates.values) {
      final lastHitAt = state.lastHitAt;
      if (lastHitAt == null ||
          now.difference(lastHitAt) < _hitContinuityWindow) {
        continue;
      }
      if (state.elapsedDuration > Duration.zero) {
        _log('主动视觉场景「${state.trigger}」 1 分钟内未再次命中，已持续时间归零');
      }
      state.resetContinuity(now);
    }
  }

  void _initializeDurationStates(GlobalConfig config, DateTime now) {
    for (final requirement in _durationRequirements(
      config.proactiveVisionTriggers,
    )) {
      _durationStates[_durationHitKey(requirement)] = _DurationHitState(
        startedAt: now,
      )..trigger = requirement.trigger;
    }
  }

  void _startNextDurationCycle(String key, DateTime now) {
    if (key.isEmpty) return;
    _durationStates[key]?.startNextCycle(now);
  }

  void _resetDurationStates() {
    _durationStates.clear();
  }

  String _formatDuration(Duration duration) {
    final safeDuration = duration.isNegative ? Duration.zero : duration;
    final seconds = safeDuration.inSeconds.remainder(60);
    if (safeDuration.inHours > 0) {
      final minutes = safeDuration.inMinutes.remainder(60);
      return '${safeDuration.inHours}小时$minutes分$seconds秒';
    }
    if (safeDuration.inMinutes > 0) {
      return '${safeDuration.inMinutes}分$seconds秒';
    }
    return '${safeDuration.inSeconds}秒';
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

class _DurationHitState {
  DateTime startedAt;
  DateTime? lastHitAt;
  Duration elapsedDuration = Duration.zero;
  String trigger = '';

  _DurationHitState({required this.startedAt});

  void registerHit(DateTime now) {
    final previousHitAt = lastHitAt;
    if (previousHitAt == null ||
        now.difference(previousHitAt) >=
            ProactiveVisionWatcher._hitContinuityWindow) {
      startedAt = now;
      elapsedDuration = Duration.zero;
    } else if (now.isAfter(previousHitAt)) {
      elapsedDuration += now.difference(previousHitAt);
    }
    lastHitAt = now;
  }

  void resetContinuity(DateTime now) {
    startedAt = now;
    lastHitAt = null;
    elapsedDuration = Duration.zero;
  }

  void startNextCycle(DateTime now) {
    startedAt = now;
    lastHitAt = now;
    elapsedDuration = Duration.zero;
  }
}
