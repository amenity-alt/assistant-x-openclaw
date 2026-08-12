#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Short Drama — 阶段状态机（合法迁移 + 线程安全，风格与 mission 一致）。"""

import threading

from .models import DramaStatus

# ── Drama 合法迁移表 ─────────────────────────────────────
_DRAMA_TRANSITIONS = {
    DramaStatus.IDLE: {DramaStatus.COLLECTING},
    DramaStatus.COLLECTING: {
        DramaStatus.PLANNING, DramaStatus.PAUSED, DramaStatus.FAILED,
    },
    DramaStatus.PLANNING: {
        DramaStatus.AWAITING_CONFIRM, DramaStatus.PAUSED, DramaStatus.FAILED,
    },
    DramaStatus.AWAITING_CONFIRM: {
        DramaStatus.EPISODE_DESIGN, DramaStatus.PROMPTS, DramaStatus.PLANNING,
        DramaStatus.COMPLETED, DramaStatus.PAUSED, DramaStatus.FAILED,
    },
    DramaStatus.EPISODE_DESIGN: {
        DramaStatus.AWAITING_CONFIRM, DramaStatus.PAUSED, DramaStatus.FAILED,
    },
    DramaStatus.PROMPTS: {
        DramaStatus.AWAITING_CONFIRM, DramaStatus.COMPLETED,
        DramaStatus.PAUSED, DramaStatus.FAILED,
    },
    DramaStatus.COMPLETED: {
        DramaStatus.PLANNING, DramaStatus.EPISODE_DESIGN, DramaStatus.PAUSED,
    },
    DramaStatus.PAUSED: {
        DramaStatus.PLANNING, DramaStatus.EPISODE_DESIGN, DramaStatus.PROMPTS,
        DramaStatus.COMPLETED, DramaStatus.AWAITING_CONFIRM, DramaStatus.FAILED,
    },
    DramaStatus.FAILED: {DramaStatus.PLANNING, DramaStatus.PAUSED},
}


class DramaStateMachine:
    """进程内单例：project 状态迁移校验。"""

    def __init__(self):
        self._lock = threading.Lock()

    def can(self, frm: DramaStatus, to: DramaStatus) -> bool:
        return to in _DRAMA_TRANSITIONS.get(frm, set())

    def transition(self, project, to: DramaStatus):
        with self._lock:
            frm = project.status
            if frm == to:
                return
            if not self.can(frm, to):
                raise ValueError(
                    f"非法短剧状态迁移: {frm.value} -> {to.value}"
                )
            project.status = to
            project.updated_at = __import__("time").time()
            project.history.append({
                "t": project.updated_at,
                "from": frm.value,
                "to": to.value,
            })
