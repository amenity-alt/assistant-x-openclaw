#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""成品导出：从 OpenCut jobs 目录下载 MP4 到用户视频目录，带时间戳命名。"""

import os
import time

from .opencut_client import OpenCutClient

_DEFAULT_EXPORT_DIR = os.path.expanduser("~/Movies/JarvisVideos")


def export_video(client: OpenCutClient, job_id: str,
                 name: str = "jarvis-video",
                 export_dir: str = _DEFAULT_EXPORT_DIR) -> str:
    """下载 job 成品到 export_dir/<name>-<ts>.mp4，返回绝对路径。"""
    os.makedirs(export_dir, exist_ok=True)
    safe = "".join(c if (c.isalnum() or c in "-_") else "-" for c in name).strip("-")
    safe = safe[:40] or "jarvis-video"
    ts = time.strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(export_dir, f"{safe}-{ts}.mp4")
    return client.download(job_id, dest)
