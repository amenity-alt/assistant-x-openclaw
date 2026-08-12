#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""OpenCut 项目管理：解析渲染目标项目（白名单）+ 未来时间线生成的占位。

Phase 2 最小实现：render 模式只允许渲染 OpenCut 自带示例项目
（白名单见 task.ALLOWED_PROJECTS），不执行任意 entryPoint。
未来个性化剪辑：这里拼 VideoProjectConfig → OpenCut workflow/generator
生成 timeline.ts（留接口 build_project_config）。
"""

from .task import ALLOWED_PROJECTS


def resolve_render(project_name: str):
    """按名称解析 (composition_id, entry_point)。非法返回 None。"""
    name = (project_name or "").strip()
    if not name:
        return None
    # 支持 "quickstart" / "src/examples/quickstart" / 全路径 三种写法
    for key, val in ALLOWED_PROJECTS.items():
        if name == key or name.endswith(f"/{key}") or name.endswith(f"{key}/index.ts"):
            return val
    return None


def list_projects() -> list:
    """可渲染项目清单。"""
    return sorted(ALLOWED_PROJECTS.keys())


def build_project_config(prompt: str, video_format: str = "horizontal",
                         duration_sec: int = 60) -> dict:
    """未来扩展：把自然语言需求 → VideoProjectConfig（JSON/YAML）。

    当前返回一个基于 facecam 模板的最小配置，供 render 模式后续接入
    OpenCut workflow/generator 生成 timeline.ts 使用。
    """
    fmt_dims = {
        "horizontal": {"width": 1920, "height": 1080},
        "vertical": {"width": 1080, "height": 1920},
        "square": {"width": 1080, "height": 1080},
    }[video_format]
    return {
        "name": "jarvis-video",
        "format": video_format,
        "facecam": "facecam.mp4",
        "playbackRate": 1.0,
        "title": "Jarvis Video",
        "segments": [
            {"type": "facecam-full", "duration": max(duration_sec, 5)}
        ],
        "_fmt_dims": fmt_dims,
        "_prompt": prompt,
    }
