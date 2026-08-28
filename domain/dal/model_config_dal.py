# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""model_configs 表数据访问。

所有函数返回 ORM 行字段的原始 dict（api_key 为加密密文，
created_at/updated_at 为 datetime 对象），业务处理（解密/脱敏/组装）
由 domain.service.model_config_service 负责。
"""
from typing import List, Optional
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError

from domain.dal.db import new_session
from domain.entities.db_models import ModelConfig


def _row_to_raw(row: ModelConfig) -> dict:
    """把 ORM 行提取为原始 dict（api_key 为密文，时间字段为 datetime 对象）。"""
    return {
        "id": row.id,
        "name": row.name,
        "code": row.code,
        "model_name": row.model_name,
        "api_key": row.api_key,
        "base_url": row.base_url,
        "model_provider": row.model_provider,
        "is_default": row.is_default,
        "is_fallback": row.is_fallback,
        "temperature": row.temperature,
        "max_tokens": row.max_tokens,
        "enabled": row.enabled,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def list_model_rows(enabled_only: bool = False) -> List[dict]:
    """返回全部模型原始 dict，按 id 升序。enabled_only=True 时仅 enabled=1。"""
    with new_session() as session:
        q = session.query(ModelConfig)
        if enabled_only:
            q = q.filter(ModelConfig.enabled == 1)
        rows = q.order_by(ModelConfig.id.asc()).all()
        return [_row_to_raw(r) for r in rows]


def get_model_row_by_id(model_id: int) -> Optional[dict]:
    """按 id 查询模型原始 dict；不存在返回 None。"""
    with new_session() as session:
        row = session.query(ModelConfig).filter(ModelConfig.id == model_id).first()
        return _row_to_raw(row) if row else None


def get_model_row_by_code(code: str) -> Optional[dict]:
    """按 code 查询模型原始 dict；不存在返回 None。"""
    with new_session() as session:
        row = session.query(ModelConfig).filter(ModelConfig.code == code).first()
        return _row_to_raw(row) if row else None


def get_default_model_row() -> Optional[dict]:
    """返回 is_default=1 的模型原始 dict；不存在返回 None。"""
    with new_session() as session:
        row = session.query(ModelConfig).filter(ModelConfig.is_default == 1).first()
        return _row_to_raw(row) if row else None


def get_row_by_provider_model(
    provider: str, model_name: str, exclude_id: Optional[int] = None
) -> Optional[dict]:
    """按 (model_provider, model_name) 查重；exclude_id 用于更新时排除自身。"""
    with new_session() as session:
        q = session.query(ModelConfig).filter(
            ModelConfig.model_provider == provider,
            ModelConfig.model_name == model_name,
        )
        if exclude_id is not None:
            q = q.filter(ModelConfig.id != exclude_id)
        row = q.first()
        return _row_to_raw(row) if row else None


def insert_model_row(fields: dict) -> dict:
    """插入一行并返回原始 dict。fields 需包含除 created_at/updated_at 外的全部列。"""
    now = datetime.utcnow()
    row = ModelConfig(
        name=fields["name"],
        code=fields["code"],
        model_name=fields["model_name"],
        api_key=fields["api_key"],
        base_url=fields.get("base_url"),
        model_provider=fields["model_provider"],
        is_default=fields["is_default"],
        is_fallback=fields.get("is_fallback", 0),
        temperature=fields.get("temperature"),
        max_tokens=fields.get("max_tokens"),
        enabled=fields.get("enabled", 1),
        created_at=now,
        updated_at=now,
    )
    with new_session() as session:
        session.add(row)
        try:
            session.commit()
            session.refresh(row)
        except SQLAlchemyError:
            session.rollback()
            raise
        return _row_to_raw(row)


def update_model_row(model_id: int, fields: dict) -> Optional[dict]:
    """按 id 更新指定字段（fields 已含全部需要覆盖的列）并返回原始 dict；不存在返回 None。"""
    with new_session() as session:
        row = session.query(ModelConfig).filter(ModelConfig.id == model_id).first()
        if row is None:
            return None
        for key, value in fields.items():
            setattr(row, key, value)
        row.updated_at = datetime.utcnow()
        try:
            session.commit()
            session.refresh(row)
        except SQLAlchemyError:
            session.rollback()
            raise
        return _row_to_raw(row)


def delete_model_row(model_id: int) -> bool:
    """删除模型；存在并删除返回 True，不存在返回 False。"""
    with new_session() as session:
        row = session.query(ModelConfig).filter(ModelConfig.id == model_id).first()
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


def clear_default_flags() -> None:
    """把所有模型的 is_default 置 0（新建/设默认前调用）。"""
    with new_session() as session:
        session.query(ModelConfig).update({ModelConfig.is_default: 0})
        session.commit()
