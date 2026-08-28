# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-19

"""Video generation API (Tab 3) (technical layer).

Only routes, request models, and delegation to appservice.
"""
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from appservice import video_appservice as svc

router = APIRouter(prefix="/api/video", tags=["video"])


class StartVideoRequest(BaseModel):
    aspect_ratio: Optional[str] = Field(None, description='如 "16:9" / "9:16" / "4:3" / "1:1"')
    resolution: Optional[str] = Field(None, description='如 "1920x1080"')
    voice_persona: Optional[str] = Field(None, description="语音人设 ID")
    enable_subtitles: Optional[bool] = Field(None, description="是否启用字幕（需已配置字幕字体）")
    subtitle_color: Optional[str] = Field(None, description="字幕颜色（0xRRGGBB）")


class SlideGenerationRequest(BaseModel):
    """高级单张生成的可选设置（随请求保存到项目配置）。"""
    voice_persona: Optional[str] = Field(None, description="语音人设 ID")
    enable_subtitles: Optional[bool] = Field(None, description="是否启用字幕")
    subtitle_color: Optional[str] = Field(None, description="字幕颜色（0xRRGGBB）")


class ClipRequest(BaseModel):
    """选段合成：选中的幻灯片序号列表。"""
    slide_indexes: List[int] = Field(..., description="选中幻灯片序号（从 1 开始）")


@router.get("/voice-personas")
def get_voice_personas():
    return svc.get_voice_personas()


@router.get("/{project_id}/config")
def get_project_config(project_id: str):
    return svc.get_project_config(project_id)


@router.post("/{project_id}", status_code=202)
def start_generation(project_id: str, body: StartVideoRequest):
    return svc.start_generation(project_id, body.model_dump(exclude_none=True))


@router.get("/{project_id}/progress")
def get_progress(project_id: str):
    return svc.get_progress(project_id)


@router.get("/{project_id}/download")
def download(project_id: str):
    return svc.download(project_id)


@router.post("/{project_id}/slide/{slide_index}", status_code=202)
def start_slide_generation(
    project_id: str,
    slide_index: int,
    body: Optional[SlideGenerationRequest] = None,
):
    settings = body.model_dump(exclude_none=True) if body else {}
    return svc.start_slide_generation(project_id, slide_index, settings)


@router.get("/{project_id}/slides/status")
def get_slides_status(project_id: str):
    return svc.get_slides_status(project_id)


@router.post("/{project_id}/concat", status_code=202)
def start_concat(project_id: str):
    return svc.start_concat(project_id)


@router.get("/{project_id}/slide/{slide_index}/download")
def download_slide(project_id: str, slide_index: int):
    return svc.download_slide(project_id, slide_index)


@router.post("/{project_id}/clips", status_code=202)
def start_clip_concat(project_id: str, body: ClipRequest):
    return svc.start_clip_concat(project_id, body.slide_indexes)


@router.get("/{project_id}/clips")
def list_clips(project_id: str):
    return svc.list_clips(project_id)


@router.delete("/{project_id}/clips/{file_name}")
def delete_clip(project_id: str, file_name: str):
    return svc.delete_clip(project_id, file_name)


@router.get("/{project_id}/clips/{file_name}/download")
def download_clip(project_id: str, file_name: str):
    return svc.download_clip(project_id, file_name)
