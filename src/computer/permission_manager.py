#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""macOS 权限（TCC）状态探测与引导。

Computer Agent 依赖「辅助功能」权限来读写 UI 元素（System Events）。
只探测与引导，不申请提权、不写系统设置。
"""

import subprocess
import threading


class PermissionManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._cache = None  # 缓存一次探测结果（权限变化需用户重启应用，短期缓存合理）

    def accessibility_enabled(self) -> bool:
        """探测辅助功能（Accessibility）权限是否已授予。

        走 osascript System Events 询问（零依赖），失败按未授权处理。
        """
        with self._lock:
            if self._cache is not None:
                return self._cache
            ok = self._probe()
            self._cache = ok
            return ok

    @staticmethod
    def _probe() -> bool:
        try:
            p = subprocess.run(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to UI elements enabled',
                ],
                capture_output=True,
                text=True,
                timeout=10.0,
            )
            return p.returncode == 0 and p.stdout.strip().lower() == "true"
        except Exception:
            return False

    @staticmethod
    def guidance() -> str:
        """未授权时的引导文案（中文，供语音/通知口播）。"""
        return (
            "电脑控制需要辅助功能权限。请在 系统设置 → 隐私与安全性 → 辅助功能 中，"
            "勾选运行语音助手的终端应用，然后重新启动语音助手。"
        )

    @staticmethod
    def open_privacy_settings():
        """打开辅助功能设置页（辅助用户手动授权）。"""
        try:
            subprocess.run(
                [
                    "open",
                    "x-apple.systempreferences:"
                    "com.apple.preference.security?Privacy_Accessibility",
                ],
                timeout=10.0,
            )
        except Exception as e:
            print(f"[Computer] 打开权限设置失败: {e}")
