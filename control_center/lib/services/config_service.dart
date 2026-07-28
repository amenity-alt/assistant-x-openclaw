import 'dart:convert';
import 'dart:io';

import 'proactive_vision_prompt.dart';

class ConfigService {
  String get _projectDir {
    final home =
        Platform.environment['HOME'] ??
        Platform.environment['USERPROFILE'] ??
        '';
    final base =
        '$home/.openclaw/workspace/voice-assistant/assistant-x-openclaw';
    return Platform.isWindows ? base.replaceAll('/', '\\') : base;
  }

  File get _envFile =>
      File(Platform.isWindows ? '$_projectDir\\.env' : '$_projectDir/.env');

  File get _assistantsFile => File(
    Platform.isWindows
        ? '$_projectDir\\assistants.json'
        : '$_projectDir/assistants.json',
  );

  Future<GlobalConfig> load() async {
    final values = await _readValues();
    final assistantEffects = await _readAssistantEffects();
    return GlobalConfig(
      speakerThreshold: _asDouble(
        values['VOICE_ASSISTANT_SPEAKER_THRESHOLD'],
        0.55,
      ),
      livenessEnabled: _asBool(
        values['VOICE_ASSISTANT_LIVENESS_ENABLED'],
        true,
      ),
      livenessEnforce: _asBool(
        values['VOICE_ASSISTANT_LIVENESS_ENFORCE'],
        false,
      ),
      livenessThreshold: _asDouble(
        values['VOICE_ASSISTANT_LIVENESS_THRESHOLD'],
        0.5,
      ),
      mediaWakeGuardEnabled: _asBool(
        values['VOICE_ASSISTANT_MEDIA_WAKE_GUARD_ENABLED'],
        true,
      ),
      mediaWakeGuardEnforce: _asBool(
        values['VOICE_ASSISTANT_MEDIA_WAKE_GUARD_ENFORCE'],
        false,
      ),
      proactiveVisionEnabled: _asBool(
        values['VOICE_ASSISTANT_PROACTIVE_VISION_ENABLED'],
        false,
      ),
      proactiveVisionOllamaUrl:
          values['VOICE_ASSISTANT_PROACTIVE_VISION_OLLAMA_URL'] ??
          'http://127.0.0.1:11434',
      proactiveVisionModel:
          values['VOICE_ASSISTANT_PROACTIVE_VISION_MODEL'] ??
          'minicpm-v4.6:latest',
      proactiveVisionPrompt: buildProactiveVisionPrompt(),
      proactiveVisionIntervalSeconds: _asInt(
        values['VOICE_ASSISTANT_PROACTIVE_VISION_INTERVAL_SECONDS'],
        20,
      ),
      proactiveVisionTriggers: _asStringList(
        values['VOICE_ASSISTANT_PROACTIVE_VISION_TRIGGERS'],
        defaultProactiveVisionTriggers,
      ),
      proactiveVisionIgnoredApps: _asStringList(
        values['VOICE_ASSISTANT_PROACTIVE_VISION_IGNORED_APPS'],
        const [
          'Control Center',
          'control_center',
          '语音助手控制中心',
          'ASSISTANT-X-OPENCLAW',
          'Assistant-X-OpenClaw',
          'assistant-x-openclaw',
        ],
      ),
      assistantEffects: assistantEffects,
    );
  }

