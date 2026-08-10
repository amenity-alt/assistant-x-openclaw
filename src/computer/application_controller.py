#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""macOS 应用控制：打开 / 关闭 / 切换（前台激活）。

实现：`open -a` + osascript（System Events / Apple Events），零第三方依赖。
语义定位优先：应用名先归一化（大小写 / 中文别名），再按标准目录+mdfind 解析
真实应用名，避免直接拼接用户输入执行命令。
"""

import os
import subprocess
import threading
import time

from .apple_script import osascript, quote

# 已知别名 → 规范应用名（进程名/包名）。「浏览器」等歧义词在解析时按已安装应用决策。
APP_ALIASES = {
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "谷歌浏览器": "Google Chrome",
    "浏览器": None,  # 运行时解析：装了 Chrome 用 Chrome，否则 Safari
    "safari": "Safari",
    "terminal": "Terminal",
    "终端": "Terminal",
    "iterm": "iTerm",
    "iterm2": "iTerm",
    "wechat": "WeChat",
    "微信": "WeChat",
    "notes": "Notes",
    "备忘录": "Notes",
    "calculator": "Calculator",
    "计算器": "Calculator",
    "mail": "Mail",
    "邮件": "Mail",
    "calendar": "Calendar",
    "日历": "Calendar",
    "photos": "Photos",
    "照片": "Photos",
    "music": "Music",
    "音乐": "Music",
    "messages": "Messages",
    "信息": "Messages",
    "system settings": "System Settings",
    "系统设置": "System Settings",
    "设置": "System Settings",
    "tencent meeting": "TencentMeeting",
    "腾讯会议": "TencentMeeting",
    "meeting": "TencentMeeting",
    "obsidian": "Obsidian",
    "finder": "Finder",
    "访达": "Finder",
    "textedit": "TextEdit",
    "文本编辑": "TextEdit",
    "stickies": "Stickies",
    "便笺": "Stickies",
    "reminders": "Reminders",
    "提醒事项": "Reminders",
    "preview": "Preview",
    "预览": "Preview",
    "maps": "Maps",
    "地图": "Maps",
    "activity monitor": "Activity Monitor",
    "活动监视器": "Activity Monitor",
    "disk utility": "Disk Utility",
    "磁盘工具": "Disk Utility",
    "system information": "System Information",
    "系统信息": "System Information",
    "console": "Console",
    "控制台": "Console",
    "launchpad": "Launchpad",
    "启动台": "Launchpad",
    "screenshot": "Screenshot",
    "截屏": "Screenshot",
    "屏幕快照": "Screenshot",
}

_APP_DIRS = [
    "/Applications",
    "/System/Applications",
    "/System/Applications/Utilities",
    os.path.expanduser("~/Applications"),
]

# 应用索引缓存：真实路径列表（避免每次 mdfind，索引 10 分钟失效重建）
_index_lock = threading.Lock()
_index_cache = (0.0, [])


def _norm(name: str) -> str:
    """应用名归一化：小写、去空白、去常见后缀噪音词。"""
    n = (name or "").strip().lower()
    for suffix in ("应用", "程序", "app", "application", "the"):
        if n.endswith(suffix) and len(n) > len(suffix):
            n = n[: -len(suffix)].strip()
    return n


def _scan_app_paths() -> list:
    """扫描标准目录下的 .app 路径（缓存 10 分钟）。"""
    global _index_cache
    now = time.time()
    with _index_lock:
        if now - _index_cache[0] < 600:
            return _index_cache[1]
    paths = []
    seen = set()
    for d in _APP_DIRS:
        if not os.path.isdir(d):
            continue
        try:
            for entry in os.listdir(d):
                if entry.endswith(".app"):
                    p = os.path.join(d, entry)
                    if p not in seen:
                        seen.add(p)
                        paths.append(p)
        except OSError:
            continue
    # mdfind 兜底（第三方 App 装在别的目录），失败不影响标准目录结果
    try:
        p = subprocess.run(
            ["mdfind", "kMDItemContentType == 'com.apple.application-bundle'"],
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        if p.returncode == 0:
            for ln in p.stdout.splitlines():
                ln = ln.strip()
                if ln.endswith(".app") and ln not in seen:
                    seen.add(ln)
                    paths.append(ln)
    except Exception:
        pass
    with _index_lock:
        _index_cache = (now, paths)
    return paths


def resolve(name: str):
    """把用户说的应用名解析为 (规范名, 路径|None)。

    顺序：别名表 → 标准目录精确匹配 → 全索引模糊（包含）匹配 → 原样返回兜底
    （最后交给 `open -a` 由 LaunchServices 解析）。
    """
    n = _norm(name)
    if not n:
        return name, None
    alias = APP_ALIASES.get(n)
    if n in APP_ALIASES:
        # 「浏览器」等歧义别名：运行时按已安装应用决策
        if alias is None:
            paths = _scan_app_paths()
            chrome = next(
                (p for p in paths if p.lower().endswith("google chrome.app")), None
            )
            alias = "Google Chrome" if chrome else "Safari"
        return alias, next(
            (p for p in _scan_app_paths() if p.lower().endswith(f"{alias.lower()}.app")),
            None,
        )
    paths = _scan_app_paths()
    exact = next(
        (p for p in paths if os.path.basename(p)[: -len(".app")].lower() == n), None
    )
    if exact:
        return os.path.basename(exact)[: -len(".app")], exact
    fuzzy = next(
        (p for p in paths if n in os.path.basename(p)[: -len(".app")].lower()), None
    )
    if fuzzy:
        return os.path.basename(fuzzy)[: -len(".app")], fuzzy
    return name, None


def _open_path(display: str, path) -> str:
    """打开应用：有路径用 `open <path>`，否则 `open -a <display>` 交 LaunchServices。"""
    try:
        if path:
            cmd = ["open", path]
        else:
            cmd = ["open", "-a", display]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20.0)
        if p.returncode == 0:
            return ""
        err = p.stderr.strip() or f"open failed (code {p.returncode})"
        return f"打开失败: {err}"
    except subprocess.TimeoutExpired:
        return "打开超时"
    except Exception as e:
        return f"打开异常: {e}"


def open_app(name: str) -> dict:
    """打开（并激活）应用。返回 {ok, message}。"""
    display, path = resolve(name)
    err = _open_path(display, path)
    if err:
        return {"ok": False, "message": err}
    activate_app(display)  # 打开后置前，保证用户看到
    return {"ok": True, "message": f"已打开 {display}", "display": display}


def activate_app(display: str) -> dict:
    """把应用切到前台（未运行则先启动）。"""
    code, out, err = osascript(f"tell application {quote(display)} to activate")
    if code == 0:
        return {"ok": True, "message": f"已切换到 {display}", "display": display}
    return {"ok": False, "message": f"激活失败: {err or out}", "display": display}


def close_app(name: str) -> dict:
    """优雅退出应用：先 Apple Events quit，失败再走 System Events 菜单退出。"""
    display, path = resolve(name)
    code, out, err = osascript(
        f"tell application {quote(display)} to quit", timeout=20.0
    )
    if code == 0:
        return {"ok": True, "message": f"已关闭 {display}", "display": display}
    # 降级：System Events 点击 Quit 菜单（需要辅助功能权限）
    code2, out2, err2 = osascript(
        f'tell application "System Events" to tell process {quote(display)} '
        f'to click menu item {quote("Quit " + display)} of menu 1 of '
        f'menu bar item 1 of menu bar 1',
        timeout=20.0,
    )
    if code2 == 0:
        return {"ok": True, "message": f"已关闭 {display}", "display": display}
    return {"ok": False, "message": f"关闭失败: {err or out} / {err2 or out2}", "display": display}


def list_running_apps() -> list:
    """运行中的应用进程名列表（调试/「现在开着什么」用）。"""
    code, out, err = osascript(
        'tell application "System Events" to get name of every process '
        'whose background only is false',
        timeout=15.0,
    )
    if code != 0:
        return []
    return [x for x in out.replace(",", "\n").splitlines() if x.strip()]
