# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from typing import Optional
from pydantic import BaseModel


class SlideData(BaseModel):
    slide_index: int
    title: str
    html_path: Optional[str] = None


class VideoConfig(BaseModel):
    aspect_ratio: str = "16:9"
    resolution: str = "1920x1080"
    fps: int = 30
    voice_persona: str = "default"
    voice: str = "zh-CN-XiaoxiaoNeural"
    voice_rate: str = "+0%"
    voice_volume: str = "+0%"
    voice_pitch: str = "+0Hz"
    video_effect: str = "none"
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    transition: str = "none"
    transition_duration: float = 0.5
    device_scale_factor: float = 2.0
    enable_subtitles: bool = False
    subtitle_mode: str = "sentence"
    subtitle_font: str = ""
    subtitle_font_file: str = ""
    subtitle_font_size: int = 24
    subtitle_color: str = "white"
    subtitle_outline_color: str = "black"
    subtitle_outline_width: int = 2
    subtitle_position: str = "bottom"
    subtitle_margin: int = 40
