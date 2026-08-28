# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

import json
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from shared.config import get_config
from domain.dal.project_store import ProjectStorage
from video_pipeline.video_config_cache import invalidate_video_config


def _get_resolution_from_ratio(aspect_ratio: str) -> str:
    ratios_path = Path(__file__).parent.parent.parent.parent / "config" / "video_aspect_ratios.json"
    if not ratios_path.exists():
        return "1920x1080"

    with open(ratios_path, "r", encoding="utf-8") as f:
        ratios = json.load(f)

    if aspect_ratio in ratios:
        return ratios[aspect_ratio].get("resolution", "1920x1080")

    return "1920x1080"


@tool
def update_video_config(
    config: RunnableConfig,
    aspect_ratio: Optional[str] = None,
    resolution: Optional[str] = None,
    fps: Optional[int] = None,
    video_effect: Optional[str] = None,
    fade_in_ms: Optional[int] = None,
    fade_out_ms: Optional[int] = None,
    transition: Optional[str] = None,
    transition_duration: Optional[float] = None,
    device_scale_factor: Optional[float] = None,
    enable_subtitles: Optional[bool] = None,
    subtitle_mode: Optional[str] = None,
    subtitle_font: Optional[str] = None,
    subtitle_font_size: Optional[int] = None,
    subtitle_color: Optional[str] = None,
    subtitle_outline_color: Optional[str] = None,
    subtitle_outline_width: Optional[int] = None,
    subtitle_position: Optional[str] = None,
    subtitle_margin: Optional[int] = None,
    voice_persona: Optional[str] = None,
    voice: Optional[str] = None,
    voice_rate: Optional[str] = None,
    voice_volume: Optional[str] = None,
    voice_pitch: Optional[str] = None,
) -> dict:
    """增量更新视频配置到项目目录。

    参数名与系统配置文件保持一致：video_settings.json 和 voice_settings.json。

    Args:
        aspect_ratio: 视频比例（16:9, 9:16, 4:3, 1:1, 21:9）
        resolution: 分辨率（如 1920x1080）
        fps: 帧率
        video_effect: 视频效果
        fade_in_ms: 淡入时长（毫秒）
        fade_out_ms: 淡出时长（毫秒）
        transition: 转场效果
        transition_duration: 转场时长（秒）
        device_scale_factor: 设备缩放因子
        enable_subtitles: 是否启用字幕
        subtitle_mode: 字幕模式
        subtitle_font: 字幕字体
        subtitle_font_size: 字幕字体大小
        subtitle_color: 字幕颜色
        subtitle_outline_color: 字幕描边颜色
        subtitle_outline_width: 字幕描边宽度
        subtitle_position: 字幕位置
        subtitle_margin: 字幕边距
        voice_persona: 语音角色
        voice: 语音类型
        voice_rate: 语速
        voice_volume: 音量
        voice_pitch: 音调

    Returns:
        包含project_id、message、file_path和updated_fields的字典
    """
    project_id = config["configurable"]["project_id"]
    config_obj = get_config()
    base_dir = config_obj.output_base_dir

    existing_config = ProjectStorage.load_video_config(project_id, base_dir)

    new_fields = {}
    params = locals()
    for key, value in params.items():
        if key not in ("config", "project_id", "config_obj", "base_dir", "existing_config", "new_fields", "params") and value is not None:
            new_fields[key] = value

    if "aspect_ratio" in new_fields and "resolution" not in new_fields:
        new_fields["resolution"] = _get_resolution_from_ratio(new_fields["aspect_ratio"])

    updated_config = {**existing_config, **new_fields}

    ProjectStorage.save_video_config(project_id, base_dir, updated_config)
    # 使视频配置缓存失效，下次读取拿到最新值
    invalidate_video_config(project_id)

    return {
        "project_id": project_id,
        "message": "视频配置已保存",
        "file_path": str((base_dir / "html_slides" / project_id / "video_config.json").resolve()),
        "updated_fields": list(new_fields.keys()),
    }
