# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""Slide management API (technical layer).

Only routes, request models, and delegation to appservice.
"""
from typing import List

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from appservice import slide_appservice as svc

router = APIRouter(prefix="/api/slides", tags=["slides"])


class UpdateNarrationRequest(BaseModel):
    narration: str = Field(..., description="新的逐字稿内容")


@router.get("/{project_id}", response_model=List[dict])
def list_slides(project_id: str):
    return svc.list_slides(project_id)


@router.get("/{project_id}/{index}/html", response_class=HTMLResponse)
def get_slide_html(project_id: str, index: int):
    return svc.get_slide_html(project_id, index)


@router.get("/{project_id}/{index}/narration")
def get_narration(project_id: str, index: int):
    return svc.get_narration(project_id, index)


@router.put("/{project_id}/{index}/narration")
def update_narration(project_id: str, index: int, body: UpdateNarrationRequest):
    return svc.update_narration(project_id, index, body.narration)
