# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-19

"""视频分享业务层：分享数字码 ↔ 项目 ID（可选片段文件名）的内存映射。

接口：
- bind(project_id, code, clip_file=None)：绑定或修改映射（code 全站唯一，已被占用返回 409）
- get_code_by_project(project_id)：查询项目已绑定的 code（供前端再次分享时预填）
- get_by_code(code)：按 code 查询分享信息，并校验目标视频已生成

分享目标可为完整视频（final_video.mp4）或指定片段（video_clips/xxx.mp4）：
不带 clip_file 时分享完整视频；带 clip_file 时分享对应片段。

注意：当前基于进程内内存 dict 实现（与 video_appservice._tasks 同模式），
服务重启后映射丢失；后续如需持久化可迁移到数据库。
"""
import logging
import threading
from pathlib import Path
from typing import Dict, Optional

from fastapi import HTTPException

from shared.config import get_config

logger = logging.getLogger("appservice.share")

# 内存映射：code(数字) -> {"project_id": str, "clip_file": Optional[str]}
_share_map: Dict[str, dict] = {}
# 反向映射：project_id -> code，用于"再次分享可修改"与弹窗预填
_pid_map: Dict[str, str] = {}
_share_lock = threading.Lock()


def _project_dir(project_id: str) -> Path:
    return get_config().output_base_dir / "html_slides" / project_id


def _ensure_media_ready(project_id: str, clip_file: Optional[str] = None) -> None:
    """校验分享目标视频存在，未生成则拒绝绑定/查询。"""
    if clip_file:
        clip = _project_dir(project_id) / "video_clips" / clip_file
        if not clip.exists():
            raise HTTPException(status_code=400, detail="片段视频不存在或已被删除")
        return
    final = _project_dir(project_id) / "final_video.mp4"
    if not final.exists():
        raise HTTPException(status_code=400, detail="视频尚未生成，请先生成视频再分享")


def _build_share_info(code: str, project_id: str, clip_file: Optional[str] = None) -> dict:
    if clip_file:
        video_url = f"/api/video/{project_id}/clips/{clip_file}/download"
    else:
        video_url = f"/api/video/{project_id}/download"
    return {
        "code": code,
        "project_id": project_id,
        "share_url": f"/s/{code}",
        "video_url": video_url,
        "download_url": video_url,
        "clip_file": clip_file,
    }


def bind(project_id: str, code: str, clip_file: Optional[str] = None) -> dict:
    """绑定或修改 code ↔ (project_id, clip_file) 映射。"""
    code = (code or "").strip()
    if not code or not code.isdigit():
        raise HTTPException(status_code=400, detail="分享数字必须为纯数字，如 123")

    _ensure_media_ready(project_id, clip_file)

    with _share_lock:
        # 该数字已被其他项目占用
        existing = _share_map.get(code)
        if existing is not None and existing["project_id"] != project_id:
            raise HTTPException(status_code=409, detail="该数字已被占用，请换一个数字")

        # 本项目已有旧 code：先释放旧映射（即"修改映射"）
        old_code = _pid_map.get(project_id)
        if old_code is not None and old_code != code:
            _share_map.pop(old_code, None)

        _share_map[code] = {"project_id": project_id, "clip_file": clip_file}
        _pid_map[project_id] = code

    return _build_share_info(code, project_id, clip_file)


def get_code_by_project(project_id: str) -> Optional[str]:
    """返回项目已绑定的 code；未绑定返回 None。"""
    with _share_lock:
        return _pid_map.get(project_id)


def get_by_code(code: str) -> dict:
    """按 code 查询分享信息；不存在返回 404。"""
    with _share_lock:
        entry = _share_map.get(code)
    if entry is None:
        raise HTTPException(status_code=404, detail="分享不存在")

    _ensure_media_ready(entry["project_id"], entry.get("clip_file"))

    return _build_share_info(code, entry["project_id"], entry.get("clip_file"))
