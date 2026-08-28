# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""视频分享 API（技术层）。

仅路由与参数透传，业务逻辑在 appservice.share_appservice：
- POST /api/share             绑定/修改分享数字码与项目映射（可带 clip_file 分享片段）
- GET  /api/share/current     查询项目已绑定的数字码（再次分享预填）
- GET  /api/share/{code}      按数字码查询分享信息（分享页前端调用）
- GET  /s/{code}              分享页入口（返回响应式分享页 share.html）
"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from appservice import share_appservice as svc

router = APIRouter(tags=["share"])

# share.html 位于 presentation/web/static/share.html
_SHARE_HTML = (
    Path(__file__).resolve().parent.parent / "web" / "static" / "share.html"
)


class ShareRequest(BaseModel):
    project_id: str
    code: str
    clip_file: Optional[str] = None


@router.post("/api/share")
def bind(req: ShareRequest):
    return svc.bind(req.project_id, req.code, req.clip_file)


@router.get("/api/share/current")
def get_current(project_id: str):
    return {"code": svc.get_code_by_project(project_id)}


@router.get("/api/share/{code}")
def get_share(code: str):
    return svc.get_by_code(code)


@router.get("/s/{code}")
def share_page(code: str):
    try:
        svc.get_by_code(code)
    except HTTPException:
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding-top:120px;"
            "color:#666;'>该分享不存在或已失效</body></html>",
            status_code=404,
        )
    return FileResponse(str(_SHARE_HTML), media_type="text/html")
