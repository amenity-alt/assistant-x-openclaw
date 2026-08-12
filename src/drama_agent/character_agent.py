#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Short Drama — 人物设定与修改（一致性约束 + 影响范围分析）。

- design()   ：为已有角色生成 appearance_prompt / consistency_prompt（LLM，失败本地兜底）
- modify()   ：按目标（女主角/男主角/姓名）+ 修改内容（发型/服装/性格/年龄/外貌）更新人物卡
- impact()   ：计算修改影响到的已生成集数（含该角色的剧集）
- sync_episodes()：确认后把新外观约束同步进已生成剧集的镜头
"""

import re

from ._llm import llm_json
from .models import Character

_CHAR_PROMPT = (
    "你是 Jarvis 的短剧人物设计师。为角色生成给视频模型的视觉一致性描述，输出严格 JSON：\n"
    '{"appearance_prompt": "英文，40词内，含发型/服装/年龄感/气质",\n'
    ' "consistency_prompt": "中文或英文，强调后续每一集不得改变发型服装"}'
)

_HAIR_RE = re.compile(r"(短发|长发|卷发|直发|马尾|丸子头|寸头|挑染|金发|黑长直|齐刘海|中分|背头|双马尾)")
_OUTFIT_RE = re.compile(r"(西装|职业装|旗袍|汉服|古装|裙子|红裙|白衬衫|T恤|卫衣|风衣|大衣|校服|工装|休闲装|运动装|礼服|夹克|外套|围巾)")
_PERSONALITY_RE = re.compile(r"(性格|脾气|高冷|温柔|冷酷|开朗|内向|外向|腹黑|善良|果断|犹豫|冷静|暴躁|毒舌)")
_AGE_RE = re.compile(r"(\d{1,2})\s*(?:岁|岁左右)")


class CharacterAgent:
    """人物卡操作。修改直接改内存中的 Character，由调用方 save。"""

    def design(self, character: Character, role: str = "jarvis") -> Character:
        """为角色补齐 appearance_prompt / consistency_prompt（缺失时）。"""
        if character.appearance_prompt and character.consistency_prompt:
            return character
        prompt = (
            f"{_CHAR_PROMPT}\n"
            f"角色：{character.name}，{character.gender}，{character.age}岁，"
            f"发型={character.hairstyle}，服装={character.outfit}，性格={character.personality}，"
            f"背景={character.background}。"
        )
        data = llm_json(prompt, role=role)
        if isinstance(data, dict):
            character.appearance_prompt = (
                data.get("appearance_prompt") or character.appearance_prompt
            ).strip()
            character.consistency_prompt = (
                data.get("consistency_prompt") or character.consistency_prompt
            ).strip()
        if not character.appearance_prompt:
            character.appearance_prompt = (
                f"{character.name}, {character.gender}, {character.age} years old, "
                f"{character.hairstyle} {character.outfit}"
            ).strip(", ")
        if not character.consistency_prompt:
            character.consistency_prompt = (
                f"角色 {character.name} 全剧保持 {character.hairstyle} {character.outfit} "
                "一致，不得改变。"
            )
        return character

    def find(self, project, target: str):
        """按目标文本找角色：女主角/男主角/姓名。找不到返回 None。"""
        t = (target or "").strip()
        if not t:
            return None
        if "女主角" in t or "女主" in t:
            for c in project.characters:
                if c.gender in ("女", "female"):
                    return c
        if "男主角" in t or "男主" in t:
            for c in project.characters:
                if c.gender in ("男", "male"):
                    return c
        for c in project.characters:
            if c.name and c.name in t:
                return c
        return None

    def classify_change(self, change: str) -> tuple:
        """把修改内容分类成 (字段, 值)。字段：hairstyle/outfit/personality/age/appearance。"""
        c = (change or "").strip()
        if not c:
            return ("appearance", c)
        if _AGE_RE.search(c):
            m = _AGE_RE.search(c)
            return ("age", m.group(1))
        if _PERSONALITY_RE.search(c):
            for kw in ("高冷", "温柔", "冷酷", "开朗", "内向", "外向", "腹黑", "善良",
                       "果断", "犹豫", "冷静", "暴躁", "毒舌"):
                if kw in c:
                    return ("personality", kw)
            m = _PERSONALITY_RE.search(c)
            return ("personality", m.group(1))
        if _HAIR_RE.search(c):
            m = _HAIR_RE.search(c)
            return ("hairstyle", m.group(1))
        if _OUTFIT_RE.search(c):
            m = _OUTFIT_RE.search(c)
            return ("outfit", m.group(1))
        return ("appearance", c)

    def modify(self, project, target: str, change: str) -> dict:
        """修改人物卡。返回 {ok, character, field, value, impacted_episodes}。"""
        c = self.find(project, target)
        if c is None:
            return {"ok": False, "message": f"找不到角色「{target}」，请说角色姓名"}
        field, value = self.classify_change(change)
        if not value:
            return {"ok": False, "message": "请说明要改成什么，例如：把女主角改成短发"}
        if field == "age":
            c.age = value
        elif field == "personality":
            c.personality = value
        elif field == "hairstyle":
            c.hairstyle = value
            c.appearance_prompt = f"{c.name}, {c.gender}, {c.age} years old, {c.hairstyle} {c.outfit}"
            c.consistency_prompt = f"角色 {c.name} 全剧保持 {c.hairstyle} {c.outfit} 一致，不得改变。"
        elif field == "outfit":
            c.outfit = value
            c.appearance_prompt = f"{c.name}, {c.gender}, {c.age} years old, {c.hairstyle} {c.outfit}"
            c.consistency_prompt = f"角色 {c.name} 全剧保持 {c.hairstyle} {c.outfit} 一致，不得改变。"
        else:
            c.appearance_prompt = f"{c.name}, {c.gender}, {c.age} years old, {value}"
        affected = self.impact(project, c)
        return {
            "ok": True, "character": c, "field": field, "value": value,
            "impacted_episodes": affected,
        }

    def impact(self, project, character: Character) -> list:
        """该角色出现在哪些已生成剧本的集数（1..current_episode）。"""
        affected = []
        for e in project.episodes:
            if any(
                s.character and (s.character == character.name or character.name in s.character)
                for s in e.shots
            ):
                affected.append(e.number)
        if not affected and project.current_episode > 1:
            affected = list(range(1, project.current_episode + 1))
        return affected

    def sync_episodes(self, project, character: Character, episodes: list):
        """确认后：把新外观/一致性约束同步进指定集的镜头。"""
        n = 0
        for e in project.episodes:
            if e.number not in episodes:
                continue
            for s in e.shots:
                if s.character and (s.character == character.name or character.name in s.character):
                    s.appearance = character.appearance_prompt
                    s.consistency_prompt = character.consistency_prompt
                    n += 1
        return n
