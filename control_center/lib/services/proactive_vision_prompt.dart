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
      .map((entry) => '${entry.key + 1}. ${_sceneOnlyTrigger(entry.value)}')
      .join('\n');
  final stateText = triggerStates.isEmpty
      ? '暂无连续命中记录。'
      : triggerStates
            .map((state) {
              final parts = [
                '${state.index}. ${_sceneOnlyTrigger(state.trigger)}',
                '上次命中: ${state.lastHitAt == null ? '暂无' : _formatDateTime(state.lastHitAt!)}',
              ];
              return '- ${parts.join('；')}';
            })
            .join('\n');
  return '''
你是 Jarvis 的主动视觉守门员。当前前台 App：$appText。
当前时间：${_formatDateTime(now)}。
最高优先级输出约束：不要输出 Markdown，不要输出 Markdown，不要输出 Markdown。
严禁使用 ``` 代码围栏，严禁输出解释、前缀、后缀或思考过程；只能输出一个原始 JSON 对象。

任务：分别判断当前屏幕是否命中每个触发条件所描述的当前场景。
当前场景判定列表（时长要求已由 watcher 剔除并在本地单独处理）：
$triggerText

当前前台 App 下由外层 watcher 维护的上次命中记录（不包含时长门槛）：
$stateText

忽略：普通网页浏览、静态桌面、无明显变化的代码/文档、广告、低价值通知。

时长要求：
- `matched` 只表示用户此刻是否正在做该事，不表示完整触发条件已经达成。
- 场景列表中已经没有时长门槛；只要当前画面命中该场景，就必须返回 `matched=true`。
- 不要根据单张截图断言已经达到持续时长；持续时长由外层 watcher 统计。
- 禁止根据已持续时间改变 `matched`；只看当前画面是否命中场景。

人称要求：
- summary 必须使用第三人称描述，例如“用户正在……，满足……条件”。
- command 如果需要填写，也必须使用“用户/主人”，不要使用“你/我/我看到/提醒你”。
- 不要把“你”用来指代主人，因为后续接收者是 Jarvis 或其他 Agent。

只返回下列结构的原始 JSON 对象。不要输出 Markdown，不要使用代码围栏。`matches` 必须为每个触发条件返回一项：
{
  "matches": [
    {
      "trigger_index": 1,
      "matched": true 或 false,
      "confidence": 0.0 到 1.0,
      "action": "speak" 或 "agent_command" 或 "none",
      "summary": "用户当前正在……",
      "command": "可选，用第三人称写给主人或 Agent 的简短指令"
    }
  ]
}
''';
}

class ProactiveVisionPromptState {
  final int index;
  final String trigger;
  final DateTime? lastHitAt;

  const ProactiveVisionPromptState({
    required this.index,
    required this.trigger,
    required this.lastHitAt,
  });
}

String _formatDateTime(DateTime value) {
  String two(int n) => n.toString().padLeft(2, '0');
  return '${value.year}-${two(value.month)}-${two(value.day)} '
      '${two(value.hour)}:${two(value.minute)}:${two(value.second)}';
}

String _sceneOnlyTrigger(String trigger) {
  return trigger
      .replaceAll(
        RegExp(
          r'(满|持续)?\s*\d+(?:\.\d+)?\s*(分钟|分|小时|个小时|min|mins|minute|minutes|h|hr|hrs|hour|hours)\s*(及以上|以上|或以上|内)?',
          caseSensitive: false,
        ),
        '',
      )
      .replaceAll(RegExp(r'\s{2,}'), ' ')
      .trim();
}