  Future<void> save(GlobalConfig config) async {
    final updates = <String, String>{
      'VOICE_ASSISTANT_SPEAKER_THRESHOLD': _formatDouble(
        config.speakerThreshold,
      ),
      'VOICE_ASSISTANT_LIVENESS_ENABLED': _formatBool(config.livenessEnabled),
      'VOICE_ASSISTANT_LIVENESS_ENFORCE': _formatBool(config.livenessEnforce),
      'VOICE_ASSISTANT_LIVENESS_THRESHOLD': _formatDouble(
        config.livenessThreshold,
      ),
      'VOICE_ASSISTANT_MEDIA_WAKE_GUARD_ENABLED': _formatBool(
        config.mediaWakeGuardEnabled,
      ),
      'VOICE_ASSISTANT_MEDIA_WAKE_GUARD_ENFORCE': _formatBool(
        config.mediaWakeGuardEnforce,
      ),
      'VOICE_ASSISTANT_PROACTIVE_VISION_ENABLED': _formatBool(
        config.proactiveVisionEnabled,
      ),
      'VOICE_ASSISTANT_PROACTIVE_VISION_OLLAMA_URL': _formatSingleLine(
        config.proactiveVisionOllamaUrl,
      ),
      'VOICE_ASSISTANT_PROACTIVE_VISION_MODEL': _formatSingleLine(
        config.proactiveVisionModel,
      ),
      'VOICE_ASSISTANT_PROACTIVE_VISION_INTERVAL_SECONDS': config
          .proactiveVisionIntervalSeconds
          .toString(),
      'VOICE_ASSISTANT_PROACTIVE_VISION_TRIGGERS': jsonEncode(
        config.proactiveVisionTriggers,
      ),
      'VOICE_ASSISTANT_PROACTIVE_VISION_IGNORED_APPS': jsonEncode(
        config.proactiveVisionIgnoredApps,
      ),
    };

    final file = _envFile;
    final original = await file.exists()
        ? await file.readAsLines()
        : <String>[];
    final seen = <String>{};
    final next = <String>[];

    for (final line in original) {
      final match = RegExp(
        r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=',
      ).firstMatch(line);
      if (match == null) {
        next.add(line);
        continue;
      }
      final key = match.group(1)!;
      if (key == 'VOICE_ASSISTANT_PROACTIVE_VISION_PROMPT') {
        continue;
      }
      if (!updates.containsKey(key)) {
        next.add(line);
        continue;
      }
      next.add('$key=${updates[key]}');
      seen.add(key);
    }

    final missing = updates.keys.where((key) => !seen.contains(key)).toList();
    if (missing.isNotEmpty) {
      if (next.isNotEmpty && next.last.trim().isNotEmpty) next.add('');
      next.add('# 声纹与活体检测配置（由 Control Center 写入）');
      for (final key in missing) {
        next.add('$key=${updates[key]}');
      }
    }

    await file.writeAsString('${next.join('\n')}\n');
    await _saveAssistantEffects(config.assistantEffects);
  }

  Future<List<AssistantEffectConfig>> _readAssistantEffects() async {
    final file = _assistantsFile;
    if (!await file.exists()) return const [];
    final root = jsonDecode(await file.readAsString()) as Map<String, dynamic>;
    final assistants = root['assistants'] as List<dynamic>? ?? const [];
    return assistants
        .map((raw) {
          final assistant = raw as Map<String, dynamic>;
          return AssistantEffectConfig(
            id: assistant['id']?.toString() ?? '',
            name:
                assistant['name']?.toString() ??
                assistant['id']?.toString() ??
                '',
            visualEffect: assistant['visualEffect']?.toString() ?? 'Particle',
          );
        })
        .where((assistant) => assistant.id.isNotEmpty)
        .toList();
  }

  Future<void> _saveAssistantEffects(
    List<AssistantEffectConfig> effects,
  ) async {
    final file = _assistantsFile;
    if (!await file.exists()) return;
    final root = jsonDecode(await file.readAsString()) as Map<String, dynamic>;
    final assistants = root['assistants'] as List<dynamic>? ?? const [];
    final selected = {
      for (final effect in effects) effect.id: effect.visualEffect,
    };
    for (final raw in assistants) {
      final assistant = raw as Map<String, dynamic>;
      final id = assistant['id']?.toString();
      if (id != null && selected.containsKey(id)) {
        assistant['visualEffect'] = selected[id];
      }
    }
    const encoder = JsonEncoder.withIndent('    ');
    await file.writeAsString('${encoder.convert(root)}\n');
  }

