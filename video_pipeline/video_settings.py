# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

import json
from pathlib import Path
from typing import Optional

from shared.file_utils import ensure_dir
from domain.entities.schemas import VideoConfig


_project_root: Optional[Path] = None


def _get_project_root() -> Path:
    global _project_root
    if _project_root is None:
        _project_root = Path(__file__).parent.parent
    return _project_root


def _get_video_settings_path() -> Path:
    return _get_project_root() / "config" / "video_settings.json"


def _get_voice_settings_path() -> Path:
    return _get_project_root() / "config" / "voice_settings.json"


def _load_voice_settings() -> dict:
    voice_path = _get_voice_settings_path()
    if not voice_path.exists():
        return {}
    with open(voice_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_aspect_ratios() -> dict:
    aspect_path = _get_project_root() / "config" / "video_aspect_ratios.json"
    if not aspect_path.exists():
        return {}
    with open(aspect_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _collect_preset_resolutions(aspect_ratios: dict) -> set:
    """收集所有预设分辨率，用于判断 resolution 是否为自定义值。"""
    resolutions = set()
    for ratio_info in aspect_ratios.values():
        preset = ratio_info.get("resolution")
        if preset:
            resolutions.add(preset)
    return resolutions


def apply_aspect_ratio(config: VideoConfig) -> VideoConfig:
    """根据 config.aspect_ratio 更新 config.resolution。

    规则：
    1. 如果当前 resolution 是某个预设比例的分辨率，则根据 aspect_ratio 更新
    2. 如果当前 resolution 不在预设列表中，视为用户自定义，保持不变
    """
    aspect_ratios = _load_aspect_ratios()
    if not aspect_ratios:
        return config

    preset_resolutions = _collect_preset_resolutions(aspect_ratios)
    current_resolution = config.resolution
    aspect_ratio = config.aspect_ratio

    # 如果当前 resolution 是预设值，则允许 aspect_ratio 覆盖它
    if current_resolution in preset_resolutions and aspect_ratio in aspect_ratios:
        new_resolution = aspect_ratios[aspect_ratio].get("resolution")
        if new_resolution:
            config.resolution = new_resolution

    return config


def load_video_settings() -> VideoConfig:
    video_path = _get_video_settings_path()
    if not video_path.exists():
        config = VideoConfig()
        save_video_settings(config)
        return config
    with open(video_path, "r", encoding="utf-8") as f:
        config_dict = json.load(f)
    voice_settings = _load_voice_settings()
    config_dict.update(voice_settings)
    config = VideoConfig(**config_dict)
    return apply_aspect_ratio(config)


def save_video_settings(config: VideoConfig) -> None:
    settings_path = _get_video_settings_path()
    ensure_dir(settings_path.parent)
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(config.model_dump(), f, ensure_ascii=False, indent=2)
