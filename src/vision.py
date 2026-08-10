#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Vision Mode 能力模块（Jarvis 视觉扫描模式）

Capability 而非 Agent：任何角色（jarvis / lin-meimei）都可通过语音进入/退出。

  - 摄像头：复用 camera.py 的 ffmpeg avfoundation 授权路径，长驻 MJPEG 管线抓帧
  - 通信：经当前角色 visual 的 TCP(17889) 推送 vision:* 事件给 Flutter overlay
  - 手部跟踪：抽象接口 VisionHandTracker，Phase 1 为空实现（渲染层 + 预留接口，
    Phase 2 可接入 MediaPipe Hands，一行切换）

协议（与地图指令同级，文本行 \n 分隔）：
  vision:start                       进入视觉模式（全屏 HUD 展开）
  vision:stop                        退出视觉模式（HUD 收缩 + 释放摄像头）
  vision:status <STATE>              状态机同步（INITIALIZING/SCANNING/.../ERROR）
  vision:frame <base64-jpeg>         摄像头预览帧（默认 640x360@10fps，仅激活时推送）
  vision:hand <json>                 手部数据（21 关键点，Phase 1 预留）

设计原则（与 camera.py 一致）：软失败。摄像头不可用/未授权 → ERROR 状态并退出，
绝不崩、不挂住语音主流程。
"""

import base64
import json
import shutil
import subprocess
import threading
import time

# 状态（与 Flutter VisionMode 对齐）
STATE_INITIALIZING = "INITIALIZING"
STATE_SCANNING = "SCANNING"
STATE_HAND_DETECTED = "HAND_DETECTED"
STATE_ANALYZING = "ANALYZING"
STATE_COMPLETED = "COMPLETED"
STATE_ERROR = "ERROR"
STATE_OFF = "OFF"

_FRAME_FPS = 10
_FRAME_SIZE = "640x360"
_MJPEG_READ_CHUNK = 65536
_MAX_BUF = 4 * 1024 * 1024


class VisionHandTracker:
    """手部跟踪抽象接口（Phase 1 空实现，Phase 2 接入 MediaPipe）。"""

    def start(self, width: int, height: int):
        pass

    def process(self, jpeg_bytes: bytes):
        """输入一帧 JPEG，返回 hand payload dict 或 None。

        payload 结构（Flutter 侧按此解析）：
            {"hands": [{"label": "Left", "score": 0.9,
                        "landmarks": [[x, y, z], ... 21 点]}]}
        坐标为归一化 0~1（相对画面宽高）。
        """
        return None

    def stop(self):
        pass


class _NullVisionHandTracker(VisionHandTracker):
    pass


class VisionManager:
    """视觉模式生命周期 + 摄像头帧流管理（单例）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._active = False
        self._stop_event = threading.Event()
        self._thread = None
        self._proc = None
        self._visual = None
        self._tracker = _NullVisionHandTracker()
        self._fps_interval = 1.0 / _FRAME_FPS

    # ── 绑定当前角色 visual ──────────────────────────────
    def bind_visual(self, visual):
        """绑定当前角色 visual（角色切换时由 main.py 更新）。"""
        self._visual = visual

    def _send(self, command: str, quiet: bool = False):
        v = self._visual
        if v is None:
            return
        try:
            v.send(command, quiet=quiet)
        except Exception as e:
            print(f"[Vision] 发送失败: {e}")

    # ── 生命周期 ─────────────────────────────────────────
    def is_active(self) -> bool:
        with self._lock:
            return self._active

    def start(self):
        """开启视觉模式（幂等）。摄像头采集在后台线程进行，不阻塞语音主循环。"""
        with self._lock:
            if self._active:
                return
            self._active = True
            self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="vision-feed"
        )
        self._thread.start()

    def stop(self):
        """关闭视觉模式（幂等）：停帧线程 + 杀 ffmpeg + 通知 overlay 退出。"""
        with self._lock:
            was_active = self._active
            self._active = False
            self._stop_event.set()
        if not was_active:
            return
        # 直接杀掉 ffmpeg，让阻塞在 read 的帧线程立刻退出
        self._cleanup_proc()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=2.0)

    def stop_if_active(self):
        self.stop()

    # ── 帧采集 ───────────────────────────────────────────
    @staticmethod
    def _find_ffmpeg():
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return shutil.which("ffmpeg")

    def _open_ffmpeg(self):
        """长驻 MJPEG 管线：avfoundation → pipe:1 输出 JPEG 帧流。"""
        exe = self._find_ffmpeg()
        if not exe:
            return None
        cmd = [
            exe, "-hide_banner", "-loglevel", "error",
            "-f", "avfoundation",
            "-framerate", str(_FRAME_FPS),
            "-video_size", _FRAME_SIZE,
            "-i", "0",
            "-f", "mjpeg",
            "-q:v", "6",
            "-fflags", "nobuffer",
            "pipe:1",
        ]
        try:
            return subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
        except Exception as e:
            print(f"[Vision] ffmpeg 启动失败: {e}")
            return None

    def _cleanup_proc(self, proc=None):
        """终止 ffmpeg 进程。传入 proc 时只处理它；否则取当前 self._proc 并置空。"""
        if proc is None:
            with self._lock:
                proc = self._proc
                self._proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1.0)
        except Exception:
            pass

    def _run(self):
        """帧采集线程：起 ffmpeg MJPEG 流 → 切帧 → 推 vision:* 事件。"""
        proc = None
        try:
            self._send("vision:start")
            self._send(f"vision:status {STATE_INITIALIZING}")
            proc = self._open_ffmpeg()
            if proc is None or proc.stdout is None:
                print("[Vision] ffmpeg 不可用，视觉模式退出（软失败）")
                self._send(f"vision:status {STATE_ERROR}")
                return
            with self._lock:
                self._proc = proc
            self._send(f"vision:status {STATE_SCANNING}")
            print("[Vision] 视觉模式已激活（摄像头帧流在线）")
            tracker = self._tracker
            try:
                tracker.start(640, 360)
                self._pump_frames(proc)
            finally:
                tracker.stop()
        finally:
            self._cleanup_proc(proc)
            self._send("vision:stop")
            # ident 守卫：快速 start/stop/start 竞态下，旧线程收尾不覆盖新线程状态
            with self._lock:
                if self._thread is not None and self._thread.ident == threading.get_ident():
                    self._proc = None
                    self._active = False
            print("[Vision] 视觉模式已退出")

    def _pump_frames(self, proc):
        buf = b""
        last_send = 0.0
        first = True
        while not self._stop_event.is_set():
            try:
                chunk = proc.stdout.read(_MJPEG_READ_CHUNK)
            except Exception:
                break
            if not chunk:
                # ffmpeg 异常退出（摄像头不可用/未授权）→ ERROR；正常被 stop → 静默
                if (
                    first
                    and proc.poll() is not None
                    and not self._stop_event.is_set()
                ):
                    print("[Vision] 摄像头不可用/未授权，视觉模式退出（软失败）")
                    self._send(f"vision:status {STATE_ERROR}")
                break
            first = False
            buf += chunk
            if len(buf) > _MAX_BUF:
                buf = buf[-_MAX_BUF:]
            while True:
                start = buf.find(b"\xff\xd8")
                if start < 0:
                    if len(buf) > 1024:
                        buf = buf[-1024:]
                    break
                end = buf.find(b"\xff\xd9", start)
                if end < 0:
                    break
                jpeg = buf[start:end + 2]
                buf = buf[end + 2:]
                now = time.time()
                if now - last_send >= self._fps_interval:
                    last_send = now
                    self._send_frame(jpeg)
                hand = self._tracker.process(jpeg)
                if hand:
                    payload = json.dumps(hand, ensure_ascii=False)
                    self._send(f"vision:hand {payload}", quiet=True)

    def _send_frame(self, jpeg: bytes):
        b64 = base64.b64encode(jpeg).decode("ascii")
        self._send(f"vision:frame {b64}", quiet=True)


# ── 单例 ────────────────────────────────────────────────
_manager = None
_manager_lock = threading.Lock()


def get_vision_manager() -> VisionManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = VisionManager()
        return _manager
