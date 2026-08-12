#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Short Drama — 阶段确认门（60s 超时 + 语音 YES/NO，风格对齐 mission 确认）。

- request()：登记待确认阶段与摘要（写进 project.pending_confirm）。
- reply() ：语音层调用，返回 (approved, expired) 并清除待确认。
- pending()：当前待确认信息（供 status / Flutter 展示）。
"""

import threading
import time

_CONFIRM_TIMEOUT = 60.0


class ConfirmGate:
    def __init__(self, timeout: float = _CONFIRM_TIMEOUT):
        self._timeout = timeout
        self._lock = threading.Lock()
        self._pending = None   # {project_id, phase, summary, deadline}

    def request(self, project, phase: str, summary: str) -> dict:
        with self._lock:
            self._pending = {
                "project_id": project.id,
                "phase": phase,
                "summary": summary,
                "deadline": time.time() + self._timeout,
            }
            project.pending_confirm = {
                "phase": phase,
                "summary": summary,
                "deadline": self._pending["deadline"],
            }
            return dict(self._pending)

    def reply(self, project_id: str, approved: bool) -> dict | None:
        """返回 {approved, expired, phase, summary}；无待确认返回 None。"""
        with self._lock:
            p = self._pending
            if not p or p["project_id"] != project_id:
                return None
            expired = time.time() > p["deadline"]
            self._pending = None
            return {
                "approved": bool(approved),
                "expired": expired,
                "phase": p["phase"],
                "summary": p["summary"],
            }

    def pending(self) -> dict | None:
        with self._lock:
            if not self._pending:
                return None
            p = dict(self._pending)
            p["remaining"] = round(max(p["deadline"] - time.time(), 0.0), 1)
            return p

    def clear(self):
        with self._lock:
            self._pending = None
