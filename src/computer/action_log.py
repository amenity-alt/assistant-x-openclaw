#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""电脑操作日志：所有 Action 执行记录 JSON lines → <项目根>/logs/computer_agent.log。

方便调试与审计：时间 / Action / Target / 风险 / 结果 / 详情。
"""

import json
import os
import threading
import time

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


class ActionLog:
    def __init__(self, path=None):
        self._path = path or os.path.join(
            _PROJECT_ROOT, "logs", "computer_agent.log"
        )
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
            except Exception as e:  # 日志失败绝不影响主流程
                print(f"[Computer] 日志写入失败: {e}")

    def tail(self, n: int = 10):
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            return lines[-n:]
        except Exception:
            return []
