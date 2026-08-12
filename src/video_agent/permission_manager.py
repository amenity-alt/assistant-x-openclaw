#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Video Agent 权限/确认管理。

- 素材路径白名单：只允许读取用户目录下的常见视频位置；系统目录拒绝；
- generate/render 需用户确认（60s 超时自动拒绝），facecam 默认放行；
- 任务提示词黑名单（危险系统操作）直接拒绝。
"""

import os
import re
import threading
import time

from .task import MODE_NEEDS_CONFIRM, VideoMode

CONFIRM_TIMEOUT = 60.0

# 素材读取白名单根目录
_ALLOWED_ROOTS = [
    os.path.expanduser("~/Movies"),
    os.path.expanduser("~/Desktop"),
    os.path.expanduser("~/Downloads"),
    os.path.expanduser("~/Documents"),
    os.path.expanduser("~/.openclaw/workspace"),
    os.path.expanduser("~/Documents/ChatGPT"),
]

# 系统目录黑名单（即使前缀在白名单内也拒绝）
_BLOCKED_PREFIXES = [
    "/etc", "/System", "/usr", "/sbin", "/bin", "/var",
    os.path.expanduser("~/.ssh"), os.path.expanduser("~/.aws"),
]

# 提示词危险操作黑名单
_BLACKLIST = re.compile(
    r"\b(?:rm\s+-rf|sudo\s|shutdown|reboot|mkfs|dd\s+|:\(\)\s*\{|"
    r"chmod\s+-R\s+777|curl\s+.*\|\s*(?:ba)?sh)\b",
    re.I,
)

# 允许的视频扩展名
_VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm")


class PermissionManager:
    def __init__(self, timeout: float = CONFIRM_TIMEOUT):
        self._timeout = timeout
        self._lock = threading.Lock()
        self._pending = {}   # confirm_id → {"task_id", "deadline", "event", "approved"}

    # ── 素材路径校验 ─────────────────────────────────────
    def valid_source_video(self, path: str) -> str:
        """校验素材路径。合法返回绝对路径；非法返回空字符串。"""
        if not path:
            return ""
        p = os.path.abspath(os.path.expanduser(path.strip()))
        if not os.path.isfile(p):
            return ""
        ext = os.path.splitext(p)[1].lower()
        if ext not in _VIDEO_EXTS:
            return ""
        for blocked in _BLOCKED_PREFIXES:
            if p.startswith(blocked + os.sep) or p == blocked:
                return ""
        for root in _ALLOWED_ROOTS:
            if p.startswith(root + os.sep):
                return p
        return ""

    # ── 判定 ─────────────────────────────────────────────
    def blacklisted(self, text: str) -> bool:
        return bool(_BLACKLIST.search(text or ""))

    def needs_confirm(self, task) -> bool:
        return task.mode in (m.value for m in MODE_NEEDS_CONFIRM)

    def guard(self, task) -> str:
        """返回 auto | confirm | deny。"""
        if self.blacklisted(task.prompt):
            return "deny"
        if task.mode == VideoMode.FACECAM.value:
            if not self.valid_source_video(task.source_video):
                return "deny"
            return "auto"
        if self.needs_confirm(task):
            return "confirm"
        return "auto"

    # ── 确认队列（照抄 coding_agent）──────────────────────
    def request_confirm(self, task) -> str:
        confirm_id = task.id
        ev = threading.Event()
        with self._lock:
            self._pending[confirm_id] = {
                "task_id": task.id,
                "mode": task.mode,
                "project": task.project,
                "deadline": time.time() + self._timeout,
                "event": ev,
                "approved": None,
            }
        return confirm_id

    def approve(self, confirm_id: str) -> bool:
        with self._lock:
            p = self._pending.get(confirm_id)
            if not p or p["approved"] is not None or time.time() > p["deadline"]:
                return False
            p["approved"] = True
            p["event"].set()
        return True

    def deny(self, confirm_id: str) -> bool:
        with self._lock:
            p = self._pending.get(confirm_id)
            if not p or p["approved"] is not None:
                return False
            p["approved"] = False
            p["event"].set()
        return True

    def wait(self, confirm_id: str) -> str:
        with self._lock:
            p = self._pending.get(confirm_id)
            if not p:
                return "timeout"
            remaining = max(p["deadline"] - time.time(), 0.01)
        p["event"].wait(remaining)
        with self._lock:
            p = self._pending.get(confirm_id)
            if p and p["approved"] is not None:
                self._pending.pop(confirm_id, None)
                return "approved" if p["approved"] else "denied"
            self._pending.pop(confirm_id, None)
            return "timeout"

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def pending(self) -> list:
        now = time.time()
        with self._lock:
            out = []
            for cid, p in self._pending.items():
                out.append(
                    {
                        "confirm_id": cid,
                        "task_id": p.get("task_id", ""),
                        "mode": p.get("mode", ""),
                        "project": p.get("project", ""),
                        "remaining": max(p["deadline"] - now, 0.0),
                    }
                )
            return out
