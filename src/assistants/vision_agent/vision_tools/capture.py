#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""帧获取：优先 VisionManager 当前帧（不重开摄像头）；兜底 camera.py 抓帧。"""


def grab_frame() -> bytes | None:
    """VisionManager 最近一帧 JPEG（物体识别默认来源）。"""
    try:
        from vision import get_vision_manager

        return get_vision_manager().last_frame()
    except Exception as e:
        print(f"[VisionAgent] 取帧失败: {e}")
        return None


def snapshot() -> bytes | None:
    """备用：camera.py 按需抓一帧（软失败）。"""
    try:
        from camera import CameraController
        import os
        import tempfile

        cc = CameraController()
        fd, path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        try:
            if not cc.capture(path):
                return None
            with open(path, "rb") as f:
                return f.read()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    except Exception as e:
        print(f"[VisionAgent] snapshot 抓帧失败: {e}")
        return None
