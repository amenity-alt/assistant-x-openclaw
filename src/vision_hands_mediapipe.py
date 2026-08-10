#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MediaPipe Hands 手部跟踪 — VisionHandTracker 接口的 Phase 2 实现

输入：JPEG 帧 → 输出 hand payload（与 Flutter vision_overlay.dart 解析一致）：
    {"hands": [{"label": "Left", "score": 0.9,
                "landmarks": [[x, y, z], ... 21 点]}]}
坐标归一化 0~1（相对画面宽高）。

依赖：mediapipe（pip 安装，含 opencv-contrib-python），模型 hand_landmarker.task
（官方 Tasks API，约 7.6MB）。模型优先读项目 models/ 目录，缺失时自动从
Google 官方地址限时下载（软失败：不可用/下载失败 → 手部跟踪关闭，不影响视觉 HUD）。

设计原则（与 camera.py 一致）：软失败，任何异常都不崩、不挂住帧流。
"""

import os
import socket
import threading
import urllib.request

import numpy as np

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL_PATH = os.path.join(_PROJECT_DIR, "models", "hand_landmarker.task")
_MODEL_URL = "https://storage.googleapis.com/mediapipe-assets/hand_landmarker.task"
_DOWNLOAD_TIMEOUT = 30  # 秒


class _quiet_fd2:
    """临时把 stderr(fd 2) 指向 /dev/null：吞掉 MediaPipe C++ 框架的一次性
    INFO/WARN 日志（直接写 fd，Python redirect_stderr 拦不住）。
    仅包裹模型创建/首次 detect 的毫秒级窗口，随后立即恢复。"""

    def __enter__(self):
        self._saved = os.dup(2)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        os.close(devnull)
        return self

    def __exit__(self, *exc):
        os.dup2(self._saved, 2)
        os.close(self._saved)
        return False


class MediaPipeHandTracker:
    """MediaPipe HandLandmarker（Tasks API）手部跟踪。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._landmarker = None
        self._fail = False
        self._warned = False

    # ── 模型准备 ─────────────────────────────────────────
    def _ensure_model(self) -> str | None:
        if os.path.exists(_MODEL_PATH) and os.path.getsize(_MODEL_PATH) > 0:
            return _MODEL_PATH
        try:
            print(f"[Vision] 下载手部模型: {_MODEL_URL}")
            os.makedirs(os.path.dirname(_MODEL_PATH), exist_ok=True)
            with socket.create_connection(("storage.googleapis.com", 443), timeout=15) as _sock:
                pass
            tmp = _MODEL_PATH + ".download"
            socket.setdefaulttimeout(_DOWNLOAD_TIMEOUT)
            try:
                urllib.request.urlretrieve(_MODEL_URL, tmp)
            finally:
                socket.setdefaulttimeout(None)
            if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                os.replace(tmp, _MODEL_PATH)
                print(f"[Vision] 手部模型已下载: {_MODEL_PATH}")
                return _MODEL_PATH
        except Exception as e:
            print(f"[Vision] 手部模型下载失败（手部跟踪关闭）: {e}")
        return None

    # ── 生命周期 ─────────────────────────────────────────
    def start(self, width: int, height: int):
        if self._landmarker is not None or self._fail:
            return
        try:
            model = self._ensure_model()
            if not model:
                self._fail = True
                return
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision as mp_vision

            base = mp_python.BaseOptions(model_asset_path=model)
            options = mp_vision.HandLandmarkerOptions(
                base_options=base,
                num_hands=2,
                min_hand_detection_confidence=0.5,
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            with _quiet_fd2():
                self._landmarker = mp_vision.HandLandmarker.create_from_options(options)
            print("[Vision] MediaPipe HandLandmarker 就绪")
        except Exception as e:
            self._fail = True
            print(f"[Vision] MediaPipe 加载失败（手部跟踪关闭）: {e}")

    def process(self, jpeg_bytes: bytes):
        if self._landmarker is None:
            if not self._fail:
                self.start(640, 360)
            if self._landmarker is None:
                return None
        try:
            rgb = self._decode_rgb(jpeg_bytes)
            if rgb is None:
                return None
            import mediapipe as mp
            img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            with self._lock:
                if not self._warned:
                    # 首次 detect 会打一条一次性 NORM_RECT 警告，一并静默
                    with _quiet_fd2():
                        res = self._landmarker.detect(img)
                    self._warned = True
                else:
                    res = self._landmarker.detect(img)
            hands = []
            n = len(res.hand_landmarks)
            for i in range(n):
                pts = [[lm.x, lm.y, lm.z] for lm in res.hand_landmarks[i]]
                label = "Hand"
                score = 1.0
                if i < len(res.handedness) and res.handedness[i]:
                    cat = res.handedness[i][0]
                    label = cat.category_name or "Hand"
                    score = float(cat.score or 1.0)
                hands.append({"label": label, "score": score, "landmarks": pts})
            if not hands:
                return None
            return {"hands": hands}
        except Exception:
            return None

    def _decode_rgb(self, jpeg: bytes):
        """JPEG → RGB ndarray（优先 mediapipe 自带的 opencv，兜底 Pillow）。"""
        try:
            import cv2
            arr = np.frombuffer(jpeg, dtype=np.uint8)
            bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if bgr is not None:
                return np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        except Exception:
            pass
        try:
            from PIL import Image
            import io
            im = Image.open(io.BytesIO(jpeg)).convert("RGB")
            return np.ascontiguousarray(np.asarray(im))
        except Exception:
            return None

    def stop(self):
        lm = self._landmarker
        self._landmarker = None
        if lm is not None:
            try:
                lm.close()
            except Exception:
                pass
