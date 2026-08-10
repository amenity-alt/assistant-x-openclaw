#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Action 派发执行器：后台线程执行 + 统一超时 + 操作日志。

原则：Jarvis 主循环只做意图解析与入队，实际系统操作在这里的
ThreadPoolExecutor(1) 后台执行，绝不阻塞语音主循环。
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .action import Action, Risk
from .action_log import ActionLog
from . import application_controller

_EXEC_TIMEOUT = 20.0  # 单个 Action 执行上限（秒）


class CommandExecutor:
    def __init__(self, log: ActionLog = None):
        self._log = log or ActionLog()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="computer")
        self._lock = threading.Lock()
        self._last_result = None  # 最近一次执行结果（Phase 5 口播用）

    # ── 提交与执行 ──────────────────────────────────────
    def submit(self, action: Action):
        """入队执行（异步）。返回 future，不阻塞调用方。"""
        return self._pool.submit(self.execute, action)

    def execute(self, action: Action) -> dict:
        """同步执行单个 Action（内部自带超时）。"""
        if action.risk == Risk.DENY:
            return self._finish(action, ok=False, detail="该操作已被安全策略拒绝")
        started = time.time()
        try:
            result = self._dispatch(action)
        except Exception as e:
            result = {"ok": False, "message": f"执行异常: {e}"}
        result.setdefault("ok", False)
        result.setdefault("message", "")
        elapsed = round(time.time() - started, 2)
        result["elapsed"] = elapsed
        self._finish(action, ok=result["ok"], detail=result["message"], elapsed=elapsed)
        return result

    # ── 派发表（Phase 1 仅应用控制；后续阶段按 action 扩充） ──
    def _dispatch(self, action: Action) -> dict:
        a = action.action
        target = action.target
        if a == "open_app":
            return application_controller.open_app(target)
        if a == "close_app":
            return application_controller.close_app(target)
        if a == "switch_app":
            display, _path = application_controller.resolve(target)
            return application_controller.activate_app(display)
        return {"ok": False, "message": f"未知操作: {a}"}

    # ── 日志与结果 ──────────────────────────────────────
    def _finish(self, action: Action, ok: bool, detail: str = "", elapsed: float = 0.0):
        entry = {
            "agent": "computer",
            "action": action.action,
            "target": action.target,
            "params": action.params,
            "risk": action.risk.value,
            "ok": ok,
            "detail": detail,
            "elapsed": elapsed,
            "action_id": action.id,
        }
        with self._lock:
            self._last_result = entry
        self._log.record(entry)
        return entry

    def last_result(self) -> dict:
        with self._lock:
            return dict(self._last_result) if self._last_result else {}

    def shutdown(self):
        self._pool.shutdown(wait=False)
