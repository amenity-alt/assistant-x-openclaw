#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Short Drama Mode — 数据模型（dataclass + to_dict/from_dict，风格与 mission.py 一致）。"""

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum


class DramaStatus(str, Enum):
    IDLE = "idle"                    # 未开启短剧模式
    COLLECTING = "collecting"        # 收集需求
    PLANNING = "planning"            # 剧情规划
    AWAITING_CONFIRM = "awaiting_confirm"
    EPISODE_DESIGN = "episode_design"
    PROMPTS = "prompts"
    COMPLETED = "completed"
    PAUSED = "paused"
    FAILED = "failed"


class DramaPhase(str, Enum):
    COLLECT_REQ = "collect_req"
    PLAN = "plan"
    EPISODE_SCRIPT = "episode_script"
    EPISODE_PROMPTS = "episode_prompts"
    REVIEW = "review"
    DONE = "done"


PHASE_LABEL_ZH = {
    DramaPhase.COLLECT_REQ: "需求收集",
    DramaPhase.PLAN: "剧情规划",
    DramaPhase.EPISODE_SCRIPT: "单集剧本",
    DramaPhase.EPISODE_PROMPTS: "镜头提示词",
    DramaPhase.REVIEW: "审核确认",
    DramaPhase.DONE: "完成",
}


@dataclass
class Character:
    id: str = ""
    name: str = ""
    age: str = ""
    gender: str = ""
    hairstyle: str = ""
    outfit: str = ""
    personality: str = ""
    voice: str = ""
    background: str = ""
    appearance_prompt: str = ""
    consistency_prompt: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Character":
        return cls(**{k: d.get(k, "") for k in cls.__dataclass_fields__})


@dataclass
class StoryboardShot:
    shot_id: str = ""
    scene: str = ""
    character: str = ""
    appearance: str = ""
    action: str = ""
    camera: str = ""
    lighting: str = ""
    environment: str = ""
    style: str = ""
    mood: str = ""
    dialogue: str = ""
    voice: str = ""
    sfx: str = ""
    bgm: str = ""
    duration: int = 5
    video_prompt: str = ""
    negative_prompt: str = ""
    consistency_prompt: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "StoryboardShot":
        return cls(**{k: d.get(k, "") for k in cls.__dataclass_fields__})


@dataclass
class Episode:
    number: int = 1
    title: str = ""
    goal: str = ""
    synopsis: str = ""
    script: str = ""
    shots: list = field(default_factory=list)   # List[StoryboardShot]
    status: str = "planned"                     # planned/script_ready/prompts_ready
    files: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "title": self.title,
            "goal": self.goal,
            "synopsis": self.synopsis,
            "script": self.script,
            "shots": [s.to_dict() for s in self.shots],
            "status": self.status,
            "files": self.files,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Episode":
        ep = cls(
            number=int(d.get("number", 1)),
            title=d.get("title", ""),
            goal=d.get("goal", ""),
            synopsis=d.get("synopsis", ""),
            script=d.get("script", ""),
            status=d.get("status", "planned"),
            files=d.get("files", {}),
        )
        ep.shots = [StoryboardShot.from_dict(s) for s in d.get("shots", [])]
        return ep


@dataclass
class DramaProject:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    genre: str = ""
    total_episodes: int = 10
    duration_per_episode: int = 60
    visual_style: str = ""
    status: DramaStatus = DramaStatus.COLLECTING
    phase: DramaPhase = DramaPhase.COLLECT_REQ
    current_episode: int = 1
    logline: str = ""
    worldview: str = ""
    main_plot: str = ""
    relationship_map: list = field(default_factory=list)
    episode_goals: list = field(default_factory=list)   # ["第1集 觉醒", ...]
    characters: list = field(default_factory=list)      # List[Character]
    episodes: list = field(default_factory=list)        # List[Episode]
    pending_confirm: dict = field(default_factory=dict) # {phase, summary}
    history: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["phase"] = self.phase.value
        d["characters"] = [c.to_dict() for c in self.characters]
        d["episodes"] = [e.to_dict() for e in self.episodes]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "DramaProject":
        p = cls(
            id=d.get("id", ""),
            title=d.get("title", ""),
            genre=d.get("genre", ""),
            total_episodes=int(d.get("total_episodes", 10)),
            duration_per_episode=int(d.get("duration_per_episode", 60)),
            visual_style=d.get("visual_style", ""),
            current_episode=int(d.get("current_episode", 1)),
            logline=d.get("logline", ""),
            worldview=d.get("worldview", ""),
            main_plot=d.get("main_plot", ""),
            relationship_map=d.get("relationship_map", []),
            episode_goals=d.get("episode_goals", []),
            pending_confirm=d.get("pending_confirm", {}),
            history=d.get("history", []),
            created_at=float(d.get("created_at", 0.0)),
            updated_at=float(d.get("updated_at", 0.0)),
        )
        try:
            p.status = DramaStatus(d.get("status", "collecting"))
        except ValueError:
            p.status = DramaStatus.COLLECTING
        try:
            p.phase = DramaPhase(d.get("phase", "collect_req"))
        except ValueError:
            p.phase = DramaPhase.COLLECT_REQ
        p.characters = [Character.from_dict(c) for c in d.get("characters", [])]
        p.episodes = [Episode.from_dict(e) for e in d.get("episodes", [])]
        return p

    def episode(self, number: int):
        for e in self.episodes:
            if e.number == number:
                return e
        return None

    def character(self, name: str):
        for c in self.characters:
            if c.name == name:
                return c
        return None
