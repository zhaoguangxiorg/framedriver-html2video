# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""CRUD operations for the `sessions` table.

Reuses `output/html_slides/checkpoints.db` (the same database used by the
agent short-term memory). Only adds a `sessions` table, never overwrites
existing tables.
"""
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session as ORMSession

from shared.config import get_config
from shared.file_utils import ensure_dir
from domain.entities.db_models import Base


def _get_db_path() -> Path:
    config = get_config()
    base_dir = config.output_base_dir
    return base_dir / "checkpoints.db"


_engine = None
_SessionLocal: Optional[sessionmaker] = None


def get_session_local() -> sessionmaker:
    """返回已初始化的 sessionmaker 工厂。

    跨模块使用时不要直接 `with get_session_local() as session`，
    因为 sessionmaker 工厂本身不是上下文管理器，应使用 `new_session()`：
    `with new_session() as session:`。
    """
    _get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def new_session() -> ORMSession:
    """创建一个新 Session，可直接用于 with 上下文管理器。

    例：
        with new_session() as session:
            session.query(...)
    """
    return get_session_local()()


def _get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        db_path = _get_db_path()
        ensure_dir(db_path.parent)
        _engine = create_engine(
            f"sqlite:///{db_path.as_posix()}",
            connect_args={"check_same_thread": False},
            echo=False,
        )
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def init_db() -> None:
    """Create `sessions` table and indexes if not exists.

    Uses `checkfirst=True` to avoid touching other tables (e.g. checkpoints
    owned by langgraph) that already exist in the same database.
    """
    engine = _get_engine()
    Base.metadata.create_all(engine, checkfirst=True)
    _migrate_messages_steps(engine)
    _migrate_messages_slides(engine)
    _migrate_messages_cards(engine)
    _migrate_messages_status(engine)
    _migrate_model_code_rule(engine)


def _migrate_messages_steps(engine) -> None:
    """Add `steps` column to legacy `messages` table if missing."""
    from sqlalchemy import text, inspect
    insp = inspect(engine)
    if not insp.has_table("messages"):
        return
    columns = {c["name"] for c in insp.get_columns("messages")}
    if "steps" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE messages ADD COLUMN steps TEXT NOT NULL DEFAULT '[]'"
        ))


def _migrate_messages_slides(engine) -> None:
    """Add `slides` column to legacy `messages` table if missing."""
    from sqlalchemy import text, inspect
    insp = inspect(engine)
    if not insp.has_table("messages"):
        return
    columns = {c["name"] for c in insp.get_columns("messages")}
    if "slides" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE messages ADD COLUMN slides TEXT NOT NULL DEFAULT '[]'"
        ))


def _migrate_messages_cards(engine) -> None:
    """Add `cards` column to `messages` table if missing, then migrate legacy
    `slides` data into the new `cards` format.

    迁移规则（参考 docs/human-intervention-design.md 第 6.7 节）：
    - 原 slides = [{slide_index:1, ...}, ...]
    - 转 cards = [{card_type:"slides", card_data:{slide_index:1, ...}}, ...]
    - 不删除 slides 列（SQLite 删列风险），保留但不再读写
    - steps 字段不迁移（保持现状）
    - 幂等：只迁移 slides != '[]' 且 cards == '[]' 的记录，避免重复迁移
    """
    import json as _json
    from sqlalchemy import text, inspect

    insp = inspect(engine)
    if not insp.has_table("messages"):
        return

    columns = {c["name"] for c in insp.get_columns("messages")}

    # Step 1: 添加 cards 列（兼容老数据库）
    if "cards" not in columns:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE messages ADD COLUMN cards TEXT NOT NULL DEFAULT '[]'"
            ))

    # Step 2: 迁移 slides 老数据到 cards 格式
    # 仅迁移 slides != '[]' 且 cards == '[]' 的记录（幂等）
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT id, slides FROM messages WHERE slides != '[]' AND cards = '[]'"
        )).fetchall()
        for row in rows:
            rid, slides_json = row
            try:
                slides = _json.loads(slides_json) if slides_json else []
            except (ValueError, TypeError):
                slides = []
            if not slides:
                continue
            cards = [{"card_type": "slides", "card_data": s} for s in slides]
            cards_json = _json.dumps(cards, ensure_ascii=False)
            conn.execute(text(
                "UPDATE messages SET cards = :cards WHERE id = :id"
            ), {"cards": cards_json, "id": rid})


def _migrate_messages_status(engine) -> None:
    """Add `status` column to `messages` table if missing.

    幂等设计：只添加列，不修改已有数据（老数据默认已是 'completed'）。
    """
    from sqlalchemy import text, inspect
    insp = inspect(engine)
    if not insp.has_table("messages"):
        return
    columns = {c["name"] for c in insp.get_columns("messages")}
    if "status" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE messages ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'"
        ))


def _new_session() -> ORMSession:
    assert _SessionLocal is not None
    return _SessionLocal()


def _migrate_model_code_rule(engine) -> None:
    """一次性迁移：将旧 code 规则更新为 provider-model_name 新规则。

    幂等：只更新 code 不符合 `{provider}-{model_name}` 格式的记录。
    """
    from datetime import datetime
    from sqlalchemy import text, inspect

    insp = inspect(engine)
    if not insp.has_table("model_configs"):
        return

    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT id, code, model_provider, model_name FROM model_configs"
        )).fetchall()
        for row in rows:
            rid, old_code, provider, model_name = row
            expected_code = f"{provider}-{model_name}"
            if old_code != expected_code:
                conn.execute(text(
                    "UPDATE model_configs SET code = :code, updated_at = :now WHERE id = :id"
                ), {"code": expected_code, "now": datetime.utcnow(), "id": rid})
