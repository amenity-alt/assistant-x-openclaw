#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
地图态势服务保障（map dashboard service）

为 Flutter overlay 左上角的「地图态势卡片」（WebView 加载 jarvis-map-module）
确保本地静态服务在线：服务未运行时自动拉起（优先 preview 构建产物，其次 dev），
随进程退出清理。作为激活联动钩子接入 lifecycle 注册表——唤醒时确认服务在线，
overlay 端负责卡片的显示/隐藏（wake 显示 / hide 隐藏），本模块不做任何浏览器操作。

设计原则（与 dock_control / media_pause 一致）：**软失败**。
  - 服务拉起失败或等待超时 → 只记日志，绝不影响语音主流程。
  - 端口已被占用（如用户手动起了 dev server）→ 直接复用，不重复拉起。
"""

import logging
import os
import socket
import subprocess
import tempfile
import threading
import time

from lifecycle import LifecycleHook

logger = logging.getLogger(__name__)

MAP_URL = "http://127.0.0.1:5199"
MAP_HOST = "127.0.0.1"
MAP_PORT = 5199
# jarvis-map-module 位于本文件（src/）的上一级目录
MAP_MODULE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "jarvis-map-module"
)
_SERVER_LOG = os.path.join(tempfile.gettempdir(), "jarvis_map_server.log")


class MapDashboardController:
    def __init__(self):
        self._server_proc = None
        self._lock = threading.Lock()
        if os.path.isdir(MAP_MODULE_DIR):
            print(f"[Map] 地图服务保障可用：{MAP_URL}/?embed=1（overlay 左上角卡片加载）")

    def server_alive(self) -> bool:
        try:
            with socket.create_connection((MAP_HOST, MAP_PORT), timeout=1.0):
                return True
        except OSError:
            return False

    def ensure_server(self) -> bool:
        """确保地图服务在线。未运行则自动拉起。返回是否就绪。"""
        if self.server_alive():
            return True
        dist = os.path.join(MAP_MODULE_DIR, "dist")
        if os.path.isdir(dist):
            cmd = ["npm", "run", "preview", "--", "--port", str(MAP_PORT), "--strictPort"]
        else:
            cmd = ["npm", "run", "dev", "--", "--port", str(MAP_PORT), "--strictPort"]
        if not os.path.isdir(MAP_MODULE_DIR):
            logger.warning("[Map] 地图模块目录不存在: %s", MAP_MODULE_DIR)
            return False
        try:
            logf = open(_SERVER_LOG, "ab")
            proc = subprocess.Popen(
                cmd,
                cwd=MAP_MODULE_DIR,
                stdout=logf,
                stderr=logf,
                start_new_session=True,
            )
            with self._lock:
                self._server_proc = proc
            print(f"[Map] 地图服务拉起中: {' '.join(cmd)}")
        except Exception as e:
            logger.warning("[Map] 地图服务启动失败: %s", e)
            return False
        for _ in range(40):  # 最多等 20 秒
            if self.server_alive():
                print("[Map] 地图服务已就绪")
                return True
            time.sleep(0.5)
        logger.warning("[Map] 地图服务等待超时，overlay 卡片将显示 OFFLINE")
        return False

    def stop_server(self):
        with self._lock:
            proc = self._server_proc
            self._server_proc = None
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass


# ── 单例 ──────────────────────────────────────────────────
_controller = None
_controller_lock = threading.Lock()


def get_map_dashboard_controller() -> MapDashboardController:
    global _controller
    with _controller_lock:
        if _controller is None:
            _controller = MapDashboardController()
        return _controller


# ── 激活联动钩子 ──────────────────────────────────────────
class MapDashboardHook(LifecycleHook):
    """唤醒时确保地图服务在线（overlay 卡片显示由 overlay 端负责）。"""

    def on_wake(self):
        get_map_dashboard_controller().ensure_server()
