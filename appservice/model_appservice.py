# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""模型配置业务层。

承接模型配置管理的业务逻辑：调用 domain.service.model_config_service，
并对对外响应做 api_key 脱敏。api 层只负责路由与参数透传。
"""
from typing import List, Optional

from fastapi import HTTPException

from domain.service.model_config_service import (
    create_model as create_model_record,
    delete_model as delete_model_record,
    get_model_by_id_masked,
    list_models_masked,
    mask_api_key,
    update_model as update_model_record,
)


def _mask_response(model_dict: dict) -> dict:
    """Mask api_key in response dict."""
    if model_dict and "api_key" in model_dict:
        model_dict["api_key"] = mask_api_key(model_dict["api_key"])
    return model_dict


def list_models(enabled: Optional[int] = None) -> List[dict]:
    """返回模型列表，api_key 脱敏。enabled=1 时仅返回启用模型。"""
    enabled_only = enabled == 1
    return list_models_masked(enabled_only=enabled_only)


def get_model(model_id: int):
    """按 id 查询单个模型，api_key 脱敏。"""
    row = get_model_by_id_masked(model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="model not found")
    return row


def create_model(data: dict):
    """创建模型。api_key 加密入库；is_default=1 时清空其他默认。"""
    try:
        created = create_model_record(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _mask_response(created)


def update_model(model_id: int, data: dict):
    """更新模型。api_key 为空/未传时保留原值；is_default=1 时清空其他默认。"""
    try:
        updated = update_model_record(model_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="model not found")
    return _mask_response(updated)


def delete_model(model_id: int):
    """删除模型。"""
    deleted = delete_model_record(model_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="model not found")
    return None
