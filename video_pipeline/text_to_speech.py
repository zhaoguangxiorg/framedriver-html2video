# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

import asyncio
import re
import subprocess
import time
from pathlib import Path
from typing import Tuple, Optional

from video_pipeline.config import VideoConfig

try:
    import imageio_ffmpeg
    _FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    _FFMPEG_PATH = "ffmpeg"


def _get_audio_duration(audio_path: str) -> float:
    """使用 ffmpeg -i 解析音频时长（无需 ffprobe，环境内 ffmpeg 可直接读取文件头）。"""
    try:
        result = subprocess.run(
            [_FFMPEG_PATH, "-i", str(audio_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # ffmpeg -i 将 "Duration: HH:MM:SS.cc" 打印到 stderr
        match = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", result.stderr)
        if match:
            return (
                int(match.group(1)) * 3600
                + int(match.group(2)) * 60
                + float(match.group(3))
            )
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return 0.0


def _estimate_duration(text: str) -> float:
    """估算音频时长（中文约每秒4-5字）。"""
    char_count = len(text.strip())
    return max(1.0, char_count / 4.5)


def text_to_speech(
    text: str,
    output_path: str,
    config: VideoConfig,
) -> Tuple[str, float, Optional[str]]:
    """
    将文字合成为语音。

    Args:
        text: 要合成的文字
        output_path: 输出音频路径
        config: 视频配置对象

    Returns:
        (audio_path, duration, subtitle_path) 元组

    Raises:
        ValueError: 文字为空时
        RuntimeError: TTS 合成失败时
    """
    import edge_tts

    if not text or not text.strip():
        raise ValueError("Text cannot be empty")

    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    max_retries = 3
    base_delay = 1.0

    last_error = None
    for attempt in range(max_retries):
        try:
            subtitle_path = asyncio.run(_synthesize(text, str(output_path), config))
            break
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)
            else:
                raise RuntimeError(f"TTS synthesis failed after {max_retries} attempts: {e}") from last_error

    duration = _get_audio_duration(str(output_path))
    if duration <= 0:
        duration = _estimate_duration(text)

    return (str(output_path), duration, subtitle_path)


async def _synthesize(text: str, output_path: str, config: VideoConfig) -> Optional[str]:
    """异步执行 TTS 合成。

    Returns:
        启用字幕时返回 SRT 文件路径，否则返回 None
    """
    import edge_tts
    from video_pipeline.voice_personas import resolve_voice_settings

    persona_settings = resolve_voice_settings(config.voice_persona)
    if persona_settings:
        voice = persona_settings["voice"]
        voice_rate = persona_settings["voice_rate"]
        voice_volume = persona_settings["voice_volume"]
        voice_pitch = persona_settings["voice_pitch"]
    else:
        voice = config.voice
        voice_rate = config.voice_rate
        voice_volume = config.voice_volume
        voice_pitch = config.voice_pitch

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=voice_rate,
        volume=voice_volume,
        pitch=voice_pitch,
    )

    subtitle_path = None

    # 字幕需同时满足：启用字幕 且 已配置字体来源（字体名或字体文件路径，未配置则不生成字幕文件）
    if config.enable_subtitles and (config.subtitle_font or config.subtitle_font_file):
        from edge_tts import SubMaker

        sub_maker = SubMaker()
        event_type = "WordBoundary" if config.subtitle_mode == "word" else "SentenceBoundary"

        with open(output_path, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == event_type:
                    sub_maker.feed(chunk)

        subtitle_path = str(Path(output_path).with_suffix(".srt"))
        with open(subtitle_path, "w", encoding="utf-8") as f:
            f.write(sub_maker.get_srt())
    else:
        with open(output_path, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])

    return subtitle_path
