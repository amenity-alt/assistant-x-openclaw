#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""osascript / System Events 统一封装（零依赖，macOS 自带）。

所有 AppleScript 调用走这里：统一超时、错误归一化、返回 (code, stdout, stderr)。
"""

import subprocess


def osascript(script: str, timeout: float = 15.0):
    """执行一段 AppleScript，返回 (returncode, stdout, stderr)。"""
    try:
        p = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError:
        return -2, "", "osascript not found"


def osascript_lines(script: str, timeout: float = 15.0):
    """执行 AppleScript 并返回非空 stdout 行列表（失败返回空列表）。"""
    code, out, err = osascript(script, timeout)
    if code != 0:
        return []
    return [ln for ln in out.splitlines() if ln.strip()]


def quote(name: str) -> str:
    """AppleScript 字符串字面量转义（包双引号，转义内部引号与反斜杠）。"""
    esc = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{esc}"'
