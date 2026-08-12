#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Jarvis Video Agent — 统一任务模型：VideoTask / VideoResult。

原则：Jarvis 永不直接拼 shell 操作 OpenCut；一切视频任务收敛为
VideoTask，经 OpenCutClient 调 OpenCut REST API（127.0.0.1）异步执行。
"""

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum


class VideoMode(str, Enum):
    GENERATE = "generate"   # 全 AI 文生视频（prompt → 分镜 → TTS → 素材 → 渲染）
    FACECAM = "facecam"     # 用户素材视频（上传 → 转写 → 字幕 → 渲染）
    RENDER = "render"       # 渲染 OpenCut 已有项目/时间线（无需 AI key）
    STATUS = "status"       # 查询任务进度（直接返回，不入队）
    CANCEL = "cancel"       # 取消当前任务（直接返回，不入队）


# 需要用户确认的 mode（渲染/生成耗时长、占资源；facecam 素材来自用户自己，默认放行）
MODE_NEEDS_CONFIRM = {VideoMode.GENERATE, VideoMode.RENDER}

# 允许的 OpenCut 示例项目（render 模式白名单；不执行任意 entryPoint）
ALLOWED_PROJECTS = {
    "quickstart": ("src/examples/quickstart/index.ts", "QuickstartPreview"),
    "openslides": ("src/examples/openslides/index.ts", "OpenSlidesDemoPreview"),
    "floom-launch": ("src/examples/floom-launch/index.ts", "FloomLaunchPreview"),
    "hyperniche-launch": ("src/examples/hyperniche-launch/index.ts", "HypernicheLaunchPreview"),
    "opendraft-research": ("src/examples/opendraft-research/index.ts", "OpendraftResearchPreview"),
    "ai-engineer-basics": ("src/examples/ai-engineer-basics/index.ts", "AiEngineerBasicsPreview"),
}


@dataclass
class VideoTask:
    mode: str                  # VideoMode 值
    prompt: str = ""           # 用户需求（generate 模式的提示词 / 描述）
    source_video: str = ""     # 用户素材视频绝对路径（facecam 模式）
    project: str = ""          # OpenCut 示例项目名（render 模式，白名单内）
    duration_sec: int = 0      # 目标时长（秒，0 = 使用默认 60s）
    video_format: str = "horizontal"   # horizontal | vertical | square
    voice: str = ""            # ElevenLabs VoiceId（可空）
    playback_rate: float = 1.0
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VideoResult:
    status: str = "failed"     # success | failed | denied | cancelled | waiting
    summary: str = ""          # 人类可读结果（口播用）
    video_path: str = ""       # 成品 MP4 绝对路径（导出后）
    job_id: str = ""           # OpenCut jobId
    phase: str = ""            # 最后一个 phase（planning/tts/footage/rendering/done）
    error: str = ""
    task_id: str = ""
    elapsed: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)
