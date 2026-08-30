# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from pathlib import Path
from typing import Optional, Tuple, List

from shared.config import get_config
from domain.dal.project_store import ProjectStorage
from video_pipeline.config import VideoConfig
from video_pipeline.html_to_image import html_to_image
from video_pipeline.text_to_speech import text_to_speech
from video_pipeline.image_audio_to_video import image_audio_to_video
from video_pipeline.concat_videos import concat_videos


def run_pipeline(
    project_dir: str,
    slides_data: dict,
    config: VideoConfig,
    warnings: Optional[list] = None,
) -> Tuple[str, float, int]:
    """
    运行视频流水线总控，生成最终视频。

    Args:
        project_dir: 项目目录
        slides_data: 幻灯片数据（从 slides_data.json 读取）
        config: 视频配置对象
        warnings: 可选，字幕渲染提示收集列表（如 .ttc 多 face 等）

    Returns:
        (final_video_path, total_duration, total_slides) 元组

    Raises:
        ValueError: slides_data 为空时
        RuntimeError: 流水线某一步失败时
    """
    project_path = Path(project_dir).resolve()
    project_path.mkdir(parents=True, exist_ok=True)

    if not slides_data:
        raise ValueError("slides_data cannot be empty")

    slides = slides_data if isinstance(slides_data, list) else slides_data.get("slides", [])
    total_slides = len(slides)
    if total_slides == 0:
        raise ValueError("No slides found in slides_data")

    segment_paths: List[str] = []

    for idx, slide in enumerate(slides):
        slide_index = slide.get("slide_index", idx + 1)
        slide_dir = project_path / f"slide_{slide_index:02d}"
        slide_dir.mkdir(parents=True, exist_ok=True)

        image_path = str(slide_dir / "slide.png")
        audio_path = str(slide_dir / "narration.mp3")
        segment_path = str(slide_dir / "segment.mp4")

        html_path = slide.get("html_path")
        if html_path:
            # 有值：若为相对路径则拼上项目目录；绝对路径则直接用
            _p = Path(html_path)
            if not _p.is_absolute():
                html_path = str(project_path / _p)
        else:
            # 无值：默认项目目录下 slide_XX/slide.html
            html_path = str(slide_dir / "slide.html")

        _pid = Path(project_dir).name
        narration = ProjectStorage.load_slide_narration(_pid, slide_index, get_config().output_base_dir)

        print(f"[Slide {slide_index}/{total_slides}] Processing...")

        print(f"  -> Generating image from HTML...")
        try:
            html_to_image(html_path, image_path, config)
        except Exception as e:
            raise RuntimeError(f"Slide {slide_index}: html_to_image failed: {e}") from e

        print(f"  -> Generating speech from text...")
        try:
            audio_path, audio_duration, subtitle_path = text_to_speech(narration, audio_path, config)
        except Exception as e:
            raise RuntimeError(f"Slide {slide_index}: text_to_speech failed: {e}") from e

        print(f"  -> Compositing video segment...")
        try:
            image_audio_to_video(image_path, audio_path, segment_path, config, audio_duration, subtitle_path, warnings=warnings)
        except Exception as e:
            raise RuntimeError(f"Slide {slide_index}: image_audio_to_video failed: {e}") from e

        segment_paths.append(segment_path)
        print(f"  -> Done: {segment_path}")

    final_video_path = str(project_path / "final_video.mp4")

    print(f"\n[Concatenation] Joining {len(segment_paths)} video segments...")
    try:
        final_path, total_duration = concat_videos(segment_paths, final_video_path, config)
    except Exception as e:
        raise RuntimeError(f"concat_videos failed: {e}") from e

    print(f"\n[Pipeline] Final video: {final_path}")
    print(f"[Pipeline] Total duration: {total_duration:.2f}s")
    print(f"[Pipeline] Total slides: {total_slides}")

    return (final_path, total_duration, total_slides)
