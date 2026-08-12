#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""video-agent 提示词（后续 Phase 5 个性化剪辑规划用，唯一源）。

当前 Phase 2 主要走 OpenCut 自带 Gemini 分镜；这里预留 Jarvis 侧
剪辑规划提示词，未来用于：素材理解 → 精彩片段选择 → 时间线生成。
"""

# 剪辑规划提示词：把用户口语需求 → 结构化剪辑方案（未来接 DeepSeek/Hermes）
CLIP_PLANNING_PROMPT = (
    "You are JARVIS video editor. Turn the user's request into a concise "
    "video production plan.\n"
    "Reply with ONLY JSON: {\"title\": string, \"durationSec\": number, "
    "\"style\": string, \"segments\": [{\"type\": \"facecam-full\"|"
    "\"screen-static\"|\"title-card\"|\"end-card\", \"duration\": number, "
    "\"note\": string}]}\n"
    "Keep at most 6 segments. No markdown.\n"
    "Request: {prompt}"
)

# 素材精彩片段选择提示词（未来接转写文本）
HIGHLIGHT_SELECTION_PROMPT = (
    "You are JARVIS video editor. Given a transcript with timestamps, pick "
    "the top highlights suitable for a short video.\n"
    "Reply with ONLY JSON array: [{\"startSec\": number, \"endSec\": number, "
    "\"reason\": string}]\n"
    "Pick at most 5. No markdown.\n"
    "Transcript: {transcript}"
)

# 视频格式映射（中文/英文 → OpenCut format 值）
FORMAT_MAP = {
    "horizontal": "horizontal",
    "横屏": "horizontal",
    "vertical": "vertical",
    "竖屏": "vertical",
    "square": "square",
    "方形": "square",
}
