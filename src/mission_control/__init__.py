#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Jarvis Mission Control — 目标级任务编排能力（Capability 而非 Agent）。

流程：目标 → 规划步骤 → 等待确认 → 串行执行（coding/computer/llm/vision/map）
→ 汇报。任何角色（jarvis / lin-meimei）都可通过语音触发。

用法（main.py 主循环拦截接入）：
    from mission_control import get_mission_agent
    agent = get_mission_agent()
    agent.on_plan = self._mission_on_plan
    agent.on_confirm_request = self._mission_on_confirm_request
    agent.on_mission_done = self._mission_on_done
    agent.plan_and_request("帮我分析项目并修复问题", role)
    agent.confirm(approved=True)
    agent.cancel(mission_id)
"""

import threading
import time

from .action_log import MissionLog
from .agent_registry import get_agent_registry
from .executor import MissionExecutor
from .mission import MissionStatus, MissionTask
from .permission_manager import MissionPermissionManager
from .planner import Planner
from .state_machine import StateMachine


class MissionControlAgent:
    """Mission Control 能力入口。"""

    def __init__(self):
        self._planner = Planner()
        self._perms = MissionPermissionManager()
        self._state = StateMachine()
        self._log = MissionLog()
        self._registry = get_agent_registry()
        self._executor = MissionExecutor(self._registry, self._perms, self._state, self._log)
        self._executor.set_event_callback(self._on_event)
        self._lock = threading.Lock()
        self._pending_mission = None   # 待用户确认的 mission

        # main.py 注入的回调（口播/HUD）
        self.on_plan = None            # fn(mission: MissionTask)  计划生成
        self.on_confirm_request = None  # fn(mission_id, step)     步骤确认请求
        self.on_step_done = None       # fn(mission_id, step)      步骤完成/失败
        self.on_mission_done = None    # fn(mission_id, mission)   任务完成/失败/取消

    # ── 规划与确认 ─────────────────────────────────────────
    def plan_and_request(self, goal: str, role: str = "jarvis") -> dict:
        """目标 → 规划 → 进入待确认。返回 {ok, mission|message}。"""
        with self._lock:
            if self._pending_mission is not None:
                return {"ok": False, "message": "已有待确认的任务，请先确认或取消"}
            if self._executor._current is not None:
                return {"ok": False, "message": "已有任务运行中，请稍后再试"}
        steps = self._planner.plan(goal, role)
        if not steps:
            return {"ok": False, "message": "无法规划该目标"}
        mission = MissionTask(
            goal=goal, role=role, steps=steps,
            status=MissionStatus.AWAITING_CONFIRM,
        )
        with self._lock:
            self._pending_mission = mission
        self._state.register(mission)
        self._log.record(
            {"agent": "mission", "mission": mission.id, "action": "planned",
             "goal": goal[:200], "role": role, "steps": len(steps)}
        )
        cb = self.on_plan
        if cb is not None:
            try:
                cb(mission)
            except Exception as e:
                print(f"[Mission] on_plan 回调异常: {e}")
        return {"ok": True, "mission": mission.to_dict()}

    def confirm(self, approved: bool) -> dict:
        """确认/取消待执行任务。"""
        with self._lock:
            mission = self._pending_mission
            if mission is None:
                return {"ok": False, "message": "没有待确认的任务"}
            self._pending_mission = None
        if not approved:
            try:
                self._state.set_mission_status(mission.id, MissionStatus.CANCELLED)
            except ValueError:
                pass
            self._log.record(
                {"agent": "mission", "mission": mission.id, "action": "rejected"}
            )
            return {"ok": True, "message": "已取消任务", "cancelled": True}
        mission.confirmed_at = time.time()
        return self._executor.start(mission)

    # ── 运行控制（转发执行器）──────────────────────────────
    def pause(self, mission_id: str) -> dict:
        return self._executor.pause(mission_id)

    def resume(self, mission_id: str) -> dict:
        return self._executor.resume(mission_id)

    def cancel(self, mission_id: str) -> dict:
        return self._executor.cancel(mission_id)

    def skip_step(self, mission_id: str, step_id: str) -> dict:
        return self._executor.skip_step(mission_id, step_id)

    def confirm_step(self, step_id: str, approved: bool) -> bool:
        return self._executor.confirm_step(step_id, approved)

    # ── 查询 ───────────────────────────────────────────────
    def status(self) -> dict:
        with self._lock:
            pending = self._pending_mission
        running = self._executor._current
        out = {
            "running": running,
            "pending_confirmation": pending.to_dict() if pending else None,
        }
        if running:
            m = self._state.mission(running)
            if m is not None:
                out["mission"] = m.to_dict()
        return out

    def last_pending_mission(self):
        """main.py 展示计划用：最近一次规划结果。"""
        with self._lock:
            return self._pending_mission

    # ── 事件分发 ───────────────────────────────────────────
    def _on_event(self, mission_id: str, event: dict):
        etype = event.get("type")
        if etype == "confirm_request":
            cb = self.on_confirm_request
            if cb is not None:
                try:
                    cb(mission_id, event.get("step"))
                except Exception as e:
                    print(f"[Mission] on_confirm_request 异常: {e}")
        elif etype == "step_status":
            cb = self.on_step_done
            if cb is not None:
                try:
                    cb(mission_id, event.get("step"))
                except Exception as e:
                    print(f"[Mission] on_step_done 异常: {e}")
        elif etype == "mission_done":
            cb = self.on_mission_done
            if cb is not None:
                try:
                    cb(mission_id, event.get("mission"))
                except Exception as e:
                    print(f"[Mission] on_mission_done 异常: {e}")


_agent = None
_agent_lock = threading.Lock()


def get_mission_agent() -> MissionControlAgent:
    global _agent
    with _agent_lock:
        if _agent is None:
            _agent = MissionControlAgent()
        return _agent
