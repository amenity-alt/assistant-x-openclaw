#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Short Drama — Phase 2/3 视频渲染流水线（storyboard → 时间线 → 成片）。

后端：
  - ffmpeg（默认，离线可用）：JARVIS HUD 场景卡 → 多样 Ken Burns 运镜 →
    macOS say 角色配音 → 淡入淡出转场 + BGM 氛围音 → 片头/片尾卡 →
    拼接导出 ~/Movies/JarvisDramas/<剧名>/episode_XX.mp4 + 剧集海报 poster.jpg
  - opencut：每镜头调用 video_agent（OpenCut AI 视频）生成素材后统一转码拼接，
    需要 OpenCut 已配置 DeepSeek/Gemini key；失败会明确报错。

进度：render() 内通过 on_progress(state, shot, total, progress, message) 回调，
cancel（threading.Event）在镜头/步骤间检查，支持语音“停止制作”。
"""

import json
import os
import re
import shutil
import subprocess
import zipfile
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


_VOICE_CACHE = None


def _available_voices() -> set:
    """macOS say 可用音色名（首次调用缓存）。"""
    global _VOICE_CACHE
    if _VOICE_CACHE is None:
        try:
            r = subprocess.run(["say", "-v", "?"], capture_output=True,
                               text=True, timeout=10)
            _VOICE_CACHE = {ln.split()[0] for ln in r.stdout.splitlines()
                            if ln.strip()}
        except Exception:
            _VOICE_CACHE = set()
    return _VOICE_CACHE


# 声线关键词 → (中文音色(男/女), 英文音色(男/女), 语速偏移)
_PERSONA_VOICES = [
    (("苍老", "年迈", "白发"), ("Grandpa", "Grandma"), ("Fred", "Grandma"), -25),
    (("慈祥", "和蔼"), ("Grandpa", "Grandma"), ("Fred", "Grandma"), -10),
    (("小孩", "幼年", "年幼", "天真"), ("Tingting", "Tingting"), ("Alice", "Alice"), +35),
    (("沉稳", "冷静", "理智"), ("Reed", "Tingting"), ("Alex", "Samantha"), -12),
    (("冷酷", "高冷", "寡言", "冷漠"), ("Reed", "Tingting"), ("Daniel", "Samantha"), -15),
    (("霸气", "强势", "威严"), ("Reed", "Tingting"), ("Daniel", "Samantha"), -10),
    (("阴险", "狡诈", "反派"), ("Reed", "Tingting"), ("Daniel", "Samantha"), -10),
    (("低沉", "沙哑"), ("Reed", "Tingting"), ("Daniel", "Samantha"), -15),
    (("甜美", "温柔", "温婉"), ("Tingting", "Tingting"), ("Samantha", "Samantha"), +8),
    (("活泼", "调皮", "可爱", "俏皮"), ("Tingting", "Tingting"), ("Alice", "Samantha"), +15),
    (("激动", "愤怒", "激昂"), ("Reed", "Tingting"), ("Alex", "Samantha"), +12),
]


def _voice_plan(character: str, characters: list, shot_voice: str, text: str) -> tuple:
    """返回 (macOS 音色, 语速)。

    优先级：角色显式音色名 > 台词声线标注/性格关键词 > 性别+语言默认。
    """
    zh = _is_zh(text)
    gender, personality, explicit = "", "", ""
    for c in characters:
        if c.get("name") == character:
            gender = c.get("gender", "")
            personality = c.get("personality", "")
            explicit = (c.get("voice") or "").strip()
            break
    if explicit:
        name = explicit.split()[0]
        if name in _available_voices():
            return name, 190
    for src in (shot_voice, personality):
        for keys, zh_pair, en_pair, delta in _PERSONA_VOICES:
            if any(k in src for k in keys):
                pair = zh_pair if zh else en_pair
                voice = pair[0] if gender == "男" else pair[1]
                return voice, max(130, min(260, 190 + delta))
    if zh:
        return ("Reed" if gender == "男" else "Tingting"), 190
    return ("Alex" if gender == "男" else "Samantha"), 190


def _voice_for(character: str, characters: list, text: str) -> str:
    """兼容旧接口：仅返回音色（默认语速）。"""
    return _voice_plan(character, characters, "", text)[0]


# ── 场景卡 / 片头片尾 / 海报（PIL，JARVIS HUD 风格）────────
def _hud_background(width: int, height: int, accent: tuple) -> Image.Image:
    img = Image.new("RGB", (width, height), (6, 11, 22))
    d = ImageDraw.Draw(img)
    for y in range(height):
        t = y / height
        d.line([(0, y), (width, y)],
               fill=(int(6 + 10 * t), int(11 + 22 * t), int(22 + 34 * t)))
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy = width // 2, int(height * 0.42)
    for i in range(220, 0, -8):
        a = int(26 * (1 - i / 220))
        gd.ellipse([cx - i, cy - i, cx + i, cy + i],
                   outline=(accent[0], accent[1], accent[2], a), width=2)
    return Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")


def _hud_frame(d: ImageDraw, width: int, height: int, accent: tuple):
    L = 46
    for (x0, y0, dx, dy) in ((24, 24, 1, 1), (width - 24, 24, -1, 1),
                             (24, height - 24, 1, -1), (width - 24, height - 24, -1, -1)):
        d.line([(x0, y0), (x0 + dx * L, y0)], fill=accent, width=4)
        d.line([(x0, y0), (x0, y0 + dy * L)], fill=accent, width=4)
    d.rectangle([16, 16, width - 16, height - 16],
                outline=(accent[0], accent[1], accent[2], 120), width=1)


def _scene_card(shot: dict, index: int, total: int, episode: int,
                project: dict, width: int = 1920, height: int = 1080) -> str:
    acc = _ACCENTS[(index - 1) % len(_ACCENTS)]
    img = _hud_background(width, height, acc)
    d = ImageDraw.Draw(img)
    _hud_frame(d, width, height, acc)

    f_small = _font(30)
    f_mid = _font(40)
    f_title = _font(88)
    f_dlg = _font(46)

    title = project.get("title") or "UNTITLED"
    d.text((64, 56), f"JARVIS DRAMA · {title[:14]}", font=_font(30),
           fill=(0x8C, 0xC1, 0xFA))
    d.text((width - 420, 56), f"EP {episode:02d} · SHOT {index:02d}/{total:02d}",
           font=_font(30), fill=(0x8C, 0xC1, 0xFA))

    scene = (shot.get("scene") or "未命名场景").strip()
    d.rectangle([64, 300, 76, 396], fill=(acc[0], acc[1], acc[2]))
    for i, line in enumerate(_wrap(scene, 16)[:2]):
        d.text((104, 300 + i * 100), line, font=f_title, fill=(0xE8, 0xF4, 0xFF))
    char = (shot.get("character") or "").strip()
    if char:
        cw = len(char) * 34 + 40
        d.rounded_rectangle([104, 520, 104 + cw, 584], radius=32,
                            fill=(acc[0], acc[1], acc[2], 40),
                            outline=(acc[0], acc[1], acc[2], 160), width=2)
        d.text((124, 534), char, font=_font(36), fill=(acc[0], acc[1], acc[2]))

    action = (shot.get("action") or "").strip()
    ay = 660
    for line in _wrap(action, 34)[:3]:
        d.text((64, ay), line, font=f_mid, fill=(0xC9, 0xDE, 0xF2))
        ay += 54

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

    d.text((width - 260, height - 320), f"{shot.get('duration', 5)}s",
           font=_font(56), fill=(acc[0], acc[1], acc[2]))

    out = tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir="/tmp")
    out.close()
    img.save(out.name)
    return out.name


def _title_card(project: dict, episode: int, total: int, mode: str,
                width: int = 1920, height: int = 1080) -> str:
    """片头（剧名卡）/ 片尾（TO BE CONTINUED / THE END）卡。"""
    acc = _ACCENTS[0]
    img = _hud_background(width, height, acc)
    d = ImageDraw.Draw(img)
    _hud_frame(d, width, height, acc)

    if mode == "open":
        d.text((64, 60), "JARVIS DRAMA PRESENTS", font=_font(34),
               fill=(0x46, 0xE0, 0xA8))
        title = (project.get("title") or "UNTITLED").strip()
        for i, line in enumerate(_wrap(title, 10)[:2]):
            d.text((width // 2 - len(line) * 46, 430 + i * 130), line,
                   font=_font(120), fill=(0xE8, 0xF4, 0xFF))
        d.text((width // 2 - 150, 760),
               f"EPISODE {episode:02d} / {total:02d}", font=_font(48),
               fill=(0x8C, 0xC1, 0xFA))
        d.text((width // 2 - 260, height - 220),
               project.get("genre") or "SHORT DRAMA", font=_font(36),
               fill=(0x5B, 0x8D, 0xB8))
    else:
        label = "THE END" if episode >= total else "TO BE CONTINUED"
        d.text((width // 2 - len(label) * 36, 460), label, font=_font(96),
               fill=(0xE8, 0xF4, 0xFF))
        d.text((width // 2 - 160, height - 240), f"EPISODE {episode:02d}",
               font=_font(44), fill=(0x8C, 0xC1, 0xFA))
        d.text((width // 2 - 300, height - 170),
               "JARVIS DRAMA", font=_font(30), fill=(0x46, 0xE0, 0xA8))

    out = tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir="/tmp")
    out.close()
    img.save(out.name)
    return out.name


def _poster(project: dict, episode: int, output_path: str):
    """剧集海报（竖版 1280x1600）。"""
    acc = _ACCENTS[(episode - 1) % len(_ACCENTS)]
    w, h = 1280, 1600
    img = _hud_background(w, h, acc)
    d = ImageDraw.Draw(img)
    _hud_frame(d, w, h, acc)
    title = (project.get("title") or "UNTITLED").strip()
    for i, line in enumerate(_wrap(title, 8)[:2]):
        d.text((w // 2 - len(line) * 52, 380 + i * 140), line,
               font=_font(120), fill=(0xE8, 0xF4, 0xFF))
    d.text((w // 2 - 130, 700), f"EPISODE {episode:02d}", font=_font(54),
           fill=(acc[0], acc[1], acc[2]))
    chars = " · ".join(c.get("name", "") for c in project.get("characters", [])[:4])
    if chars:
        d.text((w // 2 - len(chars) * 20, 900), chars, font=_font(40),
               fill=(0xC9, 0xDE, 0xF2))
    d.text((w // 2 - 220, 1380), "JARVIS DRAMA STUDIO", font=_font(34),
           fill=(0x5B, 0x8D, 0xB8))
    img.save(output_path)


# ── ffmpeg 封装 ──────────────────────────────────────────
def _run(cmd: list):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except FileNotFoundError as e:
        raise ProductionError("未找到 ffmpeg，请先安装：brew install ffmpeg") from e
    if r.returncode != 0:
        raise ProductionError("ffmpeg 失败: " + (r.stderr or r.stdout or "")[-400:])
    return r


def _probe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return float(r.stdout.strip() or 0)
    except Exception:
        return 0.0


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


def _bgm_wav(duration: float) -> str:
    """棕色噪声低通 + 音量压低 + 首尾淡入淡出 → 环境氛围 BGM。"""
    out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir="/tmp")
    out.close()
    fade_out = max(1.0, duration - 2.0)
    _run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"anoisesrc=color=brown:amplitude=0.35:duration={duration:.2f}",
        "-af", (f"lowpass=f=380,volume=0.10,"
                f"afade=t=in:d=1.5,afade=t=out:st={fade_out:.2f}:d=1.5"),
        "-ar", "44100", "-ac", "2", out.name,
    ])
    return out.name


# ── 字幕（SRT 导出 + ASS 烧录）─────────────────────────
def _subtitle_events(shots: list, open_dur: float = 3.0, fade: float = 0.5):
    """返回 [(start, end, text)]，按片头+转场偏移计算。"""
    events = []
    t = open_dur
    n = len(shots)
    for i, sh in enumerate(shots, start=1):
        d = max(2.0, min(float(sh.get("duration") or 5), 10.0))
        text = (sh.get("dialogue") or "").strip()
        if text:
            visible_end = t + d - fade if i < n else t + d
            events.append((t + 0.3, max(t + 0.3, visible_end - 0.4), text))
        t = t + d - (fade if i < n else 0)
    return events


def _ts(sec: float) -> str:
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_srt(events: list, path: str):
    lines = []
    for i, (st, en, text) in enumerate(events, start=1):
        lines += [str(i), f"{_ts(st)} --> {_ts(en)}", text, ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_ass(events: list, path: str):
    body = "\n".join(
        f"Dialogue: 0,{_ts(st)},{_ts(en)},Default,,0,0,0,,{text}"
        for st, en, text in events
    )
    ass = (
        "[Script Info]\n"
        "PlayResX: 1920\nPlayResY: 1080\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Heiti SC,52,&H00FFFFFF,&H000000FF,&H00000000,&H96000000,"
        "0,0,0,0,100,100,0,0,1,3,1,2,40,40,70,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        + body + "\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(ass)


def _burn_subtitles(video: str, ass_path: str):
    tmp = video + ".sub.mp4"
    _run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", video,
        "-vf", f"ass={ass_path}",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", tmp,
    ])
    os.replace(tmp, video)


class FFmpegShotRenderer:
    """默认离线后端：场景卡 + 多样 Ken Burns 运镜 + say 配音。"""

    name = "ffmpeg"

    def __init__(self, width: int = 1920, height: int = 1080, fps: int = 25):
        self.width = width
        self.height = height
        self.fps = fps

    def _zoompan_vf(self, frames: int, motion: int) -> str:
        w, h = self.width, self.height
        s = f"{w}x{h}"
        center_x, center_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
        if motion == 1:      # 拉远
            z = "max(1.18-0.0009*on,1.0)"
            x, y = center_x, center_y
        elif motion == 2:    # 左→右 平移
            z = "1.12"
            x = "(iw-iw/zoom)*(on/(d-1))"
            y = center_y
        elif motion == 3:    # 右→左 平移
            z = "1.12"
            x = "(iw-iw/zoom)*(1-on/(d-1))"
            y = center_y
        elif motion == 4:    # 上→下 平移
            z = "1.12"
            x, y = center_x, "(ih-ih/zoom)*(on/(d-1))"
        elif motion == 5:    # 下→上 平移
            z = "1.12"
            x, y = center_x, "(ih-ih/zoom)*(1-on/(d-1))"
        else:                # 推近
            z = "min(zoom+0.0009,1.18)"
            x, y = center_x, center_y
        return (
            f"scale={w * 2}:-1,"
            f"zoompan=z='{z}':d={frames}:x='{x}':y='{y}':s={s}:fps={self.fps}"
        )

    def render_card(self, card_path: str, duration: float, motion: int,
                    work_dir: str, shot_id: str, dialogue: str = "",
                    voice: str = "", rate: int = 190) -> str:
        dur = max(2.0, min(duration, 10.0))
        frames = int(dur * self.fps)
        silent = os.path.join(work_dir, f"{shot_id}_v.mp4")
        _run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", card_path,
            "-filter_complex", self._zoompan_vf(frames, motion),
            "-t", f"{dur:.2f}", "-r", str(self.fps),
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-an", silent,
        ])
        out = os.path.join(work_dir, f"{shot_id}.mp4")
        if dialogue:
            wav = _dialogue_wav(dialogue, voice, rate)
            if wav:
                _run([
                    "ffmpeg", "-y", "-loglevel", "error", "-i", silent, "-i", wav,
                    "-filter_complex", "[1:a]adelay=300|300,apad[a]",
                    "-map", "0:v", "-map", "[a]", "-t", f"{dur:.2f}",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                    "-ar", "44100", "-ac", "2", out,
                ])
                return out
        _run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", silent,
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", f"{dur:.2f}", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-shortest", out,
        ])
        return out

    def render_shot(self, shot: dict, index: int, total: int, episode: int,
                    project: dict, work_dir: str) -> str:
        dur = max(2, min(int(shot.get("duration") or 5), 10))
        card = _scene_card(shot, index, total, episode, project,
                           self.width, self.height)
        try:
            char = (shot.get("character") or "").strip()
            dialogue = (shot.get("dialogue") or "").strip()
            voice, rate = _voice_plan(char, project.get("characters", []),
                                      shot.get("voice") or "", dialogue)
            return self.render_card(card, dur, (index - 1) % 6, work_dir,
                                    f"shot_{index:02d}", dialogue, voice, rate)
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
    """把一集 storyboard 渲染成完整 MP4（含片头片尾/转场/BGM/海报）。"""

    def __init__(self, width: int = 1920, height: int = 1080, fps: int = 25,
                 crossfade: float = 0.5, bgm: bool = True):
        self.width = width
        self.height = height
        self.fps = fps
        self.crossfade = crossfade
        self.bgm = bgm

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
        pj = project.to_dict()

        def progress(state, shot, pct, msg):
            if on_progress:
                try:
                    on_progress(state, shot, total, pct, msg)
                except Exception:
                    pass

        progress("preparing", 0, 5, "正在准备渲染…")
        out_dir = os.path.join(_OUTPUT_ROOT, _slug(project.title))
        os.makedirs(out_dir, exist_ok=True)
        work_dir = os.path.join(
            tempfile.gettempdir(), f"drama_ep{number}_{int(time.time())}")
        os.makedirs(work_dir, exist_ok=True)

        clips = []
        try:
            use_polish = backend == "ffmpeg"
            # 片头卡
            if use_polish:
                open_card = _title_card(pj, number, project.total_episodes, "open",
                                        self.width, self.height)
                try:
                    clips.append(renderer.render_card(
                        open_card, 3.0, 0, work_dir, "opening"))
                finally:
                    try:
                        os.remove(open_card)
                    except OSError:
                        pass
            # 正片镜头
            for i, s in enumerate(shots, start=1):
                if cancel is not None and cancel.is_set():
                    raise ProductionCancelled("制作已停止")
                progress("rendering", i, 10 + int((i - 1) / total * 75),
                         f"镜头 {i}/{total}")
                clips.append(renderer.render_shot(
                    s.to_dict(), i, total, number, pj, work_dir))
            # 片尾卡
            if use_polish:
                if cancel is not None and cancel.is_set():
                    raise ProductionCancelled("制作已停止")
                end_card = _title_card(pj, number, project.total_episodes, "end",
                                       self.width, self.height)
                try:
                    clips.append(renderer.render_card(
                        end_card, 3.0, 0, work_dir, "ending"))
                finally:
                    try:
                        os.remove(end_card)
                    except OSError:
                        pass

            if cancel is not None and cancel.is_set():
                raise ProductionCancelled("制作已停止")
            progress("concatenating", total, 88, "正在拼接镜头…")
            output = os.path.join(out_dir, f"episode_{number:02d}.mp4")
            if use_polish and self.crossfade > 0 and len(clips) > 1:
                self._crossfade(clips, output, self.crossfade)
            else:
                self._concat(clips, output)
            # 字幕：SRT 导出 + ASS 烧录（仅 ffmpeg 后端）
            subtitles_path = ""
            if use_polish:
                progress("subtitles", total, 91, "正在生成字幕…")
                events = _subtitle_events(
                    [s.to_dict() for s in shots], open_dur=3.0,
                    fade=self.crossfade if self.crossfade > 0 else 0.0)
                srt_path = os.path.join(out_dir, f"episode_{number:02d}.srt")
                _write_srt(events, srt_path)
                subtitles_path = srt_path
                if events:
                    ass_path = os.path.join(work_dir, "subs.ass")
                    _write_ass(events, ass_path)
                    progress("subtitles", total, 93, "正在烧录字幕…")
                    _burn_subtitles(output, ass_path)
            # BGM 氛围音
            if use_polish and self.bgm:
                progress("mixing", total, 95, "正在混入氛围音…")
                self._mix_bgm(output)
            # 成片目录打包
            progress("packaging", total, 97, "正在打包成片目录…")
            poster_path = os.path.join(out_dir, "poster.jpg")
            _poster(pj, number, poster_path)
            self._package(project, number, output, srt_path if use_polish else "",
                          poster_path, out_dir)
            progress("finalizing", total, 100, "导出完成")
            return {
                "status": "success", "output": output,
                "poster": poster_path,
                "subtitles": subtitles_path,
                "duration": int(_probe_duration(output) or 0),
                "shots": total, "backend": backend,
            }
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

    def _crossfade(self, clips: list, output: str, fade: float):
        """多镜头淡入淡出（视/音频双 xfade 链，需重编码）。"""
        durs = [_probe_duration(c) for c in clips]
        inputs = []
        for c in clips:
            inputs += ["-i", c]
        # 转场 t（1-based）的起点 = Σ_{i<=t} d_i - t*fade（输出时间线）
        offsets = []
        prefix = durs[0]
        for t in range(1, len(clips)):
            offsets.append(round(prefix - t * fade, 3))
            prefix += durs[t]
        # 视频链
        v_expr = f"[0:v][1:v]xfade=transition=fade:duration={fade}:offset={offsets[0]}[v1]"
        for k in range(2, len(clips)):
            v_expr += f";[v{k - 1}][{k}:v]xfade=transition=fade:duration={fade}:offset={offsets[k - 1]}[v{k}]"
        # 音频链
        a_expr = f"[0:a][1:a]acrossfade=d={fade}[a1]"
        for k in range(2, len(clips)):
            a_expr += f";[a{k - 1}][{k}:a]acrossfade=d={fade}[a{k}]"
        last = len(clips) - 1
        fc = f"{v_expr};{a_expr}"
        _run([
            "ffmpeg", "-y", "-loglevel", "error", *inputs,
            "-filter_complex", fc,
            "-map", f"[v{last}]", "-map", f"[a{last}]",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart", output,
        ])

    def _package(self, project, number: int, video: str, srt: str,
                 poster: str, out_dir: str):
        """成片目录：剧本副本 + 工程快照 + 全剧索引。"""
        ep = project.episode(number)
        # 剧本副本
        if ep and ep.script:
            try:
                with open(os.path.join(out_dir, f"episode_{number:02d}.md"),
                          "w", encoding="utf-8") as f:
                    f.write(ep.script)
            except OSError:
                pass
        # 工程快照（紧凑）
        try:
            with open(os.path.join(out_dir, "project.json"),
                      "w", encoding="utf-8") as f:
                json.dump(self._snapshot(project), f,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
        # 全剧索引
        line = (
            f"EP {number:02d} | {ep.title if ep else ''} | "
            f"{_probe_duration(video):.1f}s | {os.path.basename(video)}"
            + (f" | {os.path.basename(srt)}" if srt else "")
            + (f" | {os.path.basename(poster)}" if poster else "")
        )
        idx_path = os.path.join(out_dir, "SERIES_INDEX.txt")
        try:
            lines = []
            if os.path.isfile(idx_path):
                with open(idx_path, "r", encoding="utf-8") as f:
                    lines = [l for l in f.read().splitlines() if l.strip()]
            lines = [l for l in lines if not l.startswith(f"EP {number:02d} |")]
            lines.append(line)
            with open(idx_path, "w", encoding="utf-8") as f:
                f.write("\n".join(sorted(lines)) + "\n")
        except OSError:
            pass

    @staticmethod
    def _snapshot(project) -> dict:
        d = project.to_dict()
        d.pop("history", None)
        for e in d.get("episodes", []):
            e.pop("script", None)
            e.pop("shots", None)
        return d

    def _mix_bgm(self, path: str):
        dur = _probe_duration(path)
        if dur <= 0:
            return
        bgm = _bgm_wav(dur)
        tmp = path + ".bgm.mp4"
        try:
            _run([
                "ffmpeg", "-y", "-loglevel", "error", "-i", path, "-i", bgm,
                "-filter_complex",
                "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=3[a]",
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", tmp,
            ])
            os.replace(tmp, path)
        finally:
            try:
                os.remove(bgm)
            except OSError:
                pass


# ── 一键打包发布（全剧 zip）────────────────────────────
_RELEASE_ROOT = os.path.expanduser("~/Movies/JarvisReleases")


def _release_manifest(project, src: str, files: list) -> str:
    lines = [
        "JARVIS SHORT DRAMA RELEASE",
        "==========================",
        f"Title      : {project.title}",
        f"Genre      : {project.genre or '-'}",
        f"Episodes   : {project.total_episodes}",
        f"Backend    : ffmpeg",
        "",
        "FILES",
        "-----",
    ]
    total = 0
    for name in files:
        sz = os.path.getsize(os.path.join(src, name))
        total += sz
        lines.append(f"{name:32s} {sz:>10,} bytes")
    lines.append(f"{'TOTAL':32s} {total:>10,} bytes")
    lines.append("")
    lines.append(f"Created    : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    return "\n".join(lines) + "\n"


def publish_series(project, on_progress=None) -> dict:
    """一键打包发布：全剧成片目录 → 单个 zip（含 RELEASE_INFO.txt 清单）。

    发布包递增版本号（<剧名>_v1.zip / v2 / ...），输出到 ~/Movies/JarvisReleases/。
    """
    src = os.path.join(_OUTPUT_ROOT, _slug(project.title))
    if not os.path.isdir(src):
        raise ProductionError("还没有成片目录，请先制作至少一集。")
    files = [f for f in sorted(os.listdir(src))
             if os.path.isfile(os.path.join(src, f))]
    vids = [f for f in files if f.lower().endswith(".mp4")]
    if not vids:
        raise ProductionError("成片目录里没有 MP4 成片，请先制作。")
    os.makedirs(_RELEASE_ROOT, exist_ok=True)
    version = 1
    while os.path.exists(os.path.join(_RELEASE_ROOT, f"{_slug(project.title)}_v{version}.zip")):
        version += 1
    zip_path = os.path.join(_RELEASE_ROOT, f"{_slug(project.title)}_v{version}.zip")

    def report(state, pct, msg):
        if on_progress:
            try:
                on_progress(state, len(vids), pct, msg)
            except Exception:
                pass

    report("publish", 5, "正在生成发布清单…")
    manifest = _release_manifest(project, src, files)
    mf = tempfile.NamedTemporaryFile(suffix=".txt", delete=False,
                                     mode="w", encoding="utf-8",
                                     dir=tempfile.gettempdir())
    mf.write(manifest)
    mf.close()
    total = len(files) + 1
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(mf.name, "RELEASE_INFO.txt")
            for i, name in enumerate(files, start=2):
                report("publish", 10 + int((i - 1) / total * 85), f"正在压缩 {name}…")
                zf.write(os.path.join(src, name), name)
    finally:
        try:
            os.remove(mf.name)
        except OSError:
            pass
    report("publish", 100, "发布包已生成")
    return {"status": "success", "zip_path": zip_path,
            "episodes": len(vids), "bytes": os.path.getsize(zip_path),
            "version": version}
