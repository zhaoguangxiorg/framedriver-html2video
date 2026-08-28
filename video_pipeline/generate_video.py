# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from shared.config import get_config
from domain.dal.project_store import ProjectStorage
from video_pipeline.video_settings import apply_aspect_ratio, load_video_settings
from video_pipeline.pipeline import run_pipeline


def generate_video(
    project_id: str,
    voice_persona: str = None,
    aspect_ratio: str = None,
    resolution: str = None,
    enable_subtitles: bool = None,
) -> dict:
    """执行视频生成流水线，生成最终视频。

    配置加载优先级：参数传入 > 用户项目配置 (video_config.json) > 系统默认配置 (config/*.json)

    Args:
        project_id: 项目ID
        voice_persona: 可选，语音人设ID，覆盖全局配置
        aspect_ratio: 可选，视频比例，覆盖全局配置
        resolution: 可选，自定义分辨率，最高优先级

    Returns:
        包含final_video_path、total_duration和total_slides的字典
    """
    config = get_config()
    base_dir = config.output_base_dir

    warnings: list = []

    project_dir = ProjectStorage.get_project_dir(project_id, base_dir)

    slides_data = ProjectStorage.load_slides_data(project_id, base_dir)
    slides_dict = [slide.model_dump() for slide in slides_data]

    # 1. 加载系统默认配置
    video_config = load_video_settings()

    # 2. 加载用户项目配置，合并到系统配置（用户配置优先）
    project_config = ProjectStorage.load_video_config(project_id, base_dir)
    if project_config:
        for key, value in project_config.items():
            if value is not None and hasattr(video_config, key):
                setattr(video_config, key, value)
        # 重新应用比例对应的分辨率
        video_config = apply_aspect_ratio(video_config)

    # 3. 参数传入覆盖（最高优先级）
    if voice_persona:
        video_config.voice_persona = voice_persona
    if aspect_ratio:
        video_config.aspect_ratio = aspect_ratio
        video_config = apply_aspect_ratio(video_config)
    if resolution:
        video_config.resolution = resolution
    if enable_subtitles is not None:
        video_config.enable_subtitles = enable_subtitles

    final_video_path, total_duration, total_slides = run_pipeline(
        project_dir=str(project_dir),
        slides_data=slides_dict,
        config=video_config,
        warnings=warnings,
    )

    return {
        "final_video_path": final_video_path,
        "total_duration": total_duration,
        "total_slides": total_slides,
        "warnings": warnings,
    }
