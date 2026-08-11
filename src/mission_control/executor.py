#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Mission 执行器：串行调度 + 步骤确认 + 失败策略 + 运行控制。

线程模型：每个 Mission 一个后台线程；同一时刻仅允许一个 Mission 运行。
控制（pause/resume/cancel/skip_step）在步骤边界生效，不打断底层 Agent
正在执行的原子操作（Phase 1 约束）。
"""

import threading
import time

from . import mission as M
from .state_machine import StateMachine


class MissionExecutor:
    def __init__(self, registry, perms: "MissionPermissionManager",
                 state: StateMachine, log: "MissionLog"):
        self._registry = registry
        self._perms = perms
        self._state = state
        self._log = log
        self._lock = threading.Lock()
        self._current = None       # 当前运行 mission_id
        self._pause_event = threading.Event()
        self._cancel_event = threading.Event()
        self._skip_ids = set()     # 用户跳过的 step_id
        self._on_event = None      # main.py 回调: fn(mission_id, event: dict)
        self._confirm_pending_step = None   # 当前等待确认的 step_id

    # ── 事件绑定 ──────────────────────────────────────────
    def set_event_callback(self, fn):
        self._on_event = fn

    def _emit(self, mission_id: str, event: dict):
        fn = self._on_event
        if fn is not None:
            try:
                fn(mission_id, event)
            except Exception as e:
                print(f"[Mission] 事件回调异常: {e}")

    # ── 启动 ──────────────────────────────────────────────
    def start(self, mission: M.MissionTask):
        with self._lock:
            if self._current is not None:
                return {"ok": False, "message": "已有任务运行中", "mission_id": mission.id}
            self._current = mission.id
            self._pause_event.clear()
            self._cancel_event.clear()
            self._skip_ids.clear()
        self._state.register(mission)
        threading.Thread(
            target=self._run, args=(mission,), daemon=True,
            name=f"mission-{mission.id}",
        ).start()
        return {"ok": True, "mission_id": mission.id}

    # ── 运行控制（步骤边界生效）────────────────────────────
    def pause(self, mission_id: str) -> dict:
        with self._lock:
            if self._current != mission_id:
                return {"ok": False, "message": "任务未在运行"}
        try:
            self._state.set_mission_status(mission_id, M.MissionStatus.PAUSED)
        except ValueError:
            return {"ok": False, "message": "当前状态不可暂停"}
        self._pause_event.set()
        self._log.record({"agent": "mission", "mission": mission_id, "action": "pause"})
        self._emit(mission_id, {"type": "status", "status": "paused"})
        return {"ok": True, "message": "已暂停"}

    def resume(self, mission_id: str) -> dict:
        try:
            self._state.set_mission_status(mission_id, M.MissionStatus.RUNNING)
        except ValueError:
            return {"ok": False, "message": "当前状态不可恢复"}
        self._pause_event.clear()
        self._log.record({"agent": "mission", "mission": mission_id, "action": "resume"})
        self._emit(mission_id, {"type": "status", "status": "running"})
        return {"ok": True, "message": "已继续"}

    def cancel(self, mission_id: str) -> dict:
        with self._lock:
            if self._current != mission_id:
                return {"ok": False, "message": "任务未在运行"}
        self._cancel_event.set()
        self._pause_event.clear()   # 取消时解除暂停等待
        try:
            self._state.set_mission_status(mission_id, M.MissionStatus.CANCELLED)
        except ValueError:
            pass
        self._log.record({"agent": "mission", "mission": mission_id, "action": "cancel"})
        self._emit(mission_id, {"type": "status", "status": "cancelled"})
        return {"ok": True, "message": "正在停止任务"}

    def skip_step(self, mission_id: str, step_id: str) -> dict:
        with self._lock:
            if self._current != mission_id:
                return {"ok": False, "message": "任务未在运行"}
            self._skip_ids.add(step_id)
        self._log.record({"agent": "mission", "mission": mission_id, "step": step_id, "action": "skip"})
        return {"ok": True, "message": "将跳过该步骤"}

    def confirm_step(self, step_id: str, approved: bool) -> bool:
        with self._lock:
            pending = self._confirm_pending_step
        if pending != step_id:
            return False
        return self._perms.confirm_step(step_id, approved)

    # ── 执行主循环 ────────────────────────────────────────
    def _run(self, mission: M.MissionTask):
        mission_id = mission.id
        try:
            self._state.set_mission_status(mission_id, M.MissionStatus.RUNNING)
            self._log.record(
                {"agent": "mission", "mission": mission_id, "action": "start",
                 "goal": mission.goal[:200], "role": mission.role}
            )
            for idx, step in enumerate(mission.steps):
                step.index = idx
                if self._cancel_event.is_set():
                    break
                self._wait_if_paused(mission_id)
                if self._cancel_event.is_set():
                    break
                if step.id in self._skip_ids:
                    self._state.set_step_status(mission_id, step.id, M.StepStatus.SKIPPED)
                    self._emit(mission_id, {"type": "step_status", "step": step.to_dict()})
                    continue
                if self._perms.dangerous(step):
                    self._fail_step(mission, step, "该步骤命中危险模式黑名单，已拒绝")
                    break
                # 步骤确认
                if step.requires_confirm:
                    self._state.set_step_status(mission_id, step.id, M.StepStatus.READY)
                    self._perms.request_confirm(step)
                    with self._lock:
                        self._confirm_pending_step = step.id
                    self._emit(mission_id, {"type": "confirm_request", "step": step.to_dict()})
                    approved = self._perms.wait_confirm(step)
                    with self._lock:
                        self._confirm_pending_step = None
                    if self._cancel_event.is_set():
                        self._state.set_step_status(mission_id, step.id, M.StepStatus.ABORTED)
                        break
                    if not approved:
                        self._state.set_step_status(mission_id, step.id, M.StepStatus.SKIPPED)
                        self._log.record(
                            {"agent": "mission", "mission": mission_id, "step": step.id,
                             "action": "confirm_denied"}
                        )
                        self._emit(mission_id, {"type": "step_status", "step": step.to_dict()})
                        continue
                # 执行（含 retry 循环）
                attempts = 0
                while True:
                    try:
                        self._state.set_step_status(mission_id, step.id, M.StepStatus.READY)
                    except ValueError:
                        pass  # 可能已是 READY（重试分支）
                    self._state.set_step_status(mission_id, step.id, M.StepStatus.RUNNING)
                    step.started_at = time.time()
                    self._emit(mission_id, {"type": "step_status", "step": step.to_dict()})
                    adapter = self._registry.get(step.agent)
                    if adapter is None:
                        self._fail_step(mission, step, f"未知 Agent: {step.agent}")
                        return
                    try:
                        result = adapter.execute(step, mission.role)
                    except Exception as e:
                        result = M.AgentResult(status="failed", summary=f"执行异常: {e}")
                    step.finished_at = time.time()
                    step.result = result.to_dict()
                    if result.status == "success":
                        self._state.set_step_status(mission_id, step.id, M.StepStatus.SUCCEEDED)
                        self._log.record(
                            {"agent": "mission", "mission": mission_id, "step": step.id,
                             "agent_used": step.agent, "status": "succeeded",
                             "summary": (result.summary or "")[:200]}
                        )
                        self._emit(mission_id, {"type": "step_status", "step": step.to_dict()})
                        break
                    if step.on_failure == "skip":
                        self._state.set_step_status(mission_id, step.id, M.StepStatus.SKIPPED)
                        self._emit(mission_id, {"type": "step_status", "step": step.to_dict()})
                        break
                    if step.on_failure == "retry" and attempts < 2:
                        attempts += 1
                        step.retries = attempts
                        self._state.set_step_status(mission_id, step.id, M.StepStatus.READY)
                        self._emit(mission_id, {"type": "step_status", "step": step.to_dict()})
                        continue
                    self._fail_step(mission, step, result.summary or "执行失败")
                    return
            else:
                self._state.set_mission_status(mission_id, M.MissionStatus.COMPLETED)
                mission.finished_at = time.time()
                mission.summary = self._summarize(mission)
                self._log.record(
                    {"agent": "mission", "mission": mission_id, "status": "completed",
                     "summary": mission.summary[:300]}
                )
                self._emit(mission_id, {"type": "mission_done", "mission": mission.to_dict()})
                self._finish(mission_id)
                return
            # 取消或失败
            self._finish(mission_id)
        except Exception as e:
            mission.error = str(e)
            try:
                self._state.set_mission_status(mission_id, M.MissionStatus.FAILED)
            except ValueError:
                pass
            self._log.record(
                {"agent": "mission", "mission": mission_id, "status": "failed", "error": str(e)}
            )
            self._emit(mission_id, {"type": "mission_done", "mission": mission.to_dict()})
            self._finish(mission_id)

    def _fail_step(self, mission, step, reason: str):
        step.error = reason
        step.finished_at = time.time()
        try:
            self._state.set_step_status(mission.id, step.id, M.StepStatus.FAILED)
        except ValueError:
            pass
        self._log.record(
            {"agent": "mission", "mission": mission.id, "step": step.id,
             "status": "failed", "error": reason[:200]}
        )
        self._emit(mission.id, {"type": "step_status", "step": step.to_dict()})
        try:
            self._state.set_mission_status(mission.id, M.MissionStatus.FAILED)
        except ValueError:
            pass
        mission.finished_at = time.time()
        mission.summary = f"第 {step.index + 1} 步失败：{reason}"
        self._emit(mission.id, {"type": "mission_done", "mission": mission.to_dict()})

    def _wait_if_paused(self, mission_id: str):
        while self._pause_event.is_set() and not self._cancel_event.is_set():
            self._pause_event.wait(0.5)

    def _summarize(self, mission: M.MissionTask) -> str:
        done = sum(1 for s in mission.steps if s.status == M.StepStatus.SUCCEEDED)
        skipped = sum(1 for s in mission.steps if s.status == M.StepStatus.SKIPPED)
        parts = [f"{done}/{len(mission.steps)} steps completed"]
        if skipped:
            parts.append(f"{skipped} skipped")
        return "; ".join(parts)

    def _finish(self, mission_id: str):
        with self._lock:
            if self._current == mission_id:
                self._current = None
            self._skip_ids.clear()
            self._confirm_pending_step = None
        self._pause_event.clear()
        self._cancel_event.clear()
