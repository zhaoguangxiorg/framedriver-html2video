# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""PPT package download API (technical layer).

Only routes and delegation to appservice.
"""
from fastapi import APIRouter

from appservice import package_appservice as svc

router = APIRouter(prefix="/api/package", tags=["package"])


@router.get("/{project_id}/download")
def download_ppt(project_id: str):
    return svc.download_ppt(project_id)


@router.get("/{project_id}/view")
def view_ppt(project_id: str):
    return svc.view_ppt(project_id)
