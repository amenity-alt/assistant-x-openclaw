#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Computer Agent 统一 Action 数据模型与风险分级。

原则：Jarvis 大脑不能直接碰系统；所有系统操作收敛为统一 Action，
由 CommandExecutor 派发执行。target 是「语义描述」而非坐标。
"""

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum


class Risk(str, Enum):
    AUTO = "auto"        # 低风险：自动执行（打开应用/截图/搜索/输入文字…）
    CONFIRM = "confirm"  # 高风险：必须用户确认（删除文件/sudo/改系统设置/发邮件…）
    DENY = "deny"        # 默认拒绝（未知危险命令/提权操作…）


# 各 action 默认风险（Phase 1 仅应用控制；后续阶段按动作扩充）
_ACTION_RISK = {
    "open_app": Risk.AUTO,
    "close_app": Risk.AUTO,
    "switch_app": Risk.AUTO,
    "type_text": Risk.AUTO,
    "press_keys": Risk.AUTO,
    "click_element": Risk.AUTO,
    "double_click_element": Risk.AUTO,
    "mouse_move": Risk.AUTO,
    "scroll": Risk.AUTO,
    "take_screenshot": Risk.AUTO,
    "get_screen_state": Risk.AUTO,
    "list_apps": Risk.AUTO,
}


@dataclass
class Action:
    action: str                    # "open_app" | "close_app" | "switch_app" | ...
    target: str = ""               # 语义目标：应用名 / UI 元素描述 / 文件路径 / 文本
    params: dict = field(default_factory=dict)
    risk: Risk = Risk.AUTO
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        # 未显式指定风险时按动作类型取默认
        if self.risk == Risk.AUTO and self.action in _ACTION_RISK:
            self.risk = _ACTION_RISK[self.action]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["risk"] = self.risk.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Action":
        return cls(
            action=d.get("action", ""),
            target=d.get("target", ""),
            params=d.get("params", {}) or {},
            risk=Risk(d.get("risk", "auto")),
            id=d.get("id", uuid.uuid4().hex[:12]),
            created_at=d.get("created_at", time.time()),
        )
