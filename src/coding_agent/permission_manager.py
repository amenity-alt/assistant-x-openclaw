#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Coding Agent 权限/确认管理。

- 默认 readonly：analyze/review 直接执行；
- modify / git commit / git push：必须用户确认（Phase 2 语音确认接入；
  Phase 1 提供 approve(id)/deny(id) 接口 + 阻塞等待，供测试与后续接线）；
- 黑名单任务直接拒绝；确认 60s 超时自动拒绝。
"""

import re
import threading
import time

from .task import CodingMode, MODE_NEEDS_CONFIRM

CONFIRM_TIMEOUT = 60.0

# 危险模式黑名单（出现在任务文本即拒绝）
_BLACKLIST = re.compile(
    r"\b(?:rm\s+-rf|sudo\s|shutdown|reboot|mkfs|dd\s+|:\(\)\s*\{|"
    r"chmod\s+-R\s+777|curl\s+.*\|\s*(?:ba)?sh)\b",
    re.I,
)


class PermissionManager:
    def __init__(self, timeout: float = CONFIRM_TIMEOUT):
        self._timeout = timeout
        self._lock = threading.Lock()
        self._pending = {}   # confirm_id → {"task_id", "deadline", "event", "approved"}

    # ── 判定 ─────────────────────────────────────────────
    def blacklisted(self, text: str) -> bool:
        return bool(_BLACKLIST.search(text or ""))

    def needs_confirm(self, task) -> bool:
        """modify 需确认；git 模式只有 commit/push 才需确认（由任务文本判定）。"""
        if task.mode in (m.value for m in MODE_NEEDS_CONFIRM):
            return True
        if task.mode == CodingMode.GIT.value:
            t = (task.task or "").lower()
            # 注意：中文都是 \w，不能对中文用 \b 边界（会永不匹配导致绕过确认）。
            # 仅对「提交代码/提交改动/提交一下/提交(句尾)/commit/push/推送」放行确认；
            # 「提交记录」是只读查询，不在此列。
            return bool(
                re.search(
                    r"(?:commit\b|push\b|推送|提交(?:一下)?(?:代码|改动)?$)", t
                )
            )
        return False

    def guard(self, task) -> str:
        """返回 auto | confirm | deny。"""
        if self.blacklisted(task.task):
            return "deny"
        if self.needs_confirm(task):
            return "confirm"
        return "auto"

    # ── 确认队列 ─────────────────────────────────────────
    def request_confirm(self, task) -> str:
        """登记待确认任务，返回 confirm_id（60s 超时自动拒绝）。"""
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
        """阻塞等待确认结果：approved | denied | timeout。"""
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
        """待确认登记（确认流/语音接入用）：[{confirm_id, task_id, mode, project, remaining}]。"""
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
