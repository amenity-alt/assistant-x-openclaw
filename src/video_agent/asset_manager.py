#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""素材管理：校验本地视频素材、按任务隔离拷贝到 OpenCut public/。"""

import os
import shutil
import uuid

from .opencut_client import OPENCUT_DIR

_VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm")


def validate_video(path: str) -> str:
    """校验并返回规范化路径；非法返回空字符串。"""
    if not path:
        return ""
    p = os.path.abspath(os.path.expanduser(path.strip()))
    if not os.path.isfile(p):
        return ""
    if os.path.splitext(p)[1].lower() not in _VIDEO_EXTS:
        return ""
    return p


def stage_for_render(src_video: str) -> tuple:
    """把素材拷贝到 opencut/public/jobs/<job_id>/，返回 (job_id, videoSrc)。

    videoSrc 用于 Remotion staticFile 相对路径（如 "jobs/xx/input.mp4"）。
    """
    src = validate_video(src_video)
    if not src:
        raise ValueError(f"非法素材路径: {src_video}")
    job_id = uuid.uuid4().hex[:12]
    public_jobs = os.path.join(OPENCUT_DIR, "public", "jobs", job_id)
    os.makedirs(public_jobs, exist_ok=True)
    ext = os.path.splitext(src)[1].lower() or ".mp4"
    dst = os.path.join(public_jobs, f"input{ext}")
    shutil.copy2(src, dst)
    return job_id, f"jobs/{job_id}/input{ext}"


def cleanup_job_assets(job_id: str):
    """清理 opencut/public/jobs/<id>（渲染后双份拷贝之一）。"""
    if not job_id:
        return
    public_jobs = os.path.join(OPENCUT_DIR, "public", "jobs", job_id)
    try:
        if os.path.isdir(public_jobs):
            shutil.rmtree(public_jobs, ignore_errors=True)
    except Exception as e:
        print(f"[Video] 清理素材失败: {e}")
