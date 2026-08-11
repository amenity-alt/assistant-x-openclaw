#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Jarvis Spatial Vision — vision-agent（Capability，非独立唤醒 Agent）。

负责：图像理解 / 物体识别 / 场景分析。
由 main.py 语音拦截层调用（“扫描这个 / 识别一下 / 这是什么 / 详细介绍一下”），
不注册进 assistants.json、不占用唤醒词、不写入 Jarvis 核心。

识别后端分层（软失败）：Hermes 视觉 LLM（默认）→ MediaPipe 本地分类 → YOLO 预留。
"""

import threading

from vision_object import get_object_recognizer


class VisionAgent:
    """视觉理解能力入口：scan() / describe() / status()。"""

    def __init__(self):
        self._recognizer = None
        self._lock = threading.Lock()

    @property
    def recognizer(self):
        with self._lock:
            if self._recognizer is None:
                from vision_object import get_object_recognizer

                self._recognizer = get_object_recognizer()
            return self._recognizer

    def scan(self, jpeg: bytes, role: str = "jarvis") -> dict | None:
        """单次物体识别：返回统一结果 dict 或 None。"""
        if not jpeg:
            return None
        return self.recognizer.recognize(jpeg, role)

    def describe(self, jpeg: bytes, role: str = "jarvis") -> str | None:
        """详细描述画面中的物体（“详细介绍一下”）。"""
        if not jpeg:
            return None
        return self.recognizer.describe(jpeg, role)

    def status(self) -> dict:
        return {
            "backend": "hermes -> mediapipe -> yolo",
            "role": "jarvis",
        }


# ── 单例 ────────────────────────────────────────────────
_agent = None
_agent_lock = threading.Lock()


def get_vision_agent() -> VisionAgent:
    global _agent
    with _agent_lock:
        if _agent is None:
            _agent = VisionAgent()
        return _agent
