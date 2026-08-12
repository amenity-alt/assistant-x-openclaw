#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Jarvis Video — video-agent（Capability，非独立唤醒 Agent）。

负责：视频制作 / 素材剪辑 / 项目渲染 / 进度查询。
由 main.py 语音拦截层调用（“帮我做一个视频 / 剪辑这个视频 / 渲染视频”），
不注册进 assistants.json、不占用唤醒词、不写入 Jarvis 核心。

实现委托给 src/video_agent/（OpenCut REST 适配层），此处为统一入口：
    clip()     — 用户素材剪辑（facecam 流水线）
    generate() — AI 文生视频（text-only 流水线）
    status()   — 任务进度
"""

import threading

from video_agent import VideoAgent as _Impl
from video_agent import get_video_agent as _get_impl


class VideoCapability:
    """视频能力门面：与 vision_agent.VisionAgent 同构。"""

    def __init__(self):
        self._impl = _get_impl()

    def clip(self, source_video: str, prompt: str = "") -> dict:
        """用户素材 → 剪辑视频（facecam 流水线）。"""
        return self._impl.run_sync(
            f"剪辑这个视频 {prompt}", source_video=source_video, timeout=1800.0
        )

    def generate(self, prompt: str, duration_sec: int = 60) -> dict:
        """文本 → AI 视频。"""
        return self._impl.run_sync(
            f"生成一个{duration_sec}秒视频 {prompt}", timeout=1800.0
        )

    def status(self) -> str:
        return self._impl.status()

    def impl(self) -> _Impl:
        return self._impl


_cap = None
_cap_lock = threading.Lock()


def get_video_capability() -> VideoCapability:
    global _cap
    with _cap_lock:
        if _cap is None:
            _cap = VideoCapability()
        return _cap
