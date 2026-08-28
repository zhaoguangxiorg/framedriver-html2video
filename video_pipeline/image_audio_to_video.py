# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from video_pipeline.font_resolver import resolve_subtitle_font
from video_pipeline.config import VideoConfig, parse_resolution
from video_pipeline.subtitle_render import build_subtitle_filters

try:
    import imageio_ffmpeg
    _FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
    _FFPROBE_PATH = str(Path(_FFMPEG_PATH).parent / "ffprobe.exe")
    if not Path(_FFPROBE_PATH).exists():
        _FFPROBE_PATH = _FFMPEG_PATH
except ImportError:
    _FFMPEG_PATH = "ffmpeg"
    _FFPROBE_PATH = "ffprobe"


def _get_audio_duration(audio_path: str) -> float:
    try:
        result = subprocess.run(
            [
                _FFPROBE_PATH,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return 0.0


def _build_ken_burns_filter(duration: float, fps: int, width: int, height: int) -> str:
    zoom_start = 1.0
    zoom_end = 1.1
    x_start = "iw/2-(iw/zoom/2)"
    y_start = "ih/2-(ih/zoom/2)"
    return (
        f"zoompan=z='{zoom_start}+({zoom_end}-{zoom_start})*on/{int(duration * fps)}':"
        f"d={int(duration * fps)}:s={width}x{height}:fps={fps}:"
        f"x='{x_start}':y='{y_start}'"
    )


def _build_zoom_in_filter(duration: float, fps: int, width: int, height: int) -> str:
    zoom_start = 1.0
    zoom_end = 1.15
    return (
        f"zoompan=z='min({zoom_start}+({zoom_end}-{zoom_start})*on/{int(duration * fps)}, {zoom_end})':"
        f"d={int(duration * fps)}:s={width}x{height}:fps={fps}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    )


# 视频滤镜链长度超过该值时改用 -filter_script:v（从文件读滤镜串），规避命令行长度限制
_VF_SCRIPT_THRESHOLD = 8000


def image_audio_to_video(
    image_path: str,
    audio_path: str,
    output_path: str,
    config: VideoConfig,
    audio_duration: float = 0.0,
    subtitle_path: str | None = None,
    warnings: Optional[list] = None,
) -> Tuple[str, float]:
    """
    将一张图片和一段音频合成为一段视频。

    Args:
        image_path: 图片路径
        audio_path: 音频路径
        output_path: 输出视频路径
        config: 视频配置对象
        audio_duration: 音频时长（秒），大于 0 时直接使用，否则探测音频
        subtitle_path: SRT 字幕文件路径，None 表示不渲染字幕
        warnings: 可选列表引用，用于收集字幕相关提示（如 .ttc 多 face、
            字体未找到、无有效字幕等），由调用方传入并在后续处理

    Returns:
        (video_path, duration) 元组

    Raises:
        FileNotFoundError: 图片或音频文件不存在时
        RuntimeError: FFmpeg 调用失败时
    """
    image = Path(image_path).resolve()
    if not image.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    audio = Path(audio_path).resolve()
    if not audio.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    width, height = parse_resolution(config.resolution)
    fps = config.fps

    if audio_duration > 0:
        duration = audio_duration
    else:
        duration = _get_audio_duration(str(audio))
        if duration <= 0:
            raise RuntimeError("Could not determine audio duration")

    cmd = [_FFMPEG_PATH, "-y", "-v", "error"]

    cmd.extend(["-loop", "1", "-i", str(image)])
    cmd.extend(["-i", str(audio)])

    video_filters = []
    audio_filters = []

    if config.video_effect == "static":
        video_filters.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}")
    elif config.video_effect == "ken_burns":
        video_filters.append(
            f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=decrease,"
            f"pad={width * 2}:{height * 2}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
            + _build_ken_burns_filter(duration, fps, width, height)
        )
    elif config.video_effect == "zoom_in":
        video_filters.append(
            f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=decrease,"
            f"pad={width * 2}:{height * 2}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
            + _build_zoom_in_filter(duration, fps, width, height)
        )
    else:
        video_filters.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}")

    if config.fade_in_ms > 0 or config.fade_out_ms > 0:
        fade_parts = []
        if config.fade_in_ms > 0:
            fade_parts.append(f"fade=t=in:st=0:d={config.fade_in_ms / 1000.0}")
        if config.fade_out_ms > 0:
            fade_parts.append(f"fade=t=out:st={duration - config.fade_out_ms / 1000.0}:d={config.fade_out_ms / 1000.0}")
        video_filters.append(",".join(fade_parts))

    if subtitle_path is not None and config.enable_subtitles and (config.subtitle_font or config.subtitle_font_file):
        # 字体来源优先级：subtitle_font_file（直接指定，仅单 face）> subtitle_font（字体名解析）
        font_file, font_error = resolve_subtitle_font(config.subtitle_font, config.subtitle_font_file)
        if font_file is None:
            # 防御性跳过（预检已兜底失败场景），提示原因
            if warnings is not None:
                warnings.append(f"字幕字体不可用：{font_error or '未知错误'}，未渲染字幕")
        else:
            filter_chain, render_warnings = build_subtitle_filters(subtitle_path, config, font_file)
            if warnings is not None:
                warnings.extend(render_warnings)
            if filter_chain:
                video_filters.append(filter_chain)

    if config.fade_in_ms > 0 or config.fade_out_ms > 0:
        afade_parts = []
        if config.fade_in_ms > 0:
            afade_parts.append(f"afade=t=in:st=0:d={config.fade_in_ms / 1000.0}")
        if config.fade_out_ms > 0:
            afade_parts.append(f"afade=t=out:st={duration - config.fade_out_ms / 1000.0}:d={config.fade_out_ms / 1000.0}")
        audio_filters.append(",".join(afade_parts))

    vf_script_path = None
    vf_str = ",".join(video_filters)
    if vf_str:
        if len(vf_str) > _VF_SCRIPT_THRESHOLD:
            try:
                with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
                    f.write(vf_str)
                    vf_script_path = f.name
                cmd.extend(["-filter_script:v", vf_script_path])
            except OSError:
                cmd.extend(["-vf", vf_str])  # 写文件失败则回退 -vf
        else:
            cmd.extend(["-vf", vf_str])

    if audio_filters:
        cmd.extend(["-af", ",".join(audio_filters)])

    cmd.extend([
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(output),
    ])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown FFmpeg error"
            raise RuntimeError(f"FFmpeg failed: {error_msg}")
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"FFmpeg timed out after {e.timeout} seconds") from e
    except FileNotFoundError:
        raise RuntimeError("FFmpeg not found. Please install FFmpeg and ensure it is in PATH.")
    finally:
        if vf_script_path:
            try:
                os.unlink(vf_script_path)
            except OSError:
                pass

    actual_duration = _get_audio_duration(str(output))
    if actual_duration <= 0:
        actual_duration = duration

    return (str(output), actual_duration)
