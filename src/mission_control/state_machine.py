#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Mission / Step 状态机：合法迁移校验 + 迁移执行。

规则集中在此处，executor/控制入口只调用 transition()，非法迁移抛 ValueError。
"""

import threading

from .mission import MissionStatus, StepStatus

# ── Mission 合法迁移表 ─────────────────────────────────────
_MISSION_TRANSITIONS = {
    MissionStatus.PLANNED: {
        MissionStatus.AWAITING_CONFIRM,
        MissionStatus.FAILED,
        MissionStatus.CANCELLED,
    },
    MissionStatus.AWAITING_CONFIRM: {
        MissionStatus.RUNNING,
        MissionStatus.CANCELLED,
        MissionStatus.FAILED,
    },
    MissionStatus.RUNNING: {
        MissionStatus.PAUSED,
        MissionStatus.COMPLETED,
        MissionStatus.FAILED,
        MissionStatus.CANCELLED,
    },
    MissionStatus.PAUSED: {
        MissionStatus.RUNNING,       # 继续
        MissionStatus.CANCELLED,     # 取消
        MissionStatus.COMPLETED,     # 暂停期间任务自然完成
        MissionStatus.FAILED,        # 暂停期间步骤失败
    },
    MissionStatus.COMPLETED: set(),
    MissionStatus.FAILED: {MissionStatus.RUNNING},  # 用户要求重试
    MissionStatus.CANCELLED: set(),
}

# ── Step 合法迁移表 ────────────────────────────────────────
_STEP_TRANSITIONS = {
    StepStatus.PENDING: {StepStatus.READY, StepStatus.SKIPPED, StepStatus.ABORTED},
    StepStatus.READY: {StepStatus.RUNNING, StepStatus.SKIPPED, StepStatus.ABORTED},
    StepStatus.RUNNING: {StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.ABORTED},
    StepStatus.SUCCEEDED: {StepStatus.READY},  # retry 重置
    StepStatus.FAILED: {StepStatus.READY},     # retry 重置
    StepStatus.SKIPPED: set(),
    StepStatus.ABORTED: set(),
}


class StateMachine:
    """进程内单例状态机（mission 状态 + 各 step 状态）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._missions = {}   # mission_id -> MissionTask

    def register(self, mission):
        with self._lock:
            self._missions[mission.id] = mission

    def unregister(self, mission_id):
        with self._lock:
            self._missions.pop(mission_id, None)

    def mission(self, mission_id):
        with self._lock:
            return self._missions.get(mission_id)

    def set_mission_status(self, mission_id: str, to: MissionStatus):
        with self._lock:
            m = self._missions.get(mission_id)
            if m is None:
                raise ValueError(f"未知 mission: {mission_id}")
            frm = m.status
            if frm == to:
                return
            allowed = _MISSION_TRANSITIONS.get(frm, set())
            if to not in allowed:
                raise ValueError(
                    f"非法 mission 迁移: {frm.value} -> {to.value}"
                )
            m.status = to

    def set_step_status(self, mission_id: str, step_id: str, to: StepStatus):
        with self._lock:
            m = self._missions.get(mission_id)
            if m is None:
                raise ValueError(f"未知 mission: {mission_id}")
            step = m.step(step_id)
            if step is None:
                raise ValueError(f"未知 step: {step_id}")
            frm = step.status
            if frm == to:
                return
            allowed = _STEP_TRANSITIONS.get(frm, set())
            if to not in allowed:
                raise ValueError(
                    f"非法 step 迁移: {step_id} {frm.value} -> {to.value}"
                )
            step.status = to