  Future<Map<String, String>> _readValues() async {
    final file = _envFile;
    if (!await file.exists()) return {};
    final result = <String, String>{};
    for (final raw in await file.readAsLines()) {
      final line = raw.trim();
      if (line.isEmpty || line.startsWith('#') || !line.contains('=')) {
        continue;
      }
      final idx = line.indexOf('=');
      final key = line.substring(0, idx).trim();
      final value = line.substring(idx + 1).trim();
      if (key.isNotEmpty) result[key] = value;
    }
    return result;
  }

  bool _asBool(String? value, bool fallback) {
    if (value == null || value.trim().isEmpty) return fallback;
    return {'1', 'true', 'yes', 'on', 'y'}.contains(value.trim().toLowerCase());
  }

  double _asDouble(String? value, double fallback) {
    if (value == null) return fallback;
    return double.tryParse(value.trim()) ?? fallback;
  }

  int _asInt(String? value, int fallback) {
    if (value == null) return fallback;
    return int.tryParse(value.trim()) ?? fallback;
  }

  List<String> _asStringList(String? value, List<String> fallback) {
    if (value == null || value.trim().isEmpty) return fallback;
    try {
      final decoded = jsonDecode(value.trim());
      if (decoded is List) {
        final items = decoded
            .map((item) => item.toString().trim())
            .where((item) => item.isNotEmpty)
            .toList();
        if (items.isNotEmpty) return items;
      }
    } catch (_) {}
    final items = value
        .split(RegExp(r'[|,，;；]'))
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty)
        .toList();
    return items.isEmpty ? fallback : items;
  }

  String _formatBool(bool value) => value ? 'true' : 'false';

  String _formatSingleLine(String value) =>
      value.trim().replaceAll(RegExp(r'\s+'), ' ');

  String _formatDouble(double value) {
    final fixed = value.toStringAsFixed(3);
    return fixed
        .replaceFirst(RegExp(r'0+$'), '')
        .replaceFirst(RegExp(r'\.$'), '');
  }
}

class GlobalConfig {
  final double speakerThreshold;
  final bool livenessEnabled;
  final bool livenessEnforce;
  final double livenessThreshold;
  final bool mediaWakeGuardEnabled;
  final bool mediaWakeGuardEnforce;
  final bool proactiveVisionEnabled;
  final String proactiveVisionOllamaUrl;
  final String proactiveVisionModel;
  final String proactiveVisionPrompt;
  final int proactiveVisionIntervalSeconds;
  final List<String> proactiveVisionTriggers;
  final List<String> proactiveVisionIgnoredApps;
  final List<AssistantEffectConfig> assistantEffects;

  const GlobalConfig({
    required this.speakerThreshold,
    required this.livenessEnabled,
    required this.livenessEnforce,
    required this.livenessThreshold,
    required this.mediaWakeGuardEnabled,
    required this.mediaWakeGuardEnforce,
    required this.proactiveVisionEnabled,
    required this.proactiveVisionOllamaUrl,
    required this.proactiveVisionModel,
    required this.proactiveVisionPrompt,
    required this.proactiveVisionIntervalSeconds,
    required this.proactiveVisionTriggers,
    required this.proactiveVisionIgnoredApps,
    required this.assistantEffects,
  });

