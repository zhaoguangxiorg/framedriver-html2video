# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""Content creation API (Tab 1) (technical layer).

Only routes, request models, and delegation to appservice.
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional

from appservice import content_appservice as svc

router = APIRouter(prefix="/api/content", tags=["content"])


class SendMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户输入消息")
    project_id: str = Field(..., min_length=1, description="项目ID")
    model_code: Optional[str] = None


class SaveContentRequest(BaseModel):
    content: str = Field(..., description="完整的 Markdown 格式 PPT 内容")


@router.post("/{project_id}")
async def handle_content(project_id: str, body: SendMessageRequest):
    return await svc.handle_content(project_id, body.message, body.model_code)


@router.post("/{project_id}/stop", status_code=204)
def stop_content_agent(project_id: str):
    return svc.stop_content_agent(project_id)


@router.get("/{project_id}/content-md")
def get_content_md(project_id: str):
    return svc.get_content_md(project_id)


@router.put("/{project_id}/content-md")
def save_content_md(project_id: str, body: SaveContentRequest):
    return svc.save_content_md(project_id, body.content)
