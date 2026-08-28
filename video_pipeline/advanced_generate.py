# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-19

import json
import time
from datetime import datetime
from typing import List

from shared.config import get_config
from domain.dal.project_store import ProjectStorage
from video_pipeline.config import VideoConfig
from video_pipeline.concat_videos import concat_videos
from video_pipeline.html_to_image import html_to_image
from video_pipeline.image_audio_to_video import image_audio_to_video
from video_pipeline.text_to_speech import text_to_speech


def generate_slide_video(
    project_id: str,
    slide_index: int,
    config: VideoConfig,
) -> dict:
    """对指定幻灯片执行 截图→TTS→合成 三步，输出 slide_XX/segment.mp4。

    Args:
        project_id: 项目ID
        slide_index: 幻灯片序号（从 1 开始）
        config: 视频配置对象

    Returns:
        {"segment_path": str, "audio_duration": float}
    """
    app_config = get_config()
    base_dir = app_config.output_base_dir

    warnings: list = []

    project_dir = ProjectStorage.get_project_dir(project_id, base_dir)

    slide_dir = project_dir / f"slide_{slide_index:02d}"
    slide_dir.mkdir(parents=True, exist_ok=True)

    image_path = str(slide_dir / "slide.png")
    audio_path = str(slide_dir / "narration.mp3")
    segment_path = str(slide_dir / "segment.mp4")

    html_path = str(slide_dir / "slide.html")

    narration = ProjectStorage.load_slide_narration(project_id, slide_index, base_dir)

    print(f"[Slide {slide_index}] Generating image from HTML...")
    html_to_image(html_path, image_path, config)

    print(f"[Slide {slide_index}] Generating speech from text...")
    print(f"[Slide {slide_index}] Narration text: {narration[:60]}...")
    audio_path, audio_duration, subtitle_path = text_to_speech(narration, audio_path, config)

    print(f"[Slide {slide_index}] Compositing video segment...")
    image_audio_to_video(image_path, audio_path, segment_path, config, audio_duration, subtitle_path, warnings=warnings)

    print(f"[Slide {slide_index}] Done: {segment_path}")

    return {
        "segment_path": segment_path,
        "audio_duration": audio_duration,
        "warnings": warnings,
    }


def get_slides_video_status(project_id: str) -> dict:
    """扫描所有 slide_XX/segment.mp4 和 final_video.mp4 的状态。

    Args:
        project_id: 项目ID

    Returns:
        {"slides": [{"slide_index": 1, "has_segment": true/false}, ...],
         "has_final": true/false,
         "total_segments": N,
         "total_slides": N}
    """
    app_config = get_config()
    base_dir = app_config.output_base_dir

    project_dir = ProjectStorage.get_project_dir(project_id, base_dir)
    slides_data = ProjectStorage.load_slides_data(project_id, base_dir)

    total_slides = len(slides_data)
    slides_status: List[dict] = []
    total_segments = 0

    for slide in slides_data:
        si = slide.slide_index
        slide_dir = project_dir / f"slide_{si:02d}"
        segment_file = slide_dir / "segment.mp4"
        has_segment = segment_file.exists()
        if has_segment:
            total_segments += 1
        slides_status.append({
            "slide_index": si,
            "has_segment": has_segment,
        })

    has_final = (project_dir / "final_video.mp4").exists()

    return {
        "slides": slides_status,
        "has_final": has_final,
        "total_segments": total_segments,
        "total_slides": total_slides,
    }


