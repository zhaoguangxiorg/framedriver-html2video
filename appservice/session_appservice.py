# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""会话业务层。

承接会话与消息的业务逻辑：会话 CRUD、删除协调（数据库+项目目录+内存态清理）、
项目忙碌判定。api 层只负责路由与参数透传。
"""
import shutil
from typing import List, Optional

from fastapi import HTTPException

from shared.config import get_config
from domain.dal.session_dal import SessionStorage
from domain.dal.message_dal import MessageStorage
from domain.service.session_service import create_session as create_session_record


def list_sessions() -> List[dict]:
    """Return all sessions ordered by `updated_at` desc."""
    return SessionStorage.list_sessions()


def create_session(title: str) -> dict:
    """创建一个新会话及其项目目录。"""
    try:
        return create_session_record(title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def get_session(session_id: str) -> dict:
    row = SessionStorage.get_session(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    return row


def is_project_busy(project_id: str) -> bool:
    """判定项目是否正在执行生成任务（PPT / 内容 / 视频任一进行中即 busy）。

    局部导入避免模块间循环依赖。
    """
    from appservice import ppt_appservice as _ppt, content_appservice as _content, video_appservice as _video

    # PPT 智能体
    if project_id in _ppt._running_state:
        return True

    # 内容智能体
    if project_id in _content._content_running:
        return True

    # 视频一键生成
    if _video._tasks.get(project_id, {}).get("status") == "running":
        return True

    # 高级单张生成（key 以 f"{project_id}:" 开头）
    with _video._slide_tasks_lock:
        for key, slide_task in _video._slide_tasks.items():
            if key.startswith(f"{project_id}:") and slide_task.get("status") == "running":
                return True

    # 一键合并
    if _video._concat_task.get(project_id, {}).get("status") == "running":
        return True

    return False


def delete_session(session_id: str) -> None:
    """删除会话：sessions/messages 表 + 项目目录 + 各模块内存态。"""
    from appservice import ppt_appservice as _ppt, content_appservice as _content, video_appservice as _video

    session = SessionStorage.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    project_id = session["project_id"]

    if is_project_busy(project_id):
        raise HTTPException(status_code=409, detail="会话正在执行中，请等待完成后再删除")

    # 1. sessions 表
    SessionStorage.delete_session(session_id)
    # 2. messages 表
    MessageStorage.delete_messages(project_id)
    # 3. 递归删除项目目录
    shutil.rmtree(get_config().output_base_dir / "html_slides" / project_id, ignore_errors=True)
    # 4. 清内存态
    _ppt._running_state.pop(project_id, None)
    _content._content_running.discard(project_id)
    # 5. 清视频任务内存记录（带锁）
    with _video._tasks_lock:
        _video._tasks.pop(project_id, None)
    with _video._concat_task_lock:
        _video._concat_task.pop(project_id, None)
    with _video._slide_tasks_lock:
        keys = [k for k in _video._slide_tasks if k.startswith(f"{project_id}:")]
        for k in keys:
            _video._slide_tasks.pop(k, None)

    return None


def list_messages(project_id: str, tab: Optional[str] = None) -> List[dict]:
    """Return chat messages for a project, optionally filtered by tab."""
    return MessageStorage.list_messages(project_id, tab=tab)
