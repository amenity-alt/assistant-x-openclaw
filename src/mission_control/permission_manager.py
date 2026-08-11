#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Mission 级权限：计划白名单 + 步骤确认登记 + 危险动作兜底。

- 计划白名单：agent/action/on_failure 必须落在 mission.py 的 ALLOWED_* 内；
- 危险兜底：coding 步骤复用 coding_agent 的黑名单正则；
- 步骤确认：requires_confirm 步骤登记后由语音层确认（Event + 超时）。
"""

import threading
import time

from .mission import ALLOWED_ACTIONS, ALLOWED_AGENTS, MissionStep

_STEP_CONFIRM_TIMEOUT = 90.0  # 步骤确认超时（秒）


class MissionPermissionManager:
    def __init__(self, timeout: float = _STEP_CONFIRM_TIMEOUT):
        self._timeout = timeout
        self._lock = threading.Lock()
        self._pending = {}   # step_id -> {"deadline", "event", "approved"}
        self._coding_blacklist = None

    # ── 计划白名单 ─────────────────────────────────────────
    def validate_plan(self, steps: list) -> list:
        """清洗并校验规划结果：返回合法的 MissionStep 列表（过滤非法项）。"""
        out = []
        for raw in steps:
            if not isinstance(raw, dict):
                continue
            agent = str(raw.get("agent", "")).strip().lower()
            action = str(raw.get("action", "")).strip().lower()
            if agent not in ALLOWED_AGENTS:
                continue
            if action not in ALLOWED_ACTIONS.get(agent, ()):
                continue
            params = raw.get("params") or {}
            if not isinstance(params, dict):
                params = {}
            # 参数大小限制，防 prompt 注入
            params = {k: str(v)[:500] for k, v in params.items()}
            on_failure = str(raw.get("on_failure", "abort")).strip().lower()
            if on_failure not in ("abort", "skip", "retry"):
                on_failure = "abort"
            requires_confirm = bool(raw.get("requires_confirm", False))
            # coding.modify 强制需确认（Mission 确认 ≠ 跳过修改确认）
            if agent == "coding" and action == "modify":
                requires_confirm = True
            out.append(
                MissionStep(
                    agent=agent,
                    action=action,
                    params=params,
                    requires_confirm=requires_confirm,
                    on_failure=on_failure,
                )
            )
        return out

    # ── 危险动作兜底 ───────────────────────────────────────
    def dangerous(self, step: MissionStep) -> bool:
        """返回 True 表示该步命中危险模式，应拒绝。"""
        if step.agent == "coding":
            text = (step.params.get("task") or "") + " " + (step.params.get("text") or "")
            if not text.strip():
                return False
            try:
                if self._coding_blacklist is None:
                    from coding_agent.permission_manager import PermissionManager
                    self._coding_blacklist = PermissionManager()
                return self._coding_blacklist.blacklisted(text)
            except Exception:
                return False
        return False

    # ── 步骤确认登记 ───────────────────────────────────────
    def request_confirm(self, step: MissionStep) -> str:
        with self._lock:
            self._pending[step.id] = {
                "deadline": time.time() + self._timeout,
                "event": threading.Event(),
                "approved": None,
            }
        return step.id

    def confirm_step(self, step_id: str, approved: bool) -> bool:
        with self._lock:
            p = self._pending.get(step_id)
            if p is None:
                return False
            p["approved"] = approved
            p["event"].set()
        return True

    def wait_confirm(self, step: MissionStep) -> bool:
        """阻塞等待步骤确认；超时返回 False（拒绝）。"""
        with self._lock:
            p = self._pending.get(step.id)
        if p is None:
            return False
        deadline = p["deadline"]
        remaining = max(deadline - time.time(), 0.0)
        p["event"].wait(remaining)
        with self._lock:
            approved = self._pending.get(step.id, {}).get("approved")
            self._pending.pop(step.id, None)
        return bool(approved)

    def pending(self) -> list:
        with self._lock:
            return [
                {"step_id": sid, "remaining": round(m["deadline"] - time.time(), 1)}
                for sid, m in self._pending.items()
            ]
