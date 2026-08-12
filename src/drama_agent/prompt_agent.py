#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Short Drama — 镜头 Prompt 包（每镜头完整 VIDEO_PROMPT / NEGATIVE_PROMPT / 一致性）。

对 storyboard 的每个镜头生成 16 字段 Prompt 包，输出到 prompts/shot_XX.json。
LLM 主路径（批量），失败本地模板兜底。
"""

from ._llm import llm_json

_SHOT_PROMPT = (
    "你是 Jarvis 的 AI 视频提示词工程师。为短剧镜头生成文生视频提示词，输出严格 JSON：\n"
    '{"prompts": [{"shot_id": "shot_01",\n'
    '  "video_prompt": "完整英文视频生成提示词（60-90词：场景/人物外观/动作/运镜/灯光/风格/画质）",\n'
    '  "negative_prompt": "负面提示词（英文，如 distorted hands, low quality）",\n'
    '  "consistency_prompt": "人物一致性约束（引用外观）"}]}\n'
    "人物外观与一致性约束必须保留：\n"
)


class PromptAgent:
    """每个镜头 → 完整 Prompt 包。generate() 返回 List[dict]。"""

    def generate(self, project, number: int, shots: list, role: str = "jarvis") -> list:
        char_lines = "\n".join(
            f"- {c.name}: {c.appearance_prompt} | {c.consistency_prompt}"
            for c in project.characters
        )
        shot_lines = "\n".join(
            f"- {s['shot_id']} {s.get('scene', '')} 人物={s.get('character', '')} "
            f"动作={s.get('action', '')} 运镜={s.get('camera', '')} "
            f"灯光={s.get('lighting', '')} 环境={s.get('environment', '')} "
            f"风格={s.get('style', '')} 情绪={s.get('mood', '')} 时长={s.get('duration', 5)}s"
            for s in shots
        )
        prompt = (
            f"{_SHOT_PROMPT}\n"
            f"剧名《{project.title}》第{number}集 风格={project.visual_style}\n"
            f"人物：\n{char_lines}\n"
            f"镜头：\n{shot_lines}\n"
            f"为每个镜头生成提示词包。"
        )
        data = llm_json(prompt, role=role)
        if isinstance(data, dict) and isinstance(data.get("prompts"), list):
            by_id = {str(p.get("shot_id", "")).strip(): p for p in data["prompts"]
                     if isinstance(p, dict)}
            out = []
            for s in shots:
                p = by_id.get(s.get("shot_id", ""))
                out.append({
                    "shot_id": s.get("shot_id", ""),
                    "scene": s.get("scene", ""),
                    "character": s.get("character", ""),
                    "appearance": s.get("appearance", ""),
                    "action": s.get("action", ""),
                    "camera": s.get("camera", ""),
                    "lighting": s.get("lighting", ""),
                    "environment": s.get("environment", ""),
                    "style": s.get("style", ""),
                    "mood": s.get("mood", ""),
                    "dialogue": s.get("dialogue", ""),
                    "voice": s.get("voice", ""),
                    "sfx": s.get("sfx", ""),
                    "bgm": s.get("bgm", ""),
                    "duration": int(s.get("duration") or 5),
                    "video_prompt": (p.get("video_prompt") if p else "") or self._video_prompt(s),
                    "negative_prompt": (p.get("negative_prompt") if p else "")
                    or "distorted hands, extra fingers, low quality, blurry, watermark, text artifacts",
                    "consistency_prompt": (p.get("consistency_prompt") if p else "")
                    or s.get("consistency_prompt", ""),
                })
            return out
        return [self._local_pack(s) for s in shots]

    @staticmethod
    def _video_prompt(s: dict) -> str:
        return (
            f"{s.get('style', 'cinematic realistic')}, {s.get('scene', '')}, "
            f"{s.get('character', '')}, {s.get('appearance', '')}, {s.get('action', '')}, "
            f"{s.get('camera', 'cinematic medium shot')}, {s.get('lighting', '')}, "
            f"{s.get('environment', '')}, {s.get('mood', '')}, 4k, high detail"
        )

    @staticmethod
    def _local_pack(s: dict) -> dict:
        return {
            "shot_id": s.get("shot_id", ""),
            "scene": s.get("scene", ""),
            "character": s.get("character", ""),
            "appearance": s.get("appearance", ""),
            "action": s.get("action", ""),
            "camera": s.get("camera", ""),
            "lighting": s.get("lighting", ""),
            "environment": s.get("environment", ""),
            "style": s.get("style", ""),
            "mood": s.get("mood", ""),
            "dialogue": s.get("dialogue", ""),
            "voice": s.get("voice", ""),
            "sfx": s.get("sfx", ""),
            "bgm": s.get("bgm", ""),
            "duration": int(s.get("duration") or 5),
            "video_prompt": PromptAgent._video_prompt(s),
            "negative_prompt": "distorted hands, extra fingers, low quality, blurry, watermark, text artifacts",
            "consistency_prompt": s.get("consistency_prompt", ""),
        }
