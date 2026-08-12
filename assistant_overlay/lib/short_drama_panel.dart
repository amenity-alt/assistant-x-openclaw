import 'package:flutter/material.dart';

import 'drama_hud_controller.dart';
import 'hud_terminal_shell.dart';

/// 短剧模式 HUD 面板（左上地图卡下方独立浮窗）。
///
/// 风格对齐 MapGlobeCard：HudTerminalShell + 蓝色发光边框 + 深色玻璃底。
/// 内容：剧名 / EPISODE X/Y / 阶段 / 进度条 / 下一步（待确认摘要）/ 人物。
/// 交互走语音（CONFIRM/PAUSE 按钮为 HUD 视觉元素）。
class ShortDramaPanel extends StatelessWidget {
  final DramaHudController controller;
  final double width;
  final double maxHeight;

  const ShortDramaPanel({
    super.key,
    required this.controller,
    required this.width,
    this.maxHeight = 220,
  });

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: controller,
      builder: (context, child) {
        if (!controller.active) return const SizedBox.shrink();
        final ep = 'EPISODE ${controller.currentEpisode.toString().padLeft(2, '0')}'
            ' / ${controller.totalEpisodes.toString().padLeft(2, '0')}';
        final showPending = controller.pendingSummary.isNotEmpty;
        return HudTerminalShell(
          title: 'SHORT DRAMA',
          width: width,
          maxHeight: maxHeight,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 6),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // 剧名 + 集数
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Flexible(
                        child: Text(
                          controller.title.isEmpty ? 'UNTITLED DRAMA' : controller.title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: Color(0xFF8CC1FA),
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                            letterSpacing: 1.2,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        ep,
                        style: const TextStyle(
                          color: Color(0xFF6EB9FF),
                          fontSize: 11,
                          letterSpacing: 1.0,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  // 阶段 + 状态
                  Row(
                    children: [
                      _Chip(label: controller.phaseLabel, glow: const Color(0xFF2F8CFF)),
                      const SizedBox(width: 6),
                      _Chip(
                        label: controller.statusLabel,
                        glow: controller.status == 'paused'
                            ? const Color(0xFFFFB84D)
                            : const Color(0xFF46E0A8),
                      ),
                    ],
                  ),
                  const SizedBox(height: 10),
                  // 进度条
                  _ProgressBar(
                    progress: controller.progress,
                    label:
                        'EP ${controller.currentEpisode.toString().padLeft(2, '0')} / ${controller.totalEpisodes.toString().padLeft(2, '0')}',
                  ),
                  // 制作进度（Phase 2 渲染中）
                  if (controller.productionActive) ...[
                    const SizedBox(height: 8),
                    _ProgressBar(
                      progress: (controller.prodProgress / 100).clamp(0.0, 1.0),
                      label: 'RENDER ${controller.prodShot.toString().padLeft(2, '0')}'
                          '/${controller.prodTotal.toString().padLeft(2, '0')} · '
                          '${controller.prodProgress.toStringAsFixed(0)}%',
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${controller.prodState.toUpperCase()}'
                      '${controller.prodBackend == 'opencut' ? ' · AI BACKEND' : ' · LOCAL FFMPEG'}',
                      style: const TextStyle(
                        color: Color(0xFF46E0A8),
                        fontSize: 8.5,
                        letterSpacing: 1.4,
                      ),
                    ),
                  ],
                  const SizedBox(height: 10),
                  // 下一步 / 待确认
                  if (showPending)
                    _NextStep(summary: controller.pendingSummary)
                  else
                    const _NextStep(summary: 'Say "查看第X集" or "生成提示词" to continue.'),
                  const SizedBox(height: 10),
                  // 人物 + HUD 按钮（视觉元素）同一行
                  Row(
                    children: [
                      Expanded(
                        child: Wrap(
                          spacing: 6,
                          runSpacing: 4,
                          children: controller.characters
                              .take(4)
                              .map((n) => _PersonChip(name: n))
                              .toList(),
                        ),
                      ),
                      const _HudButton(label: 'CONFIRM', primary: true),
                      const SizedBox(width: 6),
                      const _HudButton(label: 'PAUSE', primary: false),
                    ],
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

class _Chip extends StatelessWidget {
  final String label;
  final Color glow;
  const _Chip({required this.label, required this.glow});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: const Color(0x220D67BC),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: glow.withAlpha(90)),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: glow,
          fontSize: 9.5,
          letterSpacing: 1.4,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

class _ProgressBar extends StatelessWidget {
  final double progress;
  final String label;
  const _ProgressBar({required this.progress, required this.label});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text(
              'PROGRESS',
              style: TextStyle(color: Color(0xFF5B8DB8), fontSize: 8.5, letterSpacing: 1.6),
            ),
            Text(
              label,
              style: const TextStyle(color: Color(0xFF8CC1FA), fontSize: 9),
            ),
          ],
        ),
        const SizedBox(height: 4),
        ClipRRect(
          borderRadius: BorderRadius.circular(3),
          child: LinearProgressIndicator(
            value: progress,
            minHeight: 5,
            backgroundColor: const Color(0x331C7BD1),
            valueColor: const AlwaysStoppedAnimation(Color(0xFF2F8CFF)),
          ),
        ),
      ],
    );
  }
}

class _NextStep extends StatelessWidget {
  final String summary;
  const _NextStep({required this.summary});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      decoration: BoxDecoration(
        color: const Color(0x1A0D67BC),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: const Color(0xFF2F8CFF).withAlpha(60)),
      ),
      child: Text(
        summary,
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
        style: const TextStyle(
          color: Color(0xFF9FD0FF),
          fontSize: 10,
          height: 1.35,
        ),
      ),
    );
  }
}

class _PersonChip extends StatelessWidget {
  final String name;
  const _PersonChip({required this.name});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: const Color(0x2246E0A8),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        name,
        style: const TextStyle(color: Color(0xFF46E0A8), fontSize: 9),
      ),
    );
  }
}

class _HudButton extends StatelessWidget {
  final String label;
  final bool primary;
  const _HudButton({required this.label, required this.primary});

  @override
  Widget build(BuildContext context) {
    final Color c = primary ? const Color(0xFF2F8CFF) : const Color(0xFF5B8DB8);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
      decoration: BoxDecoration(
        color: c.withAlpha(30),
        borderRadius: BorderRadius.circular(5),
        border: Border.all(color: c.withAlpha(150), width: 1),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: c,
          fontSize: 9.5,
          letterSpacing: 1.6,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}
