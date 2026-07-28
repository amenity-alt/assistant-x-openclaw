import 'base/proactive_vision_service_base.dart';

const defaultProactiveVisionTriggers = [
  '测试失败、构建失败、IDE 或终端出现明显错误',
  '系统关键弹窗、权限弹窗、任务完成或失败提示',
  '会议中有人明确向主人提问或等待主人回应',
  '需要立即处理的异常、风险、阻塞或确认',
];

String buildProactiveVisionPrompt({
  ForegroundAppInfo? foregroundApp,
  List<String> triggers = defaultProactiveVisionTriggers,
  DateTime? currentTime,
  List<ProactiveVisionPromptState> triggerStates = const [],
}) {
  final now = currentTime ?? DateTime.now();
  final appText = foregroundApp == null || foregroundApp.name.isEmpty
      ? '未知 App'
      : foregroundApp.name;
  final triggerText = triggers
      .where((trigger) => trigger.trim().isNotEmpty)
      .toList()
      .asMap()
      .entries
      .map((entry) => '${entry.key + 1}. ${entry.value}')
      .join('\n');
  final stateText = triggerStates.isEmpty
      ? '暂无连续命中记录。'
      : triggerStates
            .map((state) {
              final parts = [
                '${state.index}. ${state.trigger}',
                '首次命中: ${_formatDateTime(state.startedAt)}',
                '上次命中: ${_formatDateTime(state.lastHitAt)}',
                '已持续时长: ${_formatDuration(state.elapsedDuration)}',
              ];
              if (state.requiredDuration != null) {
                parts.add('要求时长: ${_formatDuration(state.requiredDuration!)}');
              }
              if (state.summary.trim().isNotEmpty) {
                parts.add('上次摘要: ${state.summary.trim()}');
              }
              return '- ${parts.join('；')}';
            })
            .join('\n');
  return '''
你是 Jarvis 的主动视觉守门员。当前前台 App：$appText。
当前时间：${_formatDateTime(now)}。

任务：判断当前屏幕是否满足“需要主动提醒主人或触发 Agent 指令”的关键条件。
触发条件列表：
$triggerText

当前前台 App 下由外层 watcher 维护的连续命中状态：
$stateText

忽略：普通网页浏览、静态桌面、无明显变化的代码/文档、广告、低价值通知。

时长要求：
- 如果触发条件包含“30分钟以上、2小时以上、持续 N 分钟”等时长要求，只判断当前画面是否属于该场景。
- 不要根据单张截图断言已经达到持续时长；持续时长由外层 watcher 统计。
- 如果上面的连续命中状态已经显示达到要求时长，可以在 summary 中写明“外层 watcher 已记录连续命中……”，不要自行臆测未给出的历史。
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

class ProactiveVisionPromptState {
  final int index;
  final String trigger;
  final DateTime startedAt;
  final DateTime lastHitAt;
  final Duration elapsedDuration;
  final Duration? requiredDuration;
  final String summary;

  const ProactiveVisionPromptState({
    required this.index,
    required this.trigger,
    required this.startedAt,
    required this.lastHitAt,
    required this.elapsedDuration,
    this.requiredDuration,
    this.summary = '',
  });
}

String _formatDateTime(DateTime value) {
  String two(int n) => n.toString().padLeft(2, '0');
  return '${value.year}-${two(value.month)}-${two(value.day)} '
      '${two(value.hour)}:${two(value.minute)}:${two(value.second)}';
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
