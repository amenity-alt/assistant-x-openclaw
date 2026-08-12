#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Jarvis Short Drama — drama-agent 门面（Capability，非独立唤醒 Agent）。

与 video_agent.VideoCapability / vision_agent.VisionAgent 同构：
不注册进 assistants.json、不占用唤醒词，由 main.py 语音拦截层调用。

职责：短剧模式入口 → 需求收集 → 剧情规划 → 单集剧本 → 镜头 Prompt 的编排。
"""

import threading

from drama_agent import DramaAgent as _Impl
from drama_agent import get_drama_agent as _get_impl


class DramaCapability:
    """短剧能力门面。"""

    def __init__(self):
        self._impl = _get_impl()

    def handle(self, text: str, role: str = "jarvis"):
        """语音指令入口：返回 dict（消费）或 False（未消费）。"""
        return self._impl.handle(text, role=role)

    def status(self) -> dict:
        p = self._impl.current_project
        if p is None:
            return {"active": False, "message": "当前没有短剧项目"}
        return {"active": True, **self._impl._summary_dict(p)}

    def confirm(self, approved: bool) -> dict:
        p = self._impl.current_project
        if p is None:
            return {"status": "no_project", "message": "当前没有短剧项目"}
        return self._impl._confirm(p, approved)

    def impl(self) -> _Impl:
        return self._impl


_cap = None
_cap_lock = threading.Lock()


def get_drama_capability() -> DramaCapability:
    global _cap
    with _cap_lock:
        if _cap is None:
            _cap = DramaCapability()
        return _cap
