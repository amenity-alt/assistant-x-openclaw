import 'dart:convert';

import 'package:flutter/foundation.dart';

/// 短剧模式 HUD 控制器：解析 Python 推送的 `drama:status <json>`。
///
/// 数据来自 src/drama_agent/__init__.py `_summary_dict()`（紧凑摘要）：
///   {title, status, phase, current_episode, total_episodes,
///    episode_goals, characters, episodes, pending_confirm}
class DramaHudController extends ChangeNotifier {
  bool active = false;
  String title = '';
  String status = '';
  String phase = '';
  int currentEpisode = 1;
  int totalEpisodes = 10;
  String pendingPhase = '';
  String pendingSummary = '';
  List<String> episodeGoals = const [];
  List<String> characters = const [];

  static const Map<String, String> _phaseLabel = {
    'collect_req': 'REQUIREMENTS',
    'plan': 'STORY PLAN',
    'episode_script': 'EPISODE SCRIPT',
    'episode_prompts': 'SHOT PROMPTS',
    'review': 'REVIEW',
    'done': 'COMPLETE',
  };

  static const Map<String, String> _statusLabel = {
    'collecting': 'COLLECTING',
    'planning': 'PLANNING',
    'awaiting_confirm': 'AWAITING CONFIRM',
    'episode_design': 'WRITING SCRIPT',
    'prompts': 'GENERATING PROMPTS',
    'completed': 'COMPLETED',
    'paused': 'PAUSED',
    'failed': 'FAILED',
  };

  String get phaseLabel => _phaseLabel[phase] ?? phase.toUpperCase();

  String get statusLabel => _statusLabel[status] ?? status.toUpperCase();

  /// 第 N 集到第 M 集的“当前集”进度（0.0 ~ 1.0）。
  double get progress =>
      totalEpisodes <= 0 ? 0.0 : (currentEpisode / totalEpisodes).clamp(0.0, 1.0);

  void setStatus(String jsonPayload) {
    try {
      final data = jsonDecode(jsonPayload) as Map<String, dynamic>;
      title = (data['title'] as String?) ?? '';
      status = (data['status'] as String?) ?? '';
      phase = (data['phase'] as String?) ?? '';
      currentEpisode = ((data['current_episode'] as num?) ?? 1).toInt();
      totalEpisodes = ((data['total_episodes'] as num?) ?? 10).toInt();
      final pending = data['pending_confirm'];
      if (pending is Map<String, dynamic>) {
        pendingPhase = (pending['phase'] as String?) ?? '';
        pendingSummary = (pending['summary'] as String?) ?? '';
      } else {
        pendingPhase = '';
        pendingSummary = '';
      }
      episodeGoals = ((data['episode_goals'] as List?) ?? const [])
          .map((e) => e.toString())
          .toList();
      characters = ((data['characters'] as List?) ?? const [])
          .map((e) => (e as Map<String, dynamic>)['name']?.toString() ?? '')
          .where((n) => n.isNotEmpty)
          .toList();
      active = true;
      notifyListeners();
    } catch (e) {
      debugPrint('[Drama] setStatus parse error: $e');
    }
  }

  void reset() {
    active = false;
    title = '';
    status = '';
    phase = '';
    currentEpisode = 1;
    totalEpisodes = 10;
    pendingPhase = '';
    pendingSummary = '';
    episodeGoals = const [];
    characters = const [];
    notifyListeners();
  }
}
