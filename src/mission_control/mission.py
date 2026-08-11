#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Jarvis Mission Control — 统一任务数据模型。

Mission（目标）→ Steps（有序步骤）→ AgentResult（每步结果）。
风格与 coding_agent/task.py 一致：dataclass + to_dict，无数据库。
"""

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum


class MissionStatus(str, Enum):
    PLANNED = "planned"
    AWAITING_CONFIRM = "awaiting_confirm"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    ABORTED = "aborted"


# 允许规划的 Agent 白名单（planner/executor 共用）
ALLOWED_AGENTS = ("coding", "computer", "llm", "vision", "map")

# 各 Agent 允许的动作（白名单）
ALLOWED_ACTIONS = {
    "coding": ("analyze", "review", "test", "modify", "git"),
    "computer": (
        "open_app", "close_app", "switch_app", "type_text", "press_keys",
        "click_element", "double_click_element", "mouse_move", "scroll",
        "take_screenshot", "get_screen_state", "list_apps",
    ),
    "llm": ("summarize", "translate", "generate", "ask"),
    "vision": ("scan", "describe"),
    "map": ("locate", "news", "reset"),
}


@dataclass
class MissionStep:
    agent: str                   # 执行 Agent："coding" | "computer" | "llm" | ...
    action: str                  # Agent 语义动作："codex.analyze" → action="analyze"
    params: dict = field(default_factory=dict)
    requires_confirm: bool = False
    on_failure: str = "abort"    # "abort" | "skip" | "retry"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    index: int = 0
    status: StepStatus = StepStatus.PENDING
    result: dict = field(default_factory=dict)
    started_at: float = 0.0
    finished_at: float = 0.0
    error: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class AgentResult:
    status: str = "success"    # success | failed | denied | cancelled | waiting
    summary: str = ""          # 人类可读结果
    data: dict = field(default_factory=dict)   # Agent 特有数据
    task_id: str = ""
    elapsed: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MissionTask:
    goal: str                    # 用户原始目标
    role: str = "jarvis"         # 口播语言来源
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: MissionStatus = MissionStatus.PLANNED
    steps: list = field(default_factory=list)   # List[MissionStep]
    summary: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    confirmed_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["steps"] = [s.to_dict() for s in self.steps]
        return d

    def step(self, step_id: str):
        for s in self.steps:
            if s.id == step_id:
                return s
        return None
