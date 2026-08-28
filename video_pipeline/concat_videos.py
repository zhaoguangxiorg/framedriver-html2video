# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple

from video_pipeline.config import VideoConfig

try:
    import imageio_ffmpeg
    _FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
    _FFPROBE_PATH = str(Path(_FFMPEG_PATH).parent / "ffprobe.exe")
    if not Path(_FFPROBE_PATH).exists():
        _FFPROBE_PATH = _FFMPEG_PATH
except ImportError:
    _FFMPEG_PATH = "ffmpeg"
    _FFPROBE_PATH = "ffprobe"


def _get_video_duration(video_path: str) -> float:
    try:
        result = subprocess.run(
            [
                _FFPROBE_PATH,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path,
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


def _concat_demuxer(video_paths: List[str], output_path: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        list_file = f.name
        for vp in video_paths:
            safe_path = Path(vp).resolve().as_posix().replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")

    try:
        cmd = [
            _FFMPEG_PATH, "-y", "-v", "error",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            output_path,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown FFmpeg error"
            raise RuntimeError(f"FFmpeg concat demuxer failed: {error_msg}")
    finally:
        try:
            Path(list_file).unlink()
        except OSError:
            pass


def _concat_xfade(
    video_paths: List[str],
    output_path: str,
    transition: str,
    transition_duration: float,
) -> None:
    if len(video_paths) < 2:
        if len(video_paths) == 1:
            cmd = [
                    _FFMPEG_PATH, "-y", "-v", "error",
                    "-i", video_paths[0],
                    "-c", "copy",
                    output_path,
                ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode != 0:
                error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown FFmpeg error"
                raise RuntimeError(f"FFmpeg copy failed: {error_msg}")
        return

    transition_name = "fade" if transition == "fade" else "dissolve"
    durations = []
    for vp in video_paths:
        d = _get_video_duration(vp)
        if d <= 0:
            raise RuntimeError(f"Could not determine duration of video: {vp}")
        durations.append(d)

    inputs = []
    for vp in video_paths:
        inputs.extend(["-i", vp])

    filter_parts = []
    current_video = "[0:v]"
    current_audio = "[0:a]"
    current_offset = durations[0] - transition_duration

    for i in range(1, len(video_paths)):
        next_video = f"[{i}:v]"
        next_audio = f"[{i}:a]"
        out_v = f"[v{i}]"
        out_a = f"[a{i}]"

        filter_parts.append(
            f"{current_video}{next_video}xfade=transition={transition_name}:"
            f"duration={transition_duration}:offset={current_offset}{out_v}"
        )
        filter_parts.append(
            f"{current_audio}{next_audio}acrossfade=d={transition_duration}:c1=tri:c2=tri{out_a}"
        )

        current_video = out_v
        current_audio = out_a
        current_offset += durations[i] - transition_duration

    filter_complex = ";".join(filter_parts)

    cmd = [
        _FFMPEG_PATH, "-y", "-v", "error",
    ] + inputs + [
        "-filter_complex", filter_complex,
        "-map", current_video,
        "-map", current_audio,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        output_path,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=1200,
    )
    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown FFmpeg error"
        raise RuntimeError(f"FFmpeg xfade concat failed: {error_msg}")


def concat_videos(
    video_paths: List[str],
    output_path: str,
    config: VideoConfig,
) -> Tuple[str, float]:
    """
    将多段视频拼接成最终视频，带转场效果。

    Args:
        video_paths: 视频路径列表（按顺序）
        output_path: 输出视频路径
        config: 视频配置对象

    Returns:
        (final_path, total_duration) 元组

    Raises:
        ValueError: 视频路径列表为空时
        FileNotFoundError: 视频文件不存在时
        RuntimeError: FFmpeg 调用失败时
    """
    if not video_paths:
        raise ValueError("video_paths cannot be empty")

    for vp in video_paths:
        if not Path(vp).exists():
            raise FileNotFoundError(f"Video file not found: {vp}")

    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        if config.transition == "none":
            _concat_demuxer(video_paths, str(output))
        elif config.transition in ("fade", "dissolve"):
            _concat_xfade(
                video_paths,
                str(output),
                config.transition,
                config.transition_duration,
            )
        else:
            _concat_demuxer(video_paths, str(output))
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"FFmpeg timed out after {e.timeout} seconds") from e
    except FileNotFoundError:
        raise RuntimeError("FFmpeg not found. Please install FFmpeg and ensure it is in PATH.")

    total_duration = _get_video_duration(str(output))

    return (str(output), total_duration)