  GlobalConfig copyWith({
    double? speakerThreshold,
    bool? livenessEnabled,
    bool? livenessEnforce,
    double? livenessThreshold,
    bool? mediaWakeGuardEnabled,
    bool? mediaWakeGuardEnforce,
    bool? proactiveVisionEnabled,
    String? proactiveVisionOllamaUrl,
    String? proactiveVisionModel,
    String? proactiveVisionPrompt,
    int? proactiveVisionIntervalSeconds,
    List<String>? proactiveVisionTriggers,
    List<String>? proactiveVisionIgnoredApps,
    List<AssistantEffectConfig>? assistantEffects,
  }) {
    return GlobalConfig(
      speakerThreshold: speakerThreshold ?? this.speakerThreshold,
      livenessEnabled: livenessEnabled ?? this.livenessEnabled,
      livenessEnforce: livenessEnforce ?? this.livenessEnforce,
      livenessThreshold: livenessThreshold ?? this.livenessThreshold,
      mediaWakeGuardEnabled:
          mediaWakeGuardEnabled ?? this.mediaWakeGuardEnabled,
      mediaWakeGuardEnforce:
          mediaWakeGuardEnforce ?? this.mediaWakeGuardEnforce,
      proactiveVisionEnabled:
          proactiveVisionEnabled ?? this.proactiveVisionEnabled,
      proactiveVisionOllamaUrl:
          proactiveVisionOllamaUrl ?? this.proactiveVisionOllamaUrl,
      proactiveVisionModel: proactiveVisionModel ?? this.proactiveVisionModel,
      proactiveVisionPrompt:
          proactiveVisionPrompt ?? this.proactiveVisionPrompt,
      proactiveVisionIntervalSeconds:
          proactiveVisionIntervalSeconds ?? this.proactiveVisionIntervalSeconds,
      proactiveVisionTriggers:
          proactiveVisionTriggers ?? this.proactiveVisionTriggers,
      proactiveVisionIgnoredApps:
          proactiveVisionIgnoredApps ?? this.proactiveVisionIgnoredApps,
      assistantEffects: assistantEffects ?? this.assistantEffects,
    );
  }

  @override
  bool operator ==(Object other) {
    return other is GlobalConfig &&
        speakerThreshold == other.speakerThreshold &&
        livenessEnabled == other.livenessEnabled &&
        livenessEnforce == other.livenessEnforce &&
        livenessThreshold == other.livenessThreshold &&
        mediaWakeGuardEnabled == other.mediaWakeGuardEnabled &&
        mediaWakeGuardEnforce == other.mediaWakeGuardEnforce &&
        proactiveVisionEnabled == other.proactiveVisionEnabled &&
        proactiveVisionOllamaUrl == other.proactiveVisionOllamaUrl &&
        proactiveVisionModel == other.proactiveVisionModel &&
        proactiveVisionPrompt == other.proactiveVisionPrompt &&
        proactiveVisionIntervalSeconds ==
            other.proactiveVisionIntervalSeconds &&
        _listEquals(proactiveVisionTriggers, other.proactiveVisionTriggers) &&
        _listEquals(
          proactiveVisionIgnoredApps,
          other.proactiveVisionIgnoredApps,
        ) &&
        _listEquals(assistantEffects, other.assistantEffects);
  }

  @override
  int get hashCode => Object.hash(
    speakerThreshold,
    livenessEnabled,
    livenessEnforce,
    livenessThreshold,
    mediaWakeGuardEnabled,
    mediaWakeGuardEnforce,
    proactiveVisionEnabled,
    proactiveVisionOllamaUrl,
    proactiveVisionModel,
    proactiveVisionPrompt,
    proactiveVisionIntervalSeconds,
    Object.hashAll(proactiveVisionTriggers),
    Object.hashAll(proactiveVisionIgnoredApps),
    Object.hashAll(assistantEffects),
  );
}

bool _listEquals<T>(List<T> a, List<T> b) {
  if (identical(a, b)) return true;
  if (a.length != b.length) return false;
  for (var i = 0; i < a.length; i++) {
    if (a[i] != b[i]) return false;
  }
  return true;
}

class AssistantEffectConfig {
  final String id;
  final String name;
  final String visualEffect;

  const AssistantEffectConfig({
    required this.id,
    required this.name,
    required this.visualEffect,
  });

  AssistantEffectConfig copyWith({String? visualEffect}) {
    return AssistantEffectConfig(
      id: id,
      name: name,
      visualEffect: visualEffect ?? this.visualEffect,
    );
  }

  @override
  bool operator ==(Object other) {
    return other is AssistantEffectConfig &&
        id == other.id &&
        name == other.name &&
        visualEffect == other.visualEffect;
  }

  @override
  int get hashCode => Object.hash(id, name, visualEffect);
}
