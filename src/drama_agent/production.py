#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Short Drama — Phase 2 视频渲染流水线（storyboard → 时间线 → 导出）。

后端：
  - ffmpeg（默认，离线可用）：每镜头生成 JARVIS HUD 风格场景卡 →
    Ken Burns 缩放运镜 → 角色配音（macOS say，按对白语言/角色性别选声线）
    → 拼接 → 导出 ~/Movies/JarvisDramas/<剧名>/episode_XX.mp4
  - opencut：每镜头调用 video_agent（OpenCut AI 视频）生成素材后统一转码拼接，
    需要 OpenCut 已配置 DeepSeek/Gemini key；失败会明确报错。

进度：render() 内通过 on_progress(state, shot, total, progress, message) 回调，
cancel（threading.Event）在镜头间检查，支持语音“停止制作”。
"""

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

from PIL import Image, ImageDraw, ImageFont

_FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"
_FONT_FALLBACKS = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
]
_OUTPUT_ROOT = os.path.expanduser("~/Movies/JarvisDramas")

_ACCENTS = [
    (0x2F, 0x8C, 0xFF),  # JARVIS 蓝
    (0x46, 0xE0, 0xA8),  # 青绿
    (0x9B, 0x7B, 0xFF),  # 紫
    (0xFF, 0xB8, 0x4D),  # 金
    (0x4D, 0xD2, 0xFF),  # 亮青
]


class ProductionError(RuntimeError):
    pass


class ProductionCancelled(ProductionError):
    pass


def _font(size: int):
    for path in (_FONT_PATH, *_FONT_FALLBACKS):
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _slug(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", title.strip() or "untitled")[:60] or "untitled"


def _is_zh(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _wrap(text: str, width: int) -> list:
    """CJK 按字符折行；混合文本按词折行。"""
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if _is_zh(ch):
            if len(cur) >= width:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        else:
            if len(cur) >= width * 2 or (cur and cur[-1] == " " and len(cur) >= width):
                lines.append(cur)
                cur = ch
            else:
                cur += ch
    if cur:
        lines.append(cur)
    return lines or [""]


def _voice_for(character: str, characters: list, text: str) -> str:
    zh = _is_zh(text)
    gender = ""
    for c in characters:
        if c.get("name") == character:
            gender = c.get("gender", "")
            break
    if zh:
        return "Reed" if gender == "男" else "Tingting"
    return "Alex" if gender == "男" else "Samantha"


# ── 场景卡（PIL，JARVIS HUD 风格）────────────────────────
def _scene_card(shot: dict, index: int, total: int, episode: int,
                project: dict, width: int = 1920, height: int = 1080) -> str:
    acc = _ACCENTS[(index - 1) % len(_ACCENTS)]
    img = Image.new("RGB", (width, height), (6, 11, 22))
    d = ImageDraw.Draw(img)

    # 深空渐变背景
    for y in range(height):
        t = y / height
        r = int(6 + 10 * t)
        g = int(11 + 22 * t)
        b = int(22 + 34 * t)
        d.line([(0, y), (width, y)], fill=(r, g, b))
    # 中心径向光晕
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy = width // 2, int(height * 0.42)
    for i in range(220, 0, -8):
        a = int(26 * (1 - i / 220))
        gd.ellipse([cx - i, cy - i, cx + i, cy + i],
                   outline=(acc[0], acc[1], acc[2], a), width=2)
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    d = ImageDraw.Draw(img)

    # 四角 HUD 亮角
    L = 46
    for (x0, y0, dx, dy) in ((24, 24, 1, 1), (width - 24, 24, -1, 1),
                             (24, height - 24, 1, -1), (width - 24, height - 24, -1, -1)):
        d.line([(x0, y0), (x0 + dx * L, y0)], fill=(acc[0], acc[1], acc[2]), width=4)
        d.line([(x0, y0), (x0, y0 + dy * L)], fill=(acc[0], acc[1], acc[2]), width=4)
    # 细边框
    d.rectangle([16, 16, width - 16, height - 16],
                outline=(acc[0], acc[1], acc[2], 120), width=1)

    f_small = _font(30)
    f_mid = _font(40)
    f_title = _font(88)
    f_dlg = _font(46)

    # 顶栏：剧名 + EP/镜头
    title = project.get("title") or "UNTITLED"
    d.text((64, 56), f"JARVIS DRAMA · {title[:14]}", font=_font(30),
           fill=(0x8C, 0xC1, 0xFA))
    d.text((width - 420, 56), f"EP {episode:02d} · SHOT {index:02d}/{total:02d}",
           font=_font(30), fill=(0x8C, 0xC1, 0xFA))

    # 中央：场景名 + 人物 chip
    scene = (shot.get("scene") or "未命名场景").strip()
    d.rectangle([64, 300, 76, 396], fill=(acc[0], acc[1], acc[2]))
    for i, line in enumerate(_wrap(scene, 16)[:2]):
        d.text((104, 300 + i * 100), line, font=f_title,
               fill=(0xE8, 0xF4, 0xFF))
    char = (shot.get("character") or "").strip()
    if char:
        cw = len(char) * 34 + 40
        d.rounded_rectangle([104, 520, 104 + cw, 584], radius=32,
                            fill=(acc[0], acc[1], acc[2], 40),
                            outline=(acc[0], acc[1], acc[2], 160), width=2)
        d.text((124, 534), char, font=_font(36), fill=(acc[0], acc[1], acc[2]))

    # 动作（折行）
    action = (shot.get("action") or "").strip()
    ay = 660
    for line in _wrap(action, 34)[:3]:
        d.text((64, ay), line, font=f_mid, fill=(0xC9, 0xDE, 0xF2))
        ay += 54

    # 左下：镜头参数
    meta_lines = [
        f"CAM  {shot.get('camera') or '-'}",
        f"LIT  {shot.get('lighting') or '-'}",
        f"MOOD {shot.get('mood') or '-'}",
        f"STY  {shot.get('style') or '-'}",
        f"SFX  {shot.get('sfx') or '-'}  BGM  {shot.get('bgm') or '-'}",
    ]
    my = height - 340
    for line in meta_lines:
        d.text((64, my), line, font=f_small, fill=(0x5B, 0x8D, 0xB8))
        my += 44

    # 右下：时长
    d.text((width - 260, height - 320), f"{shot.get('duration', 5)}s",
           font=_font(56), fill=(acc[0], acc[1], acc[2]))

    # 底部：对白框
    dialogue = (shot.get("dialogue") or "").strip()
    if dialogue:
        box = [64, height - 220, width - 64, height - 88]
        d.rounded_rectangle(box, radius=16, fill=(0x0A, 0x14, 0x30, 230),
                            outline=(0x9F, 0xD0, 0xFF, 120), width=2)
        d.text((96, height - 196), "“" + _wrap(dialogue, 44)[0][:44] + "”",
               font=f_dlg, fill=(0xFF, 0xFF, 0xFF))
        d.text((width - 360, height - 196), f"VOICE {_voice_for(char, project.get('characters', []), dialogue)}",
               font=_font(28), fill=(0x5B, 0x8D, 0xB8))

    out = tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir="/tmp")
    out.close()
    img.save(out.name)
    return out.name


# ── ffmpeg 封装 ──────────────────────────────────────────
def _run(cmd: list):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except FileNotFoundError as e:
        raise ProductionError("未找到 ffmpeg，请先安装：brew install ffmpeg") from e
    if r.returncode != 0:
        raise ProductionError(
            "ffmpeg 失败: " + (r.stderr or r.stdout or "")[-400:])
    return r


def _dialogue_wav(text: str, voice: str, rate: int = 190) -> str | None:
    aiff = tempfile.NamedTemporaryFile(suffix=".aiff", delete=False, dir="/tmp")
    aiff.close()
    try:
        subprocess.run(
            ["say", "-v", voice, "-r", str(rate), "-o", aiff.name, text],
            capture_output=True, timeout=120,
        )
        if not os.path.isfile(aiff.name) or os.path.getsize(aiff.name) == 0:
            return None
        wav = aiff.name.rsplit(".", 1)[0] + ".wav"
        _run(["ffmpeg", "-y", "-loglevel", "error", "-i", aiff.name, wav])
        return wav
    except Exception as e:
        print(f"[Drama] 配音失败: {e}")
        return None


class FFmpegShotRenderer:
    """默认离线后端：场景卡 + Ken Burns + say 配音。"""

    name = "ffmpeg"

    def __init__(self, width: int = 1920, height: int = 1080, fps: int = 25):
        self.width = width
        self.height = height
        self.fps = fps

    def render_shot(self, shot: dict, index: int, total: int, episode: int,
                    project: dict, work_dir: str) -> str:
        dur = max(2, min(int(shot.get("duration") or 5), 10))
        card = _scene_card(shot, index, total, episode, project,
                           self.width, self.height)
        try:
            frames = dur * self.fps
            silent = os.path.join(work_dir, f"shot_{index:02d}_v.mp4")
            vf = (
                f"scale={self.width * 2}:-1,"
                f"zoompan=z='min(zoom+0.0009,1.18)':d={frames}:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"s={self.width}x{self.height}:fps={self.fps}"
            )
            _run([
                "ffmpeg", "-y", "-loglevel", "error", "-i", card,
                "-filter_complex", vf, "-t", str(dur), "-r", str(self.fps),
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-an", silent,
            ])
            out = os.path.join(work_dir, f"shot_{index:02d}.mp4")
            dialogue = (shot.get("dialogue") or "").strip()
            char = (shot.get("character") or "").strip()
            voice = _voice_for(char, project.get("characters", []), dialogue)
            if dialogue:
                wav = _dialogue_wav(dialogue, voice)
                if wav:
                    _run([
                        "ffmpeg", "-y", "-loglevel", "error", "-i", silent,
                        "-i", wav,
                        "-filter_complex", "[1:a]adelay=300|300,apad[a]",
                        "-map", "0:v", "-map", "[a]", "-t", str(dur),
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                        "-ar", "44100", "-ac", "2", out,
                    ])
                    return out
            # 无对白/配音失败 → 静音轨（保证 concat 流统一）
            _run([
                "ffmpeg", "-y", "-loglevel", "error", "-i", silent,
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", str(dur), "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-shortest", out,
            ])
            return out
        finally:
            try:
                os.remove(card)
            except OSError:
                pass


class OpenCutShotRenderer:
    """OpenCut 后端：每镜头调用 video_agent.generate（需配置 AI key）。"""

    name = "opencut"

    def __init__(self, width: int = 1920, height: int = 1080, fps: int = 25):
        self.width = width
        self.height = height
        self.fps = fps

    def render_shot(self, shot: dict, index: int, total: int, episode: int,
                    project: dict, work_dir: str) -> str:
        from video_agent import get_video_agent

        agent = get_video_agent()
        if not agent.client.has_ai_key():
            raise ProductionError("OpenCut 未配置 AI key（DeepSeek/Gemini），"
                                  "无法使用 AI 后端；请说「开始制作第X集」用默认后端")
        dur = max(2, min(int(shot.get("duration") or 5), 10))
        prompt = (shot.get("video_prompt") or shot.get("scene") or "").strip()
        if not prompt:
            raise ProductionError(f"镜头 {shot.get('shot_id')} 缺少视频提示词")
        res = agent.run_sync(
            f"生成一个{dur}秒视频 {prompt}", duration_sec=dur, timeout=600.0,
        )
        src = (res or {}).get("video_path") or ""
        if res.get("status") != "success" or not os.path.isfile(src):
            raise ProductionError(f"OpenCut 生成镜头失败: {res.get('summary', '')}")
        out = os.path.join(work_dir, f"shot_{index:02d}.mp4")
        _run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", src,
            "-vf", (f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
                    f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2"),
            "-r", str(self.fps), "-t", str(dur),
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", out,
        ])
        return out


# ── 制作编排 ─────────────────────────────────────────────
class EpisodeProducer:
    """把一集 storyboard 渲染成完整 MP4。"""

    def __init__(self, width: int = 1920, height: int = 1080, fps: int = 25):
        self.width = width
        self.height = height
        self.fps = fps

    def backends(self) -> dict:
        return {"ffmpeg": FFmpegShotRenderer, "opencut": OpenCutShotRenderer}

    def render(self, project, number: int, backend: str = "ffmpeg",
               on_progress=None, cancel: threading.Event = None):
        ep = project.episode(number)
        if ep is None:
            raise ProductionError(f"没有第{number}集")
        shots = ep.shots
        if not shots:
            raise ProductionError(f"第{number}集还没有镜头，请先生成剧本与提示词")

        cls = self.backends().get(backend)
        if cls is None:
            raise ProductionError(f"未知渲染后端: {backend}")
        renderer = cls(self.width, self.height, self.fps)
        total = len(shots)

        def progress(state, shot, pct, msg):
            if on_progress:
                try:
                    on_progress(state, shot, total, pct, msg)
                except Exception:
                    pass

        pj = project.to_dict()
        progress("preparing", 0, 5, "正在准备渲染…")
        out_dir = os.path.join(_OUTPUT_ROOT, _slug(project.title))
        os.makedirs(out_dir, exist_ok=True)
        work_dir = os.path.join(
            tempfile.gettempdir(), f"drama_ep{number}_{int(time.time())}")
        os.makedirs(work_dir, exist_ok=True)

        clip_paths = []
        try:
            for i, s in enumerate(shots, start=1):
                if cancel is not None and cancel.is_set():
                    raise ProductionCancelled("制作已停止")
                progress("rendering", i, 10 + int((i - 1) / total * 75),
                         f"镜头 {i}/{total}")
                clip = renderer.render_shot(
                    s.to_dict(), i, total, number, pj, work_dir)
                clip_paths.append(clip)
            if cancel is not None and cancel.is_set():
                raise ProductionCancelled("制作已停止")
            progress("concatenating", total, 88, "正在拼接镜头…")
            output = os.path.join(out_dir, f"episode_{number:02d}.mp4")
            self._concat(clip_paths, output)
            progress("finalizing", total, 100, "导出完成")
            return {"status": "success", "output": output,
                    "duration": sum(int(s.duration or 5) for s in shots),
                    "shots": total, "backend": backend}
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _concat(self, clips: list, output: str):
        if len(clips) == 1:
            shutil.copyfile(clips[0], output)
            return
        lst = os.path.join(tempfile.gettempdir(),
                           f"drama_concat_{int(time.time())}.txt")
        with open(lst, "w", encoding="utf-8") as f:
            for c in clips:
                f.write(f"file '{c}'\n")
        try:
            _run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", lst,
                "-c", "copy", output,
            ])
        finally:
            try:
                os.remove(lst)
            except OSError:
                pass
