# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""messages 表数据访问层（DAL）。"""
from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError

from domain.dal.db import _new_session
from domain.entities.db_models import Message


class MessageStorage:
    """CRUD for chat messages."""

    @staticmethod
    def add_message(
        project_id: str,
        role: str,
        content: str,
        tab: str = "content",
        steps: Optional[list] = None,
        slides: Optional[list] = None,
        cards: Optional[list] = None,
        status: str = "completed",
    ) -> dict:
        """Insert a message and return serialized dict.

        Args:
            steps: 执行步骤列表，每项形如 {"name": "中文名", "code": "tool_name"}。
                仅对 agent 消息有意义；为 None 或空列表时存 "[]"。
            slides: 幻灯片卡片列表，每项形如 {"slide_index": 1, "title": "...", ...}。
            cards: 卡片数组（气泡外），每项形如 {"card_type": "...", "card_data": {...}}。
                支持 card_type=intervention 与 card_type=slides 混合；为 None 或空列表时存 "[]"。
            status: 消息状态，默认 "completed"。可选值: pending/completed/interrupted/error。
        """
        import uuid
        from datetime import datetime
        import json as _json
        steps_json = _json.dumps(steps or [], ensure_ascii=False)
        slides_json = _json.dumps(slides or [], ensure_ascii=False)
        cards_json = _json.dumps(cards or [], ensure_ascii=False)
        msg = Message(
            id=str(uuid.uuid4()),
            project_id=project_id,
            role=role,
            content=content or "",
            tab=tab,
            steps=steps_json,
            slides=slides_json,
            cards=cards_json,
            status=status,
            created_at=datetime.utcnow(),
        )
        db = _new_session()
        try:
            db.add(msg)
            db.commit()
            db.refresh(msg)
            return msg.to_dict()
        except SQLAlchemyError:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def list_messages(project_id: str, tab: Optional[str] = None) -> List[dict]:
        """Return messages for a project, optionally filtered by tab."""
        db = _new_session()
        try:
            q = db.query(Message).filter(Message.project_id == project_id)
            if tab:
                q = q.filter(Message.tab == tab)
            rows = q.order_by(Message.created_at.asc()).all()
            return [r.to_dict() for r in rows]
        finally:
            db.close()

    @staticmethod
    def delete_messages(project_id: str) -> int:
        """Delete all messages for a project. Returns count deleted."""
        db = _new_session()
        try:
            count = db.query(Message).filter(Message.project_id == project_id).delete()
            db.commit()
            return count
        except SQLAlchemyError:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def update_message_cards(message_id: str, cards: list) -> bool:
        """更新指定消息的 cards 字段。

        Args:
            message_id: 消息 ID。
            cards: 卡片数组（list），每项形如 {"card_type": "...", "card_data": {...}}。
                内部 json.dumps 后存入。

        Returns:
            True 表示更新成功，False 表示消息不存在。
        """
        import json as _json
        cards_json = _json.dumps(cards or [], ensure_ascii=False)
        db = _new_session()
        try:
            row = db.query(Message).filter(Message.id == message_id).first()
            if row is None:
                return False
            row.cards = cards_json
            db.commit()
            return True
        except SQLAlchemyError:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def update_message_status(message_id: str, status: str) -> bool:
        """更新指定消息的 status 字段。"""
        db = _new_session()
        try:
            row = db.query(Message).filter(Message.id == message_id).first()
            if row is None:
                return False
            row.status = status
            db.commit()
            return True
        except SQLAlchemyError:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def get_last_agent_message(project_id: str) -> Optional[dict]:
        """获取指定项目最后一条 role=agent 的消息。"""
        db = _new_session()
        try:
            row = db.query(Message).filter_by(
                project_id=project_id, role="agent"
            ).order_by(Message.created_at.desc()).first()
            return row.to_dict() if row else None
        finally:
            db.close()

    @staticmethod
    def get_message_by_intervention_id(
        project_id: str, intervention_id: str
    ) -> Optional[dict]:
        """根据 intervention_id 查找对应的 role=agent 消息。

        查找逻辑：遍历该 project_id 的 role=agent 消息，解析 cards JSON，
        查找 card_type=intervention 且 card_data.intervention_id 匹配的卡片。

        Args:
            project_id: 项目 ID。
            intervention_id: 介入问题唯一标识。

        Returns:
            消息完整 dict（含 id, content, steps, cards 等字段），
            找不到返回 None。
        """
        import json as _json
        db = _new_session()
        try:
            rows = (
                db.query(Message)
                .filter(Message.project_id == project_id, Message.role == "agent")
                .all()
            )
            for row in rows:
                try:
                    cards = _json.loads(row.cards) if row.cards else []
                except (ValueError, TypeError):
                    cards = []
                for card in cards:
                    if not isinstance(card, dict):
                        continue
                    if card.get("card_type") != "intervention":
                        continue
                    card_data = card.get("card_data") or {}
                    if card_data.get("intervention_id") == intervention_id:
                        return row.to_dict()
            return None
        finally:
            db.close()

    @staticmethod
    def update_message_content_steps(
        message_id: str, content: str, steps: list, cards: list
    ) -> bool:
        """恢复完成时更新原消息的 content / steps / cards 字段（全量覆盖）。

        Args:
            message_id: 消息 ID。
            content: 最终文本（覆盖原 content）。
            steps: 全部步骤列表（覆盖原 steps，内部 json.dumps）。
            cards: 完整卡片数组（覆盖原 cards，内部 json.dumps）。

        Returns:
            True 表示更新成功，False 表示消息不存在。
        """
        import json as _json
        steps_json = _json.dumps(steps or [], ensure_ascii=False)
        cards_json = _json.dumps(cards or [], ensure_ascii=False)
        db = _new_session()
        try:
            row = db.query(Message).filter(Message.id == message_id).first()
            if row is None:
                return False
            row.content = content or ""
            row.steps = steps_json
            row.cards = cards_json
            db.commit()
            return True
        except SQLAlchemyError:
            db.rollback()
            raise
        finally:
            db.close()
