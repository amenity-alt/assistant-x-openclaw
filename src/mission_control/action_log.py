#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Mission Control 审计日志：JSON lines → <项目根>/logs/mission_control.log。

记录：mission 创建 / 状态迁移 / 步骤结果 / 确认动作 / 控制指令。
"""

import json
import os
import threading
import time

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


class MissionLog:
    def __init__(self, path=None):
        self._path = path or os.path.join(_PROJECT_ROOT, "logs", "mission_control.log")
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._lock = threading.Lock()

    @property
    def path(self) -> str:
        return self._path

    def record(self, entry: dict):
        entry = dict(entry)
        entry.setdefault("ts", time.strftime("%Y-%m-%d %H:%M:%S"))
        with self._lock:
            try:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as e:
                print(f"[Mission] 日志写入失败: {e}")
