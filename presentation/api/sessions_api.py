# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""Session management API (technical layer).

Only routes, request models, and delegation to appservice.
"""
from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from appservice import session_appservice as svc

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
messages_router = APIRouter(prefix="/api/messages", tags=["messages"])


class CreateSessionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="PPT 主题")


@router.get("", response_model=List[dict])
def list_sessions():
    return svc.list_sessions()


@router.post("", status_code=201)
def create_session(body: CreateSessionRequest):
    return svc.create_session(body.title)


@router.get("/{session_id}")
def get_session(session_id: str):
    return svc.get_session(session_id)


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: str):
    return svc.delete_session(session_id)


@messages_router.get("/{project_id}", response_model=List[dict])
def list_messages(project_id: str, tab: Optional[str] = Query(None, description="content / ppt")):
    return svc.list_messages(project_id, tab=tab)
