# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""Model management API (technical layer).

Only routes, request models, and delegation to appservice.
"""
from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from appservice import model_appservice as svc

router = APIRouter(prefix="/api/models", tags=["models"])


class ModelCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    model_name: str = Field(..., min_length=1, max_length=128)
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    model_provider: str = Field(..., min_length=1, max_length=64)
    is_default: Optional[int] = 0
    is_fallback: Optional[int] = 0
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    enabled: Optional[int] = 1


class ModelUpdateRequest(BaseModel):
    name: Optional[str] = None
    model_name: Optional[str] = None
    api_key: Optional[str] = None  # empty/None = keep original
    base_url: Optional[str] = None
    model_provider: Optional[str] = None
    is_default: Optional[int] = None
    is_fallback: Optional[int] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    enabled: Optional[int] = None


@router.get("", response_model=List[dict])
def list_models(enabled: Optional[int] = Query(None, description="1=仅启用")):
    return svc.list_models(enabled)


@router.get("/{model_id}")
def get_model(model_id: int):
    return svc.get_model(model_id)


@router.post("", status_code=201)
def create_model(body: ModelCreateRequest):
    return svc.create_model(body.model_dump())


@router.put("/{model_id}")
def update_model(model_id: int, body: ModelUpdateRequest):
    # 仅传显式设置的字段，避免把 None 覆盖到数据库
    return svc.update_model(model_id, body.model_dump(exclude_unset=True))


@router.delete("/{model_id}", status_code=204)
def delete_model(model_id: int):
    return svc.delete_model(model_id)
