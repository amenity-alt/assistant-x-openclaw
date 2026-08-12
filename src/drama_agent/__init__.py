#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Jarvis Short Drama Agent — 短剧剪辑模式（Capability 而非 Agent）。

流程：需求收集 → 剧情规划 → 确认 → 单集剧本 → 确认 → 镜头 Prompt → 确认 → 下一集/完成。
Phase 1 不做视频生成/自动剪辑/自动音频/自动发布（produce/reclip 仅占位提示）。

用法（main.py 语音拦截层接入）：
    from drama_agent import get_drama_agent
    agent = get_drama_agent()
    agent.on_message = self._drama_on_message       # 口播/overlay
    agent.on_confirm_request = self._drama_on_confirm  # 确认请求口播
    agent.on_project_update = self._drama_push_status  # 推送 drama:status 给 Flutter
    res = agent.handle("短剧剪辑", role="jarvis")    # dict | False

回调模式与 mission_control.MissionControlAgent 同构；生成类操作后台线程执行，
handle() 立即返回，完成后经 on_project_update/on_message 通知。
"""

import os
import re
import threading
import time

from . import intent_parser
from .character_agent import CharacterAgent
from .confirm_gate import ConfirmGate
from .episode_writer import EpisodeWriter
from .models import DramaPhase, DramaStatus, Episode
from .planner import DramaPlanner
from .production import EpisodeProducer, ProductionCancelled, ProductionError
from .prompt_agent import PromptAgent
from .state_machine import DramaStateMachine
from .store import DramaProjectStore

PHASE_LABEL = {
    "collect_req": "需求收集",
    "plan": "剧情规划",
    "episode": "单集剧本",
    "prompts": "镜头提示词",
    "character": "人物调整",
    "replan": "重新规划",
    "rewrite": "重写剧本",
}


class DramaAgent:
    """短剧模式入口。"""

    def __init__(self):
        self._store = DramaProjectStore()
        self._state = DramaStateMachine()
        self._planner = DramaPlanner()
        self._characters = CharacterAgent()
        self._writer = EpisodeWriter()
        self._prompts_agent = PromptAgent()
        self._producer = EpisodeProducer()
        self._gate = ConfirmGate()
        self._lock = threading.Lock()
        self._current_id = None
        self._busy = False
        self._queued_confirm = None   # 人物修改打断前的待确认（phase/summary）
        self._gate_episode = None       # 重写/制作目标集
        self._cancel = threading.Event()
        self._backend = "ffmpeg"        # ffmpeg（默认离线）| opencut（AI）

        # main.py 注入的回调
        self.on_message = None          # fn(dict)  口播 + overlay（async 完成）
        self.on_confirm_request = None  # fn(project_id, phase, summary)
        self.on_project_update = None   # fn(dict)  drama:status 推送

    # ── 状态 ──────────────────────────────────────────────
    @property
    def current_project(self):
        with self._lock:
            cid = self._current_id
        if not cid:
            return None
        return self._store.load(cid)

    def set_current(self, project_id: str):
        with self._lock:
            self._current_id = project_id

    def _load(self, project_id: str):
        return self._store.load(project_id)

    def _save(self, project):
        project.updated_at = time.time()
        self._store.save(project)
        self._push(project)

    def _push(self, project):
        cb = self.on_project_update
        if cb is not None:
            try:
                cb(self._summary_dict(project))
            except Exception as e:
                print(f"[Drama] on_project_update 异常: {e}")

    def _message(self, project, msg: str, hud: str = None):
        cb = self.on_message
        if cb is not None:
            try:
                cb({"project": self._summary_dict(project) if project else None,
                    "message": msg, "hud": hud})
            except Exception as e:
                print(f"[Drama] on_message 异常: {e}")

    def _request_confirm(self, project, phase: str, summary: str):
        self._gate.request(project, phase, summary)
        self._save(project)
        cb = self.on_confirm_request
        if cb is not None:
            try:
                cb(project.id, phase, summary)
            except Exception as e:
                print(f"[Drama] on_confirm_request 异常: {e}")

    def _begin_generation(self):
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            return True

    def _end_generation(self):
        with self._lock:
            self._busy = False

    # ── 入口 ──────────────────────────────────────────────
    def handle(self, text: str, role: str = "jarvis"):
        """解析语音意图并执行。返回 dict（消费）或 False（未消费）。"""
        intent = intent_parser.parse(text or "")
        cmd = intent.cmd
        if cmd == "none":
            return False
        project = self.current_project

        # 无项目：只接受 enter / collect
        if project is None:
            if cmd == "enter":
                return self._enter(intent, role)
            if cmd == "collect":
                return self._enter(intent, role)
            return {
                "status": "idle",
                "message": "还没有短剧项目，请先说「短剧剪辑」开始。",
            }

        pid = project.id

        if cmd == "exit":
            return self._exit(project)
        if cmd == "status":
            return self._status(project)
        if cmd == "pause":
            return self._pause(project)
        if cmd == "resume":
            return self._resume(project)
        if cmd == "yes":
            return self._confirm(project, approved=True)
        if cmd == "no":
            return self._confirm(project, approved=False)
        if cmd in ("collect", "start", "enter"):
            return self._collect(project, intent, role)
        if cmd == "plan":
            return self._replan(project, role)
        if cmd == "character":
            return self._modify_character(project, intent, role)
        if cmd == "episode_view":
            return self._episode_view(project, intent.episode)
        if cmd == "episode_rewrite":
            return self._episode_rewrite(project, intent.episode, role)
        if cmd == "prompts":
            return self._prompts(project, intent.episode, role)
        if cmd == "produce":
            return self._produce(project, intent.episode, intent.ai)
        if cmd == "produce_all":
            return self._produce_all(project, intent.ai)
        if cmd == "stop":
            return self._stop_production(project)
        if cmd == "next":
            return self._next_episode(project, role)
        if cmd == "reclip":
            return self._reclip(project, intent.episode)
        return {"status": "unhandled", "message": "未识别该短剧指令。"}

    # ── 进入 / 需求收集 ───────────────────────────────────
    _ENTER_KEYWORDS = re.compile(
        r"(短剧剪辑|短剧模式|开启短剧|进入短剧|退出短剧|关闭短剧|结束短剧|"
        r"short\s*drama|drama\s*mode|短剧|drama)", re.I
    )

    @classmethod
    def _bare_enter(cls, text: str) -> bool:
        """去掉入口关键词后没有实质内容 → 纯入口指令。"""
        rest = cls._ENTER_KEYWORDS.sub("", text or "")
        rest = re.sub(r"^(?:请|帮我|麻烦|给我|帮|jarvis|贾维斯)\s*", "", rest)
        return not rest.strip(" ，,。")

    def _enter(self, intent, role: str) -> dict:
        with self._lock:
            if self._busy:
                return {"status": "busy", "message": "上一个短剧任务还在生成中，请稍候。"}
        project = self.current_project
        if project is None:
            from .models import DramaProject
            project = DramaProject(
                title="", genre="", total_episodes=10, duration_per_episode=60,
                status=DramaStatus.COLLECTING, phase=DramaPhase.COLLECT_REQ,
            )
            self.set_current(project.id)
            self._save(project)
        if self._bare_enter(intent.text):
            # 纯入口指令：只收集需求，不把「短剧剪辑」误当主题
            return {
                "status": "collecting",
                "message": "短剧模式已开启。请告诉我主题、集数和每集时长，例如："
                           "帮我做一个10集每集1分钟的都市逆袭短剧。",
            }
        fields = intent_parser.collect_fields(intent.text)
        if not fields:
            return {
                "status": "collecting",
                "message": "短剧模式已开启。请告诉我主题、集数和每集时长，例如："
                           "帮我做一个10集每集1分钟的都市逆袭短剧。",
            }
        return self._apply_fields(project, fields, role)

    def _collect(self, project, intent, role: str) -> dict:
        if self._bare_enter(intent.text):
            pending = self._gate.pending()
            if pending:
                return {"status": "awaiting", "message": "请先确认或取消当前步骤。"}
            return {
                "status": "collecting",
                "message": "短剧模式已开启。请告诉我主题、集数和每集时长，例如："
                           "帮我做一个10集每集1分钟的都市逆袭短剧。",
            }
        fields = intent_parser.collect_fields(intent.text)
        if not fields:
            pending = self._gate.pending()
            if pending:
                return {"status": "awaiting", "message": "请先确认或取消当前步骤。"}
            missing = []
            if not project.title:
                missing.append("主题")
            return {
                "status": "collecting",
                "message": f"还缺少：{'、'.join(missing)}。请补充，例如：主题是都市逆袭。"
                if missing else "请描述你的短剧创意。",
            }
        return self._apply_fields(project, fields, role)

    def _apply_fields(self, project, fields: dict, role: str) -> dict:
        if fields.get("theme"):
            project.title = fields["theme"]
        if fields.get("genre"):
            project.genre = fields["genre"]
        if fields.get("episodes"):
            project.total_episodes = fields["episodes"]
        if fields.get("duration"):
            project.duration_per_episode = fields["duration"]
        if fields.get("style"):
            project.visual_style = fields["style"]
        # 需求是否足够开规划
        if project.title:
            self._save(project)
            return self._start_plan(project, role)
        return {
            "status": "collecting",
            "message": "还缺少主题。请告诉我你想做什么题材的短剧。",
        }

    # ── 规划（后台线程）───────────────────────────────────
    def _start_plan(self, project, role: str) -> dict:
        if not self._begin_generation():
            return {"status": "busy", "message": "上一个任务还在生成中，请稍候。"}
        self._set_status(project, DramaStatus.PLANNING)
        self._save(project)

        def _work():
            try:
                plan = self._planner.plan_story(
                    project.title, project.genre, project.visual_style,
                    project.total_episodes, role=role,
                )
                project.title = plan["title"]
                project.logline = plan["logline"]
                project.worldview = plan["worldview"]
                project.main_plot = plan["main_plot"]
                project.episode_goals = plan["episode_goals"]
                project.relationship_map = plan["relationship_map"]
                from .models import Character
                project.characters = [
                    Character(**{k: v for k, v in c.items()
                                 if k in Character.__dataclass_fields__})
                    for c in plan["characters"]
                ] if plan.get("characters") else []
                for c in project.characters:
                    self._characters.design(c, role=role)
                project.episodes = [
                    Episode(number=i + 1, title=f"第{i + 1}集",
                            goal=project.episode_goals[i] if i < len(project.episode_goals) else "")
                    for i in range(project.total_episodes)
                ]
                self._set_status(project, DramaStatus.AWAITING_CONFIRM)
                chars = "、".join(c.name for c in project.characters) or "待定"
                goals = "，".join(project.episode_goals[:5])
                if len(project.episode_goals) > 5:
                    goals += f" 等{len(project.episode_goals)}集"
                summary = (
                    f"《{project.title}》{project.total_episodes}集·每集"
                    f"{project.duration_per_episode // 60}分钟。人物：{chars}。"
                    f"主线：{project.episode_goals[0] if project.episode_goals else ''} → {goals}"
                )
                self._request_confirm(project, "plan", summary)
                self._message(project, f"规划完成：{summary}", hud="DRAMA PLAN READY")
            except Exception as e:
                print(f"[Drama] 规划异常: {e}")
                self._set_status(project, DramaStatus.FAILED)
                self._save(project)
                self._message(project, f"剧情规划失败：{e}")
            finally:
                self._end_generation()

        threading.Thread(target=_work, daemon=True).start()
        return {
            "status": "planning",
            "message": f"好的，正在规划《{project.title}》的剧情，请稍等。",
        }

    # ── 确认 ──────────────────────────────────────────────
    def _confirm(self, project, approved: bool) -> dict:
        if self._busy:
            return {"status": "busy", "message": "还在生成中，请稍后再确认。"}
        reply = self._gate.reply(project.id, approved)
        if reply is None:
            return {"status": "no_pending", "message": "当前没有需要确认的步骤。"}
        phase = reply["phase"]
        if reply["expired"]:
            return {
                "status": "expired",
                "message": f"确认超时（60秒），{PHASE_LABEL.get(phase, phase)}已取消。",
            }
        if not reply["approved"]:
            project.pending_confirm = {}
            self._save(project)
            return {"status": "cancelled", "message": "已取消。"}
        project.pending_confirm = {}
        return self._advance(project, phase)

    def _advance(self, project, phase: str) -> dict:
        if phase == "plan":
            self._set_status(project, DramaStatus.EPISODE_DESIGN)
            self._save(project)
            return self._design_episode(project, project.current_episode)
        if phase == "episode":
            self._set_status(project, DramaStatus.PROMPTS)
            self._save(project)
            return self._generate_prompts(project, project.current_episode)
        if phase == "prompts":
            if project.current_episode < project.total_episodes:
                project.current_episode += 1
                self._set_status(project, DramaStatus.EPISODE_DESIGN)
                self._save(project)
                return self._design_episode(project, project.current_episode)
            self._set_status(project, DramaStatus.COMPLETED)
            self._save(project)
            return {
                "status": "completed",
                "message": f"《{project.title}》全部 {project.total_episodes} 集规划完成。"
                           "「开始制作第X集」将在第二阶段接入视频生成。",
            }
        if phase == "character":
            return self._finish_character(project)
        if phase == "replan":
            return self._start_plan(project, "jarvis")
        if phase == "rewrite":
            ep = self._gate_episode or project.current_episode
            return self._design_episode(project, ep)
        if phase == "produce":
            ep = self._gate_episode or project.current_episode
            backend = self._backend or "ffmpeg"
            return self._start_production(project, ep, backend)
        if phase == "produce_all":
            backend = self._backend or "ffmpeg"
            return self._start_batch_production(project, backend)
        return {"status": "ok", "message": "已确认。"}

    # ── 单集剧本（后台线程）───────────────────────────────
    def _design_episode(self, project, number: int) -> dict:
        if not self._begin_generation():
            return {"status": "busy", "message": "上一个任务还在生成中，请稍候。"}
        self._set_status(project, DramaStatus.EPISODE_DESIGN)
        self._save(project)
        role = self._role_hint()

        def _work():
            try:
                script_md, shots = self._writer.write(project, number, role=role)
                ep = project.episode(number)
                if ep is None:
                    ep = Episode(number=number, title=f"第{number}集")
                    project.episodes.append(ep)
                ep.script = script_md
                from .models import StoryboardShot
                ep.shots = [StoryboardShot.from_dict(s) for s in shots]
                ep.status = "script_ready"
                ep.files["script.md"] = self._store.save_script(project.id, number, script_md)
                ep.files["storyboard.json"] = self._store.save_storyboard(
                    project.id, number, [s.to_dict() for s in ep.shots])
                self._set_status(project, DramaStatus.AWAITING_CONFIRM)
                summary = (
                    f"第{number}集《{ep.title}》剧本完成，共 {len(ep.shots)} 个镜头。"
                    f"梗概：{ep.synopsis[:60]}"
                )
                self._request_confirm(project, "episode", summary)
                self._message(project, f"第{number}集剧本完成，共 {len(ep.shots)} 个镜头。",
                              hud=f"EPISODE {number:02d} SCRIPT READY")
            except Exception as e:
                print(f"[Drama] 剧本生成异常: {e}")
                self._set_status(project, DramaStatus.FAILED)
                self._save(project)
                self._message(project, f"第{number}集剧本生成失败：{e}")
            finally:
                self._end_generation()

        threading.Thread(target=_work, daemon=True).start()
        return {
            "status": "writing",
            "message": f"正在创作第{number}集剧本，请稍等。",
        }

    # ── 镜头 Prompt（后台线程）────────────────────────────
    def _generate_prompts(self, project, number: int) -> dict:
        ep = project.episode(number)
        if ep is None or not ep.shots:
            return {"status": "no_script",
                    "message": f"第{number}集还没有剧本，请先生成剧本。"}
        if not self._begin_generation():
            return {"status": "busy", "message": "上一个任务还在生成中，请稍候。"}
        self._set_status(project, DramaStatus.PROMPTS)
        self._save(project)
        role = self._role_hint()
        shots = [s.to_dict() for s in ep.shots]

        def _work():
            try:
                packs = self._prompts_agent.generate(project, number, shots, role=role)
                for pack in packs:
                    self._store.save_shot_prompt(project.id, number,
                                                 pack["shot_id"], pack)
                    for s in ep.shots:
                        if s.shot_id == pack["shot_id"]:
                            s.video_prompt = pack["video_prompt"]
                            s.negative_prompt = pack["negative_prompt"]
                            s.consistency_prompt = pack["consistency_prompt"]
                ep.status = "prompts_ready"
                ep.files["prompts"] = f"episodes/episode_{number:02d}/prompts"
                self._set_status(project, DramaStatus.AWAITING_CONFIRM)
                summary = (
                    f"第{number}集 {len(packs)} 个镜头的生成提示词已完成，"
                    "确认后进入下一集（或完成）。"
                )
                self._request_confirm(project, "prompts", summary)
                self._message(project, f"第{number}集 {len(packs)} 个镜头提示词已完成。",
                              hud=f"EPISODE {number:02d} PROMPTS READY")
            except Exception as e:
                print(f"[Drama] Prompt 生成异常: {e}")
                self._set_status(project, DramaStatus.FAILED)
                self._save(project)
                self._message(project, f"第{number}集提示词生成失败：{e}")
            finally:
                self._end_generation()

        threading.Thread(target=_work, daemon=True).start()
        return {
            "status": "prompting",
            "message": f"正在为第{number}集生成镜头提示词，请稍等。",
        }

    # ── 制作（Phase 2 渲染）─────────────────────────────
    def _start_production(self, project, number: int, backend: str = "ffmpeg") -> dict:
        if not self._begin_generation():
            return {"status": "busy", "message": "上一个任务还在生成中，请稍候。"}
        self._cancel.clear()
        ep = project.episode(number)
        project.production = {
            "state": "queued", "progress": 0,
            "shot": 0, "total": len(ep.shots) if ep else 0,
            "backend": backend, "output": "",
        }
        self._save(project)

        def on_progress(state, shot, total, pct, msg):
            project.production = {
                "state": state, "progress": pct,
                "shot": shot, "total": total,
                "backend": backend, "output": "",
            }
            self._save(project)

        def _work():
            try:
                res = self._producer.render(
                    project, number, backend=backend,
                    on_progress=on_progress, cancel=self._cancel,
                )
                ep = project.episode(number)
                if ep is not None:
                    ep.status = "produced"
                    ep.files["video"] = res["output"]
                project.production = {
                    "state": "done", "progress": 100,
                    "shot": res["shots"], "total": res["shots"],
                    "backend": backend, "output": res["output"],
                }
                self._save(project)
                self._message(
                    project,
                    f"第{number}集渲染完成，视频已导出到 {res['output']}。"
                    "可以说「查看第X集」或「进入下一集」继续。",
                    hud=f"EPISODE {number:02d} RENDERED",
                )
            except ProductionCancelled:
                project.production = {"state": "cancelled", "progress": 0,
                                      "shot": 0, "total": 0,
                                      "backend": backend, "output": ""}
                self._save(project)
                self._message(project, "已停止制作。", hud="DRAMA RENDER STOPPED")
            except ProductionError as e:
                project.production = {"state": "failed", "progress": 0,
                                      "shot": 0, "total": 0,
                                      "backend": backend, "output": ""}
                self._save(project)
                self._message(project, f"制作失败：{e}")
            except Exception as e:
                print(f"[Drama] 制作异常: {e}")
                project.production = {"state": "failed", "progress": 0,
                                      "shot": 0, "total": 0,
                                      "backend": backend, "output": ""}
                self._save(project)
                self._message(project, f"制作失败：{e}")
            finally:
                self._end_generation()

        threading.Thread(target=_work, daemon=True).start()
        return {"status": "producing",
                "message": f"开始制作第{number}集（{'AI' if backend == 'opencut' else '本地'}渲染），"
                           "完成后我会汇报。"}

    def _start_batch_production(self, project, backend: str = "ffmpeg") -> dict:
        """按顺序制作全部未完成集。"""
        if not self._begin_generation():
            return {"status": "busy", "message": "上一个任务还在生成中，请稍候。"}
        self._cancel.clear()
        todo = [e.number for e in project.episodes if e.status != "produced"]
        project.production = {
            "state": "queued", "progress": 0,
            "shot": 0, "total": len(todo), "batch": True,
            "backend": backend, "output": "",
        }
        self._save(project)

        def _work():
            done, failed = [], []
            try:
                for n in todo:
                    if self._cancel.is_set():
                        raise ProductionCancelled("制作已停止")
                    ep = project.episode(n)
                    project.production.update(
                        {"state": "rendering", "progress": 0,
                         "shot": n, "total": len(todo), "batch": True,
                         "backend": backend, "output": ""})
                    self._save(project)
                    self._message(project, f"开始制作第{n}集…",
                                  hud=f"BATCH RENDER EP {n:02d}")
                    res = self._producer.render(
                        project, n, backend=backend, cancel=self._cancel,
                        on_progress=lambda st, sh, tt, pct, msg, _n=n: self._save(
                            self._update_batch_progress(project, _n, pct, st)),
                    )
                    ep = project.episode(n)
                    if ep is not None:
                        ep.status = "produced"
                        ep.files["video"] = res["output"]
                    self._save(project)
                    done.append(n)
                project.production = {
                    "state": "done", "progress": 100,
                    "shot": done[-1] if done else 0, "total": len(todo),
                    "batch": True, "backend": backend, "output": "",
                }
                self._save(project)
                self._message(
                    project,
                    f"批量制作完成：第{'、'.join(map(str, done))}集已导出到 "
                    f"{os.path.expanduser('~/Movies/JarvisDramas')}。"
                    if done else "批量制作完成。",
                    hud="BATCH RENDER DONE",
                )
            except ProductionCancelled:
                project.production = {"state": "cancelled", "progress": 0,
                                      "shot": 0, "total": len(todo),
                                      "batch": True, "backend": backend,
                                      "output": ""}
                self._save(project)
                self._message(project, "批量制作已停止。", hud="BATCH RENDER STOPPED")
            except ProductionError as e:
                project.production = {"state": "failed", "progress": 0,
                                      "shot": 0, "total": len(todo),
                                      "batch": True, "backend": backend,
                                      "output": ""}
                self._save(project)
                self._message(project, f"批量制作失败（第{done[-1] if done else 1}集后停止）：{e}")
            except Exception as e:
                print(f"[Drama] 批量制作异常: {e}")
                project.production = {"state": "failed", "progress": 0,
                                      "shot": 0, "total": len(todo),
                                      "batch": True, "backend": backend,
                                      "output": ""}
                self._save(project)
                self._message(project, f"批量制作失败：{e}")
            finally:
                self._end_generation()

        threading.Thread(target=_work, daemon=True).start()
        return {"status": "producing",
                "message": f"开始批量制作 {len(todo)} 集，完成后我会汇报。"}

    def _update_batch_progress(self, project, episode, pct, state):
        prod = dict(project.production)
        prod.update({"state": state, "progress": pct, "shot": episode, "batch": True})
        project.production = prod
        return project

    # ── 人物修改 ──────────────────────────────────────────
    def _modify_character(self, project, intent, role: str) -> dict:
        if self._busy:
            return {"status": "busy", "message": "还在生成中，请稍后再修改人物。"}
        res = self._characters.modify(project, intent.target, intent.change)
        if not res.get("ok"):
            return {"status": "failed", "message": res.get("message", "修改失败。")}
        c = res["character"]
        affected = res["impacted_episodes"]
        self._save(project)
        if affected:
            pending = self._gate.pending()
            if pending:
                self._queued_confirm = pending
            self._gate_episode = None
            summary = (
                f"已把「{c.name}」的{res['field']}改为「{res['value']}」。"
                f"这会影响第 {'、'.join(map(str, affected))} 集的人物一致性，是否同步更新这些集？"
            )
            self._request_confirm(project, "character", summary)
            return {"status": "confirm", "message": summary}
        return {
            "status": "ok",
            "message": f"已更新「{c.name}」的{res['field']}：{res['value']}。"
                       "后续集数的镜头将使用新设定。",
        }

    def _finish_character(self, project) -> dict:
        if self._queued_confirm:
            q = self._queued_confirm
            self._queued_confirm = None
            self._request_confirm(project, q["phase"], q["summary"])
            return {"status": "ok", "message": "人物已同步。请继续确认下一步。"}
        return {"status": "ok", "message": "人物设定已同步到相关剧集。"}

    # ── 查看 / 重写 / Prompt / 制作 / 下一集 ───────────────
    def _episode_view(self, project, number: int) -> dict:
        n = number or project.current_episode
        ep = project.episode(n)
        if ep is None:
            return {"status": "no_episode", "message": f"还没有第{n}集。"}
        if not ep.script:
            return {"status": "no_script", "message": f"第{n}集还没有剧本，请先确认规划后生成。"}
        head = "\n".join(ep.script.splitlines()[:24])
        return {
            "status": "ok",
            "message": f"第{n}集《{ep.title}》：{ep.synopsis or ''}\n{head[:220]}",
            "hud": f"EPISODE {n:02d} SCRIPT",
        }

    def _episode_rewrite(self, project, number: int, role: str) -> dict:
        if self._busy:
            return {"status": "busy", "message": "还在生成中，请稍后再重写。"}
        n = number or project.current_episode
        self._gate_episode = n
        summary = f"将重新生成第{n}集剧本，是否继续？"
        self._request_confirm(project, "rewrite", summary)
        return {"status": "confirm", "message": summary}

    def _prompts(self, project, number: int, role: str) -> dict:
        if self._busy:
            return {"status": "busy", "message": "还在生成中，请稍候。"}
        n = number or project.current_episode
        ep = project.episode(n)
        if ep is None or not ep.shots:
            return {"status": "no_script", "message": f"第{n}集还没有剧本，请先生成剧本。"}
        return self._generate_prompts(project, n)

    def _produce(self, project, number: int, ai: bool = False) -> dict:
        if self._busy:
            return {"status": "busy", "message": "还在生成中，请稍候。"}
        n = number or project.current_episode
        ep = project.episode(n)
        if ep is None or not ep.shots:
            return {"status": "no_script",
                    "message": f"第{n}集还没有剧本与镜头，请先确认规划后再制作。"}
        backend = "opencut" if ai else "ffmpeg"
        self._gate_episode = n
        self._backend = backend
        label = "AI（OpenCut）" if backend == "opencut" else "本地"
        summary = (
            f"将使用{label}渲染第{n}集（{len(ep.shots)} 个镜头，约"
            f"{sum(int(s.duration or 5) for s in ep.shots)} 秒），"
            f"预计需要几分钟，是否开始？"
        )
        self._request_confirm(project, "produce", summary)
        return {"status": "confirm", "message": summary}

    def _produce_all(self, project, ai: bool = False) -> dict:
        if self._busy:
            return {"status": "busy", "message": "还在生成中，请稍候。"}
        todo = [e.number for e in project.episodes if e.status != "produced"]
        if not todo:
            return {"status": "done", "message": "所有剧集都已制作完成。"}
        self._gate_episode = 0
        self._backend = "opencut" if ai else "ffmpeg"
        label = "AI（OpenCut）" if ai else "本地"
        summary = (
            f"将使用{label}按顺序制作剩余 {len(todo)} 集（"
            f"第{'、'.join(str(n) for n in todo[:5])}"
            f"{'…' if len(todo) > 5 else ''}），预计需要较长时间，是否开始？"
        )
        self._request_confirm(project, "produce_all", summary)
        return {"status": "confirm", "message": summary}

    def _stop_production(self, project) -> dict:
        if not self._busy:
            return {"status": "idle", "message": "当前没有正在制作的任务。"}
        self._cancel.set()
        return {"status": "ok", "message": "好的，正在停止制作…"}

    def _next_episode(self, project, role: str) -> dict:
        if self._busy:
            return {"status": "busy", "message": "还在生成中，请稍候。"}
        if project.current_episode >= project.total_episodes:
            return {"status": "done",
                    "message": "全部剧集已完成规划。可查看任意一集或开始制作。"}
        project.current_episode += 1
        self._set_status(project, DramaStatus.EPISODE_DESIGN)
        self._save(project)
        return self._design_episode(project, project.current_episode)

    def _reclip(self, project, number: int) -> dict:
        n = number or project.current_episode
        return {
            "status": "phase2",
            "message": f"重新剪辑第{n}集将在第二阶段接入 OpenCut。当前暂不支持。",
        }

    def _replan(self, project, role: str) -> dict:
        if self._busy:
            return {"status": "busy", "message": "还在生成中，请稍候。"}
        summary = "将重新规划整个剧情（覆盖当前规划），是否继续？"
        self._request_confirm(project, "replan", summary)
        return {"status": "confirm", "message": summary}

    # ── 暂停 / 继续 / 退出 / 状态 ─────────────────────────
    def _pause(self, project) -> dict:
        if project.status == DramaStatus.PAUSED:
            return {"status": "ok", "message": "短剧模式已处于暂停状态。"}
        self._set_status(project, DramaStatus.PAUSED)
        self._save(project)
        return {"status": "ok", "message": "已暂停短剧制作。说「继续短剧」恢复。"}

    def _resume(self, project) -> dict:
        if project.status != DramaStatus.PAUSED:
            return {"status": "ok", "message": "短剧模式没有在暂停状态。"}
        target = {
            DramaPhase.PLAN: DramaStatus.AWAITING_CONFIRM,
            DramaPhase.EPISODE_SCRIPT: DramaStatus.EPISODE_DESIGN,
            DramaPhase.EPISODE_PROMPTS: DramaStatus.PROMPTS,
        }.get(project.phase, DramaStatus.AWAITING_CONFIRM)
        self._set_status(project, target)
        self._save(project)
        pending = self._gate.pending()
        if pending:
            return {"status": "ok", "message": f"已恢复。请确认：{pending['summary'][:80]}"}
        return {"status": "ok", "message": "已恢复短剧制作。"}

    def _exit(self, project) -> dict:
        self._gate.clear()
        self._cancel.set()
        self._save(project)
        self._message(project, "", hud="DRAMA OFF")
        with self._lock:
            self._current_id = None
        return {"status": "exit", "message": "已退出短剧模式。说「短剧剪辑」可随时继续。"}

    def _status(self, project) -> dict:
        pending = self._gate.pending()
        msg = (
            f"短剧《{project.title}》：第 {project.current_episode}/{project.total_episodes} 集，"
            f"当前阶段「{PHASE_LABEL.get(project.phase.value if hasattr(project.phase, 'value') else project.phase, project.phase)}」"
        )
        if self._busy:
            msg += "，正在生成中，请稍候。"
        elif pending:
            msg += f"。待确认：{pending['summary'][:80]}"
        elif project.status == DramaStatus.COMPLETED:
            msg += "，全部集数已完成规划。"
        else:
            msg += "。说「查看第X集」或「生成第X集提示词」继续。"
        return {"status": "ok", "message": msg, "hud": "DRAMA STATUS"}

    # ── 工具 ──────────────────────────────────────────────
    def _set_status(self, project, status: DramaStatus):
        try:
            self._state.transition(project, status)
        except ValueError as e:
            print(f"[Drama] 状态迁移跳过（保持现状）: {e}")
            project.status = status
            project.history.append({"t": time.time(),
                                    "from": getattr(project.status, 'value', ''),
                                    "to": status.value})
        if status == DramaStatus.AWAITING_CONFIRM:
            project.phase = self._phase_for_pending()
        elif status == DramaStatus.PLANNING:
            project.phase = DramaPhase.PLAN
        elif status == DramaStatus.EPISODE_DESIGN:
            project.phase = DramaPhase.EPISODE_SCRIPT
        elif status == DramaStatus.PROMPTS:
            project.phase = DramaPhase.EPISODE_PROMPTS
        elif status == DramaStatus.COMPLETED:
            project.phase = DramaPhase.DONE
        elif status == DramaStatus.COLLECTING:
            project.phase = DramaPhase.COLLECT_REQ

    def _phase_for_pending(self) -> DramaPhase:
        p = self._gate.pending()
        return {
            "plan": DramaPhase.PLAN,
            "episode": DramaPhase.EPISODE_SCRIPT,
            "prompts": DramaPhase.EPISODE_PROMPTS,
            "character": DramaPhase.EPISODE_SCRIPT,
            "replan": DramaPhase.PLAN,
            "rewrite": DramaPhase.EPISODE_SCRIPT,
        }.get((p or {}).get("phase"), DramaPhase.REVIEW)

    def _role_hint(self) -> str:
        return "jarvis"

    def _summary_dict(self, project) -> dict:
        """紧凑摘要（推给 Flutter overlay，去掉剧本/镜头等大字段）。"""
        d = project.to_dict()
        d.pop("history", None)
        d.pop("worldview", None)
        d.pop("main_plot", None)
        d.pop("relationship_map", None)
        # 人物只保留姓名
        for c in d.get("characters", []):
            for k in ("hairstyle", "outfit", "personality", "voice", "background",
                      "appearance_prompt", "consistency_prompt", "age", "gender"):
                c.pop(k, None)
        # 集数只保留状态与成品视频路径
        for e in d.get("episodes", []):
            e.pop("script", None)
            e.pop("shots", None)
            e.pop("goal", None)
            e.pop("synopsis", None)
            files = e.get("files") or {}
            e["video"] = files.get("video", "")
            e.pop("files", None)
        pending = self._gate.pending()
        d["pending_confirm"] = pending or d.get("pending_confirm", {})
        return d


# ── 单例 ───────────────────────────────────────────────
_agent = None
_agent_lock = threading.Lock()


def get_drama_agent() -> DramaAgent:
    global _agent
    with _agent_lock:
        if _agent is None:
            _agent = DramaAgent()
        return _agent
