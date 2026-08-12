#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Short Drama — 项目持久化（projects/short_drama/ JSON，原子写）。"""

import json
import os
import threading

from .models import DramaProject

_PROJECTS_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "projects", "short_drama",
)
_INDEX_FILE = os.path.join(_PROJECTS_ROOT, "index.json")


class DramaProjectStore:
    def __init__(self, root: str = _PROJECTS_ROOT):
        self.root = root
        self._lock = threading.Lock()

    def project_dir(self, project_id: str) -> str:
        return os.path.join(self.root, project_id)

    def _atomic_write(self, path: str, data: dict):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    # ── 项目 ─────────────────────────────────────────────
    def save(self, project: DramaProject):
        with self._lock:
            d = project.to_dict()
            d.pop("history", None)  # history 只保留在内存，避免无限膨胀
            self._atomic_write(
                os.path.join(self.project_dir(project.id), "drama.json"), d
            )
            self._touch_index(project)

    def load(self, project_id: str) -> DramaProject | None:
        path = os.path.join(self.project_dir(project_id), "drama.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return DramaProject.from_dict(json.load(f))
        except Exception as e:
            print(f"[Drama] 加载项目失败 {project_id}: {e}")
            return None

    def list_projects(self) -> list:
        idx = {}
        try:
            with open(_INDEX_FILE, "r", encoding="utf-8") as f:
                idx = json.load(f)
        except Exception:
            pass
        return sorted(
            idx.values(), key=lambda x: x.get("updated_at", 0), reverse=True
        )

    def _touch_index(self, project: DramaProject):
        idx = {}
        try:
            with open(_INDEX_FILE, "r", encoding="utf-8") as f:
                idx = json.load(f)
        except Exception:
            pass
        idx[project.id] = {
            "id": project.id,
            "title": project.title or "未命名短剧",
            "status": project.status.value,
            "phase": project.phase.value,
            "current_episode": project.current_episode,
            "total_episodes": project.total_episodes,
            "updated_at": project.updated_at,
        }
        os.makedirs(os.path.dirname(_INDEX_FILE), exist_ok=True)
        tmp = _INDEX_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _INDEX_FILE)

    # ── 集文件 ───────────────────────────────────────────
    def episode_dir(self, project_id: str, number: int) -> str:
        return os.path.join(
            self.project_dir(project_id), "episodes", f"episode_{number:02d}"
        )

    def save_script(self, project_id: str, number: int, text: str) -> str:
        d = self.episode_dir(project_id, number)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "script.md")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
        return path

    def save_storyboard(self, project_id: str, number: int, shots: list) -> str:
        d = self.episode_dir(project_id, number)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "storyboard.json")
        self._atomic_write(path, {"episode": number, "shots": shots})
        return path

    def save_shot_prompt(self, project_id: str, number: int,
                         shot_id: str, data: dict) -> str:
        d = os.path.join(self.episode_dir(project_id, number), "prompts")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{shot_id}.json")
        self._atomic_write(path, data)
        return path
