#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Short Drama — 剧情规划（主题→标题/世界观/人物/关系/主线/分集目标）。

主路径：HermesBridge（DeepSeek）→ 结构化 JSON；
失败：本地模板兜底（保证断网也能给出可确认的骨架）。
"""

import json

from ._llm import llm_json

_PLAN_PROMPT = (
    "你是 Jarvis 的短剧编剧。请根据用户创意规划一部短剧，输出严格 JSON（不要 markdown）：\n"
    '{\n'
    '  "title": "剧名（2-8字，吸睛）",\n'
    '  "logline": "核心冲突一句话（30字内）",\n'
    '  "worldview": "世界观设定（80字内）",\n'
    '  "main_plot": "全剧主线（120字内）",\n'
    '  "characters": [\n'
    '    {"name": "姓名", "gender": "男/女", "age": "28", "role": "主角/反派/配角",\n'
    '     "hairstyle": "发型", "outfit": "服装", "personality": "性格",\n'
    '     "voice": "声线特点", "background": "背景（40字内）",\n'
    '     "appearance_prompt": "给视频模型的角色外观一致描述（英文，40词内，含发型/服装/年龄感）",\n'
    '     "consistency_prompt": "全剧一致性约束（英文或中文，强调发型服装不得改变）"}\n'
    '  ],\n'
    '  "relationship_map": ["林晓-林峰: 兄妹", "林晓-苏晴: 闺蜜"],\n'
    '  "episode_goals": ["第1集 觉醒", "第2集 第一次使用能力"]\n'
    '}\n'
    "要求：characters 3-5 人；episode_goals 数量必须等于总集数；"
    "episode_goals 每条 10 字内；人物名贴近题材；中文为主，外观 prompt 用英文。"
)


def _normalize(data: dict, theme: str, total: int) -> dict:
    """清洗/兜底 LLM 输出，保证字段完整。"""
    title = (data.get("title") or "").strip()
    if not title:
        title = theme[:6] or "无名短剧"
    chars = data.get("characters") or []
    clean_chars = []
    for i, c in enumerate(chars[:6]):
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or f"角色{i + 1}").strip()[:12]
        clean_chars.append({
            "name": name,
            "gender": (c.get("gender") or "女").strip()[:2],
            "age": str(c.get("age") or "25")[:6],
            "role": (c.get("role") or "主角").strip()[:4],
            "hairstyle": (c.get("hairstyle") or "").strip(),
            "outfit": (c.get("outfit") or "").strip(),
            "personality": (c.get("personality") or "").strip(),
            "voice": (c.get("voice") or "").strip(),
            "background": (c.get("background") or "").strip(),
            "appearance_prompt": (c.get("appearance_prompt")
                                  or f"{name}, {c.get('hairstyle', '')} {c.get('outfit', '')}"
                                  ).strip(),
            "consistency_prompt": (c.get("consistency_prompt")
                                   or f"角色 {name} 全剧保持 {c.get('hairstyle', '')} {c.get('outfit', '')} 一致，不得改变。"
                                   ).strip(),
        })
    goals = [str(g).strip()[:14] for g in (data.get("episode_goals") or []) if str(g).strip()]
    while len(goals) < total:
        goals.append(f"第{len(goals) + 1}集 推进主线")
    goals = goals[:total]
    return {
        "title": title,
        "logline": (data.get("logline") or f"{theme}题材的核心冲突").strip()[:60],
        "worldview": (data.get("worldview") or "").strip()[:200] or "都市现实世界观",
        "main_plot": (data.get("main_plot") or "").strip()[:300] or "主角在冲突中成长",
        "characters": clean_chars or [
            {
                "name": "主角", "gender": "女", "age": "25", "role": "主角",
                "hairstyle": "黑色长发", "outfit": "简洁职业装",
                "personality": "坚韧聪明", "voice": "清亮",
                "background": "普通都市青年",
                "appearance_prompt": "female lead, long black hair, neat business casual, 25",
                "consistency_prompt": "主角全剧保持黑色长发与职业装一致，不得改变。",
            },
            {
                "name": "对手", "gender": "男", "age": "30", "role": "反派",
                "hairstyle": "短寸", "outfit": "深色西装",
                "personality": "冷静多谋", "voice": "低沉",
                "background": "商业对手",
                "appearance_prompt": "male antagonist, short hair, dark suit, 30",
                "consistency_prompt": "反派全剧保持短寸与深色西装一致，不得改变。",
            },
        ],
        "relationship_map": [
            str(r).strip()[:40] for r in (data.get("relationship_map") or []) if str(r).strip()
        ] or ([f"{clean_chars[0]['name']}-{clean_chars[1]['name']}: 宿敌"]
              if len(clean_chars) > 1 else ["主角-对手: 宿敌"]),
        "episode_goals": goals,
    }


class DramaPlanner:
    """故事规划器。plan_story() 返回归一化后的规划 dict。"""

    def plan_story(self, theme: str, genre: str = "", style: str = "",
                   total_episodes: int = 10, role: str = "jarvis") -> dict:
        theme = (theme or "").strip()[:40] or "都市逆袭"
        prompt = (
            f"{_PLAN_PROMPT}\n"
            f"用户创意：主题={theme}；类型={genre or '都市'}；视觉风格={style or '电影感'}；"
            f"总集数={total_episodes} 集（episode_goals 必须恰好 {total_episodes} 条）。"
        )
        data = llm_json(prompt, role=role)
        if not isinstance(data, dict):
            data = self._template(theme, genre, style, total_episodes)
        return _normalize(data, theme, total_episodes)

    @staticmethod
    def _template(theme: str, genre: str, style: str, total: int) -> dict:
        """本地模板兜底：结构完整但文案朴素。"""
        goals = [f"第{i + 1}集 冲突升级" for i in range(total)]
        return {
            "title": theme[:6],
            "logline": f"{theme}为核心冲突的{genre or '都市'}短剧",
            "worldview": f"{genre or '都市'}现实世界观，{style or '电影感'}视觉风格",
            "main_plot": f"围绕{theme}展开的主线冲突，主角逐步成长，最终达成目标",
            "characters": [],
            "relationship_map": [],
            "episode_goals": goals,
        }