def concat_all_segments(project_id: str, config: VideoConfig) -> dict:
    """扫描所有 slide_XX/segment.mp4 文件，调用 concat_videos 合成 final_video.mp4。

    Args:
        project_id: 项目ID
        config: 视频配置对象

    Returns:
        {"final_video_path": str, "total_duration": float}
    """
    app_config = get_config()
    base_dir = app_config.output_base_dir

    project_dir = ProjectStorage.get_project_dir(project_id, base_dir)
    slides_data = ProjectStorage.load_slides_data(project_id, base_dir)

    segment_paths: List[str] = []
    missing: List[int] = []
    for slide in slides_data:
        si = slide.slide_index
        slide_dir = project_dir / f"slide_{si:02d}"
        segment_file = slide_dir / "segment.mp4"
        if segment_file.exists():
            segment_paths.append(str(segment_file))
        else:
            missing.append(si)

    # 严格校验：全部幻灯片都必须已生成 segment.mp4，缺一不可
    if missing:
        raise ValueError(
            "以下幻灯片尚未生成视频，请先生成单张视频后再合成：" + "、".join(str(si) for si in missing)
        )

    if not segment_paths:
        raise ValueError("No segment.mp4 files found for concatenation")

    final_video_path = str(project_dir / "final_video.mp4")

    print(f"\n[Concatenation] Joining {len(segment_paths)} video segments...")
    final_path, total_duration = concat_videos(segment_paths, final_video_path, config)

    print(f"[Concatenation] Final video: {final_path}")
    print(f"[Concatenation] Total duration: {total_duration:.2f}s")

    return {
        "final_video_path": final_path,
        "total_duration": total_duration,
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# 选段合成 — 勾选任意幻灯片子集合成片段视频（video_clips/）
# ---------------------------------------------------------------------------

def _clips_json(clips_dir) -> List[dict]:
    """读取 video_clips/video_clips.json，不存在或损坏时返回空列表。"""
    json_path = clips_dir / "video_clips.json"
    if not json_path.exists():
        return []
    try:
        records = json.loads(json_path.read_text(encoding="utf-8"))
        return records if isinstance(records, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def _append_clip_record(clips_dir, record: dict) -> None:
    """向 video_clips.json 追加一条记录（读改写，保留历史，不覆盖）。"""
    records = _clips_json(clips_dir)
    records.append(record)
    (clips_dir / "video_clips.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def concat_selected_segments(
    project_id: str,
    slide_indexes: List[int],
    config: VideoConfig,
) -> dict:
    """按选中的幻灯片序号列表合成片段视频。

    收集所选 slide_XX/segment.mp4 → 合成 video_clips/{时间戳}.mp4，
    并登记到 video_clips/video_clips.json。时间戳命名天然防重复，
    重复勾选同一组也会生成新文件而不覆盖。

    Args:
        project_id: 项目ID
        slide_indexes: 选中幻灯片序号（从 1 开始，自动去重排序）
        config: 视频配置对象

    Returns:
        {"file_name", "video_name"(如 "1-2-3"), "slides", "created_at",
         "total_duration", "clip_path"}
    """
    app_config = get_config()
    base_dir = app_config.output_base_dir
    project_dir = ProjectStorage.get_project_dir(project_id, base_dir)

    slide_indexes = sorted({int(si) for si in slide_indexes})

    # 严格校验：所选幻灯片必须都已生成 segment.mp4，缺一不可
    missing: List[int] = []
    segment_paths: List[str] = []
    for si in slide_indexes:
        segment_file = project_dir / f"slide_{si:02d}" / "segment.mp4"
        if segment_file.exists():
            segment_paths.append(str(segment_file))
        else:
            missing.append(si)

    if missing:
        raise ValueError(
            "以下幻灯片尚未生成视频，请先生成单张视频后再合成：" + "、".join(str(si) for si in missing)
        )
    if not segment_paths:
        raise ValueError("所选幻灯片中无已生成的视频片段，请先生成单张视频")

    clips_dir = project_dir / "video_clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    file_name = f"{int(time.time())}.mp4"
    clip_path = str(clips_dir / file_name)

    print(f"\n[Clip] Joining {len(segment_paths)} selected segments: {slide_indexes}...")
    _, total_duration = concat_videos(segment_paths, clip_path, config)
    print(f"[Clip] Saved: {clip_path}")

    record = {
        "file_name": file_name,
        "video_name": "-".join(str(si) for si in slide_indexes),
        "slides": slide_indexes,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _append_clip_record(clips_dir, record)

    return {
        **record,
        "total_duration": total_duration,
        "clip_path": clip_path,
    }


def list_video_clips(project_id: str) -> List[dict]:
    """返回项目全部片段记录（按生成顺序，最早的在前）。"""
    app_config = get_config()
    base_dir = app_config.output_base_dir
    project_dir = ProjectStorage.get_project_dir(project_id, base_dir)
    return _clips_json(project_dir / "video_clips")


def delete_video_clip(project_id: str, file_name: str) -> dict:
    """删除指定片段：移除 JSON 登记并删除磁盘文件。"""
    if not file_name or not file_name.endswith(".mp4") or "/" in file_name or "\\" in file_name:
        raise ValueError("非法文件名")

    app_config = get_config()
    base_dir = app_config.output_base_dir
    project_dir = ProjectStorage.get_project_dir(project_id, base_dir)
    clips_dir = project_dir / "video_clips"
    json_path = clips_dir / "video_clips.json"

    records = _clips_json(clips_dir)
    remaining = [r for r in records if r.get("file_name") != file_name]
    if len(remaining) == len(records):
        raise ValueError("片段记录不存在")
    json_path.write_text(
        json.dumps(remaining, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    clip_file = clips_dir / file_name
    if clip_file.exists():
        clip_file.unlink()

    return {"deleted": file_name}
