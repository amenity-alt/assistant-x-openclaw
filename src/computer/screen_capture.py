#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""屏幕截图（系统自带 screencapture，零依赖）。

截图存 <项目根>/logs/screenshots/（gitignore）。截图失败（未授权屏幕录制等）
返回 None，由上层给出权限引导。
"""

import os
import subprocess
import time

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
SCREENSHOT_DIR = os.path.join(_PROJECT_ROOT, "logs", "screenshots")
_MIN_SIZE = 10 * 1024  # 正常截图远大于此；过小视为截图失败/被系统拦截


def _ensure_dir():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def capture(path: str = None) -> str:
    """全屏截图 → 返回 PNG 路径；失败返回 None。

    -x：不播放声音、不显示阴影。
    """
    _ensure_dir()
    path = path or os.path.join(
        SCREENSHOT_DIR, f"screen_{time.strftime('%Y%m%d_%H%M%S')}.png"
    )
    try:
        p = subprocess.run(
            ["screencapture", "-x", path], capture_output=True, text=True, timeout=15.0
        )
        if p.returncode != 0:
            print(f"[Computer] 截图失败: {p.stderr.strip()}")
            return None
        if not os.path.exists(path) or os.path.getsize(path) < _MIN_SIZE:
            print("[Computer] 截图文件过小，可能缺少屏幕录制权限")
            return None
        return path
    except Exception as e:
        print(f"[Computer] 截图异常: {e}")
        return None
