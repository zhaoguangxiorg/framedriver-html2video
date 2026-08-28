# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""sessions 表数据访问层（DAL）。"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError

from domain.dal.db import _new_session
from domain.entities.db_models import Session


def _serialize(row: Optional[Session]) -> Optional[dict]:
    """Eagerly convert a SQLAlchemy Session row to a dict.

    Must be called while the row is still attached to its session,
    otherwise accessing attributes raises DetachedInstanceError.
    """
    if row is None:
        return None
    return {
        "id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "project_path": row.project_path,
    }


class SessionStorage:
    """High-level CRUD for sessions."""

    @staticmethod
    def insert_session(title: str, session_id: str, project_id: str, project_path: str) -> dict:
        """插入一条会话记录并返回序列化 dict（业务编排由 service 层负责）。"""
        now = datetime.utcnow()
        record = Session(
            id=session_id,
            project_id=project_id,
            title=title,
            created_at=now,
            updated_at=now,
            project_path=project_path,
        )
        db = _new_session()
        try:
            db.add(record)
            db.commit()
            db.refresh(record)
            return _serialize(record)
        except SQLAlchemyError:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def list_sessions() -> List[dict]:
        """Return all sessions ordered by `updated_at` descending."""
        db = _new_session()
        try:
            rows = db.query(Session).order_by(Session.updated_at.desc()).all()
            return [_serialize(row) for row in rows]
        finally:
            db.close()

    @staticmethod
    def get_session(session_id: str) -> Optional[dict]:
        db = _new_session()
        try:
            row = db.query(Session).filter(Session.id == session_id).first()
            return _serialize(row)
        finally:
            db.close()

    @staticmethod
    def delete_session(session_id: str) -> bool:
        """Delete session record. Returns True if deleted, False if not found."""
        db = _new_session()
        try:
            row = db.query(Session).filter(Session.id == session_id).first()
            if row is None:
                return False
            db.delete(row)
            db.commit()
            return True
        except SQLAlchemyError:
            db.rollback()
            raise
        finally:
            db.close()
