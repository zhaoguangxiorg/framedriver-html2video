# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""SQLAlchemy ORM models for session manager.

Defines the `sessions` and `messages` tables, which live in the same SQLite
database as the agent short-term memory (`output/html_slides/checkpoints.db`).
"""
from datetime import datetime
from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Session(Base):
    """A user-created session, mapped to a project directory."""

    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, comment="UUID")
    project_id = Column(String(64), unique=True, nullable=False, comment="项目ID")
    title = Column(String(255), nullable=False, comment="会话标题（PPT 主题）")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    project_path = Column(String(500), nullable=False, comment="项目目录绝对路径")

    __table_args__ = (
        Index("idx_sessions_updated_at", "updated_at"),
        Index("idx_sessions_project_id", "project_id"),
    )


class Message(Base):
    """Chat message belonging to a project (content or ppt tab)."""

    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, comment="UUID")
    project_id = Column(String(64), nullable=False, comment="项目ID")
    role = Column(String(16), nullable=False, comment="user / agent")
    content = Column(Text, nullable=False, default="", comment="消息内容")
    tab = Column(String(16), nullable=False, default="content", comment="content / ppt")
    steps = Column(Text, nullable=False, default="[]", comment="执行步骤 JSON 数组，每项含 name/code")
    slides = Column(Text, nullable=False, default="[]", comment="幻灯片卡片 JSON 数组")
    cards = Column(Text, nullable=False, default="[]", comment="卡片数组 JSON（气泡外），每项含 card_type/card_data")
    status = Column(String(16), nullable=False, default="completed", comment="消息状态: pending/completed/interrupted/error")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_messages_project_id", "project_id"),
        Index("idx_messages_project_tab", "project_id", "tab"),
    )

    def to_dict(self) -> dict:
        import json as _json
        try:
            steps = _json.loads(self.steps) if self.steps else []
        except (ValueError, TypeError):
            steps = []
        try:
            slides = _json.loads(self.slides) if self.slides else []
        except (ValueError, TypeError):
            slides = []
        try:
            cards = _json.loads(self.cards) if self.cards else []
        except (ValueError, TypeError):
            cards = []
        return {
            "id": self.id,
            "project_id": self.project_id,
            "role": self.role,
            "content": self.content,
            "tab": self.tab,
            "steps": steps,
            "slides": slides,
            "cards": cards,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ModelConfig(Base):
    """模型网关配置表，存储可用模型的连接信息和参数。"""

    __tablename__ = "model_configs"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    name = Column(String(100), nullable=False, comment="显示名称")
    code = Column(String(64), unique=True, nullable=False, comment="唯一 code")
    model_name = Column(String(128), nullable=False, comment="模型名称（传给 init_chat_model 的 model 参数）")
    api_key = Column(Text, nullable=False, comment="Fernet 加密存储")
    base_url = Column(String(255), nullable=True, comment="自定义 API 地址")
    model_provider = Column(String(64), nullable=False, comment="提供商（openai/anthropic 等）")
    is_default = Column(Integer, default=0, comment="是否默认模型")
    is_fallback = Column(Integer, default=0, comment="是否降级备用")
    temperature = Column(Float, nullable=True, comment="默认温度")
    max_tokens = Column(Integer, nullable=True, comment="默认最大 tokens")
    enabled = Column(Integer, default=1, comment="是否启用")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="更新时间")

    __table_args__ = (
        Index("idx_model_configs_code", "code"),
    )
