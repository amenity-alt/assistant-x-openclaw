#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Computer Control System — Jarvis 电脑控制能力模块。

Capability 而非 Agent：任何角色（jarvis / lin-meimei）都可语音触发。
Phase 1：应用控制（打开/关闭/切换 App）+ 权限探测 + 操作日志。

用法（Phase 5 由 main.py 主循环拦截接入）：
    from computer import get_computer_agent
    agent = get_computer_agent()
    agent.handle("打开Chrome")   # 解析→入队，返回 True 表示已消费
"""

import threading

from .action import Action, Risk
from .action_log import ActionLog
from .command_executor import CommandExecutor
from . import application_controller, intent_parser, permission_manager


class ComputerAgent:
    """电脑控制能力入口：handle(text) / execute_action(action) / permissions()。"""

    def __init__(self):
        self.log = ActionLog()
        self.executor = CommandExecutor(self.log)
        self.permissions = permission_manager.PermissionManager()

    # ── 入口 ────────────────────────────────────────────
    def handle(self, text: str) -> bool:
        """解析并异步入队执行；返回 True 表示指令已被消费（不进大模型）。

        权限未授权时不执行，仅返回引导信息（写入日志）。
        """
        action = intent_parser.parse(text)
        if action is None:
            return False
        if not self.permissions.accessibility_enabled():
            msg = self.permissions.guidance()
            self.log.record(
                {
                    "agent": "computer",
                    "action": action.action,
                    "target": action.target,
                    "ok": False,
                    "detail": "permission denied",
                    "action_id": action.id,
                }
            )
            print(f"[Computer] 权限未授权，拒绝执行: {text}")
            return True  # 已消费（不进大模型），但未执行
        self.executor.submit(action)
        print(
            f"[Computer] 已入队: {action.action} target={action.target!r} "
            f"risk={action.risk.value}"
        )
        return True

    def execute_action(self, action: Action) -> dict:
        """同步执行一个 Action（内部测试/确认回调用）。"""
        return self.executor.execute(action)

    # ── 查询 ────────────────────────────────────────────
    def accessibility_enabled(self) -> bool:
        return self.permissions.accessibility_enabled()

    def last_result(self) -> dict:
        return self.executor.last_result()


# ── 单例 ────────────────────────────────────────────────
_agent = None
_agent_lock = threading.Lock()


def get_computer_agent() -> ComputerAgent:
    global _agent
    with _agent_lock:
        if _agent is None:
            _agent = ComputerAgent()
        return _agent
