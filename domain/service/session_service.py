# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""会话业务规则层（service）。"""
import uuid
from pathlib import Path

from shared.config import get_config
from shared.file_utils import ensure_dir

from domain.dal.session_dal import SessionStorage


def create_session(title: str) -> dict:
    """创建一个新会话：校验标题 → 生成 ID → 创建项目目录 → 入库。

    Args:
        title: PPT 主题。

    Returns:
        序列化后的会话 dict。

    Raises:
        ValueError: title 为空。
    """
    title = (title or "").strip()
    if not title:
        raise ValueError("title cannot be empty")

    config = get_config()
    base_dir = config.output_base_dir
    session_id = str(uuid.uuid4())
    project_id = session_id
    project_path = str((base_dir / "html_slides" / project_id).resolve())
    ensure_dir(Path(project_path))

    return SessionStorage.insert_session(title, session_id, project_id, project_path)
