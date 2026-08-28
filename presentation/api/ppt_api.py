# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""PPT generation API (Tab 2) (technical layer).

Only routes, request models, and delegation to appservice.
"""
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from appservice import ppt_appservice as svc

router = APIRouter(prefix="/api/ppt", tags=["ppt"])


class SendMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户输入消息")
    project_id: str = Field(..., min_length=1, description="项目ID")
    model_code: Optional[str] = None


class InterventionRequest(BaseModel):
    intervention_id: str = Field(..., description="介入问题ID")
    answers: list = Field(..., description="用户答案列表")
    model_code: Optional[str] = None


@router.post("/{project_id}")
async def handle_ppt(project_id: str, body: SendMessageRequest):
    return await svc.handle_ppt(project_id, body.message, body.model_code)


@router.post("/{project_id}/stop", status_code=204)
def stop_agent(project_id: str):
    return svc.stop_agent(project_id)


@router.post("/{project_id}/intervention")
async def handle_intervention(project_id: str, body: InterventionRequest):
    return await svc.handle_intervention(
        project_id, body.intervention_id, body.answers, body.model_code
    )


@router.get("/{project_id}/agent-status")
async def get_agent_status(project_id: str):
    return await svc.get_agent_status(project_id)
