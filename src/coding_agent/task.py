#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Coding Agent 统一任务模型：CodingTask / CodingResult + mode→沙箱映射。

原则：Jarvis/大脑永不直接执行 shell 修改代码；一切编码任务收敛为
CodingTask，经 CodexClient 在受控沙箱内执行。沙箱由 mode 强制推导，
任务本身不能自定义权限。
"""

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum


class CodingMode(str, Enum):
    ANALYZE = "analyze"   # 项目分析（只读）
    REVIEW = "review"     # 代码审查（只读）
    TEST = "test"         # 运行测试（workspace-write：允许写构建产物）
    MODIFY = "modify"     # 代码修改（workspace-write，必须用户确认）
    GIT = "git"           # git 操作（status/diff/log 只读；commit/push 需确认）


# mode → Codex 沙箱（强制映射，任务不可覆盖）
MODE_SANDBOX = {
    CodingMode.ANALYZE: "read-only",
    CodingMode.REVIEW: "read-only",
    CodingMode.TEST: "workspace-write",
    CodingMode.MODIFY: "workspace-write",
    CodingMode.GIT: "",
}


# 需要用户确认的 mode（Phase 1 起即生效；push 额外单独确认）
MODE_NEEDS_CONFIRM = {CodingMode.MODIFY}


@dataclass
class CodingTask:
    mode: str                  # CodingMode 值
    task: str = ""             # 自然语言任务描述
    project: str = ""          # 目标项目绝对路径（git 仓库）
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)

    @property
    def sandbox(self) -> str:
        return MODE_SANDBOX.get(CodingMode(self.mode), "read-only")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sandbox"] = self.sandbox
        return d


@dataclass
class CodingResult:
    status: str = "failed"     # success | failed | denied | cancelled | waiting
    summary: str = ""          # 最终 agent_message 文本
    files_changed: list = field(default_factory=list)   # [{path, kind}]
    commands: list = field(default_factory=list)        # [{command, exit_code}]
    git_diff: str = ""         # diff --stat 摘要
    usage: dict = field(default_factory=dict)
    stderr: str = ""
    task_id: str = ""
    elapsed: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)
