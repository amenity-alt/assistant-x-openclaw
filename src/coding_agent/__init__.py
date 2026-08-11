#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Jarvis Coding Agent — 本机 Codex CLI 编码能力模块。

Capability 而非 Agent：任何角色（jarvis / lin-meimei）都可语音触发。
Phase 1：项目分析 / 代码审查 / 运行测试 / 编码修改 / git 只读，
         Codex 在受控沙箱内执行，修改需确认，永不自动 push。

用法（Phase 2 由 main.py 主循环拦截接入）：
    from coding_agent import get_coding_agent
    agent = get_coding_agent()
    agent.handle("分析一下这个项目")   # 解析→入队，返回 True 表示已消费
"""

import threading

from . import git_manager, intent_parser, workspace_manager
from .action_log import CodingLog
from .codex_client import CodexClient
from .permission_manager import PermissionManager
from .task import CodingResult, CodingTask
from .task_manager import TaskManager


class CodingAgent:
    """编码能力入口：handle(text) / run_sync(text) / status()。"""

    def __init__(self):
        self.log = CodingLog()
        self.workspaces = workspace_manager.WorkspaceManager()
        self.permissions = PermissionManager()
        self.git = git_manager.GitManager()
        self.client = CodexClient()
        self.tasks = TaskManager(self.client, self.log, self.permissions, self.git)
        self.current_project = self.workspaces.resolve()["path"]

    # ── 入口 ────────────────────────────────────────────
    def handle(self, text: str, project: str = ""):
        """解析意图并（异步）执行/登记确认。

        返回（按类型处理，供 main.py 语音接入）：
          - False    → 未消费（非编码指令，放行大模型）；
          - Future   → auto 任务已入队执行；
          - dict     → 消费结果：waiting_confirmation / denied / success（workspace 切换）。
        """
        intent = intent_parser.parse(text)
        if intent is None:
            return False
        # 纯「切换到 X 项目」：只更新当前项目状态
        if intent.mode == "workspace":
            proj = self.workspaces.resolve(intent.project_hint)
            self.current_project = proj["path"]
            print(f"[Coding] 已切换到项目: {proj['name']}")
            return {"status": "success", "summary": f"已切换到 {proj['name']}"}
        proj = self.workspaces.resolve(project or intent.project_hint or self.current_project)
        task = CodingTask(mode=intent.mode, task=intent.task, project=proj["path"])
        verdict = self.permissions.guard(task)
        if verdict == "deny":
            self.log.record(
                {
                    "agent": "coding", "task": task.task[:200],
                    "mode": task.mode, "project": task.project,
                    "status": "denied", "detail": "黑名单拦截",
                }
            )
            print(f"[Coding] 黑名单拦截: {task.task[:80]}")
            return CodingResult(
                status="denied",
                summary="该任务命中危险模式黑名单，已拒绝",
                task_id=task.id,
            ).to_dict()
        if verdict == "confirm":
            info = self.tasks.submit(task)
            print(
                f"[Coding] 等待确认({info.get('confirm_id')}): {task.mode} {task.project}"
            )
            return info
        future = self.tasks.submit(task)
        print(
            f"[Coding] 已入队: {task.mode} project={proj['name']} "
            f"sandbox={task.sandbox}"
        )
        return future

    def run_sync(self, text: str, project: str = "", timeout: float = 330.0) -> dict:
        """同步执行（测试/确认后调用）：解析 → 执行 → 返回结果 dict。"""
        intent = intent_parser.parse(text)
        if intent is None:
            return CodingResult(status="failed", summary="无法解析为编码任务").to_dict()
        if intent.mode == "workspace":
            proj = self.workspaces.resolve(intent.project_hint)
            self.current_project = proj["path"]
            return CodingResult(status="success", summary=f"已切换到 {proj['name']}").to_dict()
        proj = self.workspaces.resolve(project or intent.project_hint or self.current_project)
        task = CodingTask(mode=intent.mode, task=intent.task, project=proj["path"])
        verdict = self.permissions.guard(task)
        if verdict == "deny":
            return CodingResult(status="denied", summary="黑名单拦截", task_id=task.id).to_dict()
        if verdict == "confirm":
            return self.tasks.submit(task)
        future = self.tasks.submit(task)
        if hasattr(future, "result"):
            return future.result(timeout=timeout)
        return future

    # ── 查询 ────────────────────────────────────────────
    def status(self) -> dict:
        return {
            "codex": self.client.version(),
            "workspaces": self.workspaces.describe(),
            "pending_confirmations": self.permissions.pending_count(),
        }

    def confirm(self, confirm_id: str, approved: bool):
        """Phase 2 语音确认回调：approve/deny 后执行或取消任务。"""
        return self.tasks.confirm_result(confirm_id, approved)

    def pending_confirmations(self) -> list:
        """待确认任务（Phase 2 语音接入：用户说确认/取消时按 confirm_id 回调）。"""
        return self.tasks.pending_confirmations()

    def last_result(self) -> dict:
        return self.tasks.last_result()


# ── 单例 ────────────────────────────────────────────────
_agent = None
_agent_lock = threading.Lock()


def get_coding_agent() -> CodingAgent:
    global _agent
    with _agent_lock:
        if _agent is None:
            _agent = CodingAgent()
        return _agent
