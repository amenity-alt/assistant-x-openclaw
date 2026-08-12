#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Short Drama — 单集剧本（剧情/对白/镜头列表/运镜/音效/BGM/旁白）。

输出 script.md（人类可读完整剧本）+ storyboard.json（镜头结构化数据）。
LLM 主路径，失败本地模板兜底。
"""

import json

from ._llm import llm_json
from .models import StoryboardShot

_SCRIPT_PROMPT = (
    "你是 Jarvis 的短剧导演兼编剧。根据剧情规划写第 {ep} 集的完整剧本，输出严格 JSON：\n"
    '{\n'
    '  "title": "本集标题（8字内）",\n'
    '  "goal": "本集目标（20字内）",\n'
    '  "synopsis": "本集剧情梗概（100字内）",\n'
    '  "prose": "完整剧本正文，含场景描写与对白（300字内，分场）",\n'
    '  "shots": [\n'
    '    {"scene": "场景", "character": "出场人物", "action": "动作",\n'
    '     "camera": "运镜（cinematic medium shot 等）", "lighting": "灯光",\n'
    '     "environment": "环境", "style": "风格", "mood": "情绪",\n'
    '     "dialogue": "对白（可空）", "voice": "配音人声/语速",\n'
    '     "sfx": "音效", "bgm": "BGM", "duration": 5}\n'
    '  ]\n'
    '}\n'
    "要求：5-9 个镜头；duration 4-8 秒；对白口语化；运镜多样；人物名必须用规划中的人物名。"
)


class EpisodeWriter:
    """单集剧本生成。write() 返回 (script_md, shots[dict])。"""

    def write(self, project, number: int, role: str = "jarvis") -> tuple:
        episode = project.episode(number)
        goal = episode.goal if episode else ""
        goal_text = (
            goal
            or (project.episode_goals[number - 1]
                if project.episode_goals and number - 1 < len(project.episode_goals)
                else "")
        )
        chars = "、".join(c.name for c in project.characters) or "主角"
        prompt = (
            f"{_SCRIPT_PROMPT.replace('{ep}', str(number))}\n"
            f"剧名：《{project.title}》 类型={project.genre} 风格={project.visual_style}。\n"
            f"世界观：{project.worldview}\n"
            f"主线：{project.main_plot}\n"
            f"本集目标：{goal_text}\n"
            f"人物：{chars}\n"
            f"人物外观与一致性：\n"
            + "\n".join(
                f"- {c.name}: {c.appearance_prompt} | 一致性: {c.consistency_prompt}"
                for c in project.characters
            )
            + "\n请输出 JSON。"
        )
        data = llm_json(prompt, role=role)
        if not isinstance(data, dict):
            data = self._template(project, number, goal)
        title = (data.get("title") or f"第{number}集").strip()[:16]
        synopsis = (data.get("synopsis") or "").strip()
        prose = (data.get("prose") or "").strip()
        raw_shots = data.get("shots") or []
        shots = []
        for i, s in enumerate(raw_shots[:12], start=1):
            if not isinstance(s, dict):
                continue
            shot = StoryboardShot(
                shot_id=f"shot_{i:02d}",
                scene=str(s.get("scene") or "").strip(),
                character=str(s.get("character") or "").strip(),
                action=str(s.get("action") or "").strip(),
                camera=str(s.get("camera") or "cinematic medium shot").strip(),
                lighting=str(s.get("lighting") or "").strip(),
                environment=str(s.get("environment") or "").strip(),
                style=str(s.get("style") or project.visual_style or "cinematic realistic").strip(),
                mood=str(s.get("mood") or "").strip(),
                dialogue=str(s.get("dialogue") or "").strip(),
                voice=str(s.get("voice") or "").strip(),
                sfx=str(s.get("sfx") or "").strip(),
                bgm=str(s.get("bgm") or "").strip(),
                duration=max(3, min(int(s.get("duration") or 5), 10)),
            )
            char = project.character(shot.character)
            if char:
                shot.appearance = char.appearance_prompt
                shot.consistency_prompt = char.consistency_prompt
            shots.append(shot)
        if not shots:
            shots = self._template_shots(project, number)
        script_md = self._render_md(project, number, title, goal, synopsis, prose, shots)
        return script_md, [s.to_dict() for s in shots]

    # ── Markdown 渲染 ─────────────────────────────────────
    @staticmethod
    def _render_md(project, number, title, goal, synopsis, prose, shots) -> str:
        lines = [
            f"# 第{number}集 《{title}》",
            "",
            f"- 剧名：{project.title}",
            f"- 类型：{project.genre} ｜ 风格：{project.visual_style}",
            f"- 本集目标：{goal}",
            "",
            "## 剧情梗概",
            "",
            synopsis,
            "",
            "## 完整剧本",
            "",
            prose,
            "",
            "## 镜头列表",
            "",
        ]
        for s in shots:
            lines.append(f"### {s.shot_id}｜{s.scene}")
            lines.append(f"- 人物：{s.character} ｜ 动作：{s.action}")
            lines.append(f"- 运镜：{s.camera} ｜ 灯光：{s.lighting} ｜ 情绪：{s.mood}")
            lines.append(f"- 环境：{s.environment} ｜ 风格：{s.style}")
            if s.dialogue:
                lines.append(f"- 对白：{s.dialogue}")
            lines.append(f"- 配音：{s.voice} ｜ 音效：{s.sfx} ｜ BGM：{s.bgm} ｜ 时长：{s.duration}s")
            lines.append("")
        return "\n".join(lines)

    # ── 模板兜底 ──────────────────────────────────────────
    @staticmethod
    def _template(project, number, goal) -> dict:
        return {
            "title": f"第{number}集 推进",
            "goal": goal or "",
            "synopsis": f"{project.title}第{number}集：主线冲突继续推进。",
            "prose": f"第{number}集。{project.worldview}\n{project.main_plot}",
            "shots": [],
        }

    @staticmethod
    def _template_shots(project, number) -> list:
        char = project.characters[0] if project.characters else None
        name = char.name if char else "主角"
        return [
            StoryboardShot(
                shot_id="shot_01", scene="开场城市街道", character=name,
                action=f"{name}出场，环境交代", camera="cinematic establishing shot",
                lighting="自然光", environment="城市街道", style="cinematic realistic",
                mood="紧张", dialogue="", voice="女声，清晰", sfx="环境音",
                bgm="悬疑铺垫", duration=5,
            ),
            StoryboardShot(
                shot_id="shot_02", scene="核心冲突场景", character=name,
                action=f"{name}面对关键冲突", camera="cinematic medium shot",
                lighting="对比光", environment="室内", style="cinematic realistic",
                mood="冲突", dialogue="这是命运的转折。", voice="女声，坚定", sfx="心跳声",
                bgm="高潮推进", duration=6,
            ),
            StoryboardShot(
                shot_id="shot_03", scene="结局定格", character=name,
                action=f"{name}做出决定", camera="close-up",
                lighting="暖光", environment="同上", style="cinematic realistic",
                mood="希望", dialogue="", voice="女声，温柔", sfx="渐弱",
                bgm="主题收束", duration=5,
            ),
        ]
