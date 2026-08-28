# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""幻灯片数据业务层。

承接幻灯片数据管理逻辑：幻灯片列表、HTML 读取、逐字稿读写。
"""
import logging
from pathlib import Path
from typing import List

from fastapi import HTTPException
from fastapi.responses import HTMLResponse

from shared.config import get_config
from domain.dal.project_store import ProjectStorage

logger = logging.getLogger("appservice.slide")


def _project_dir(project_id: str) -> Path:
    return get_config().output_base_dir / "html_slides" / project_id


def list_slides(project_id: str) -> List[dict]:
    """Return all slides metadata for a project."""
    try:
        rows = ProjectStorage.load_slides_data(project_id, get_config().output_base_dir)
    except FileNotFoundError:
        return []
    items = []
    for row in rows:
        d = row.model_dump()
        idx = d.get("slide_index")
        d["html_path"] = f"/api/slides/{project_id}/{idx}/html"
        d["slide_text"] = ProjectStorage.load_slide_content(project_id, idx, get_config().output_base_dir)
        d["narration"] = ProjectStorage.load_slide_narration(project_id, idx, get_config().output_base_dir)
        items.append(d)
    return items


def get_slide_html(project_id: str, index: int):
    slide_dir = _project_dir(project_id) / f"slide_{index:02d}"
    html_file = slide_dir / "slide.html"
    if not html_file.exists():
        raise HTTPException(status_code=404, detail="slide.html not found")
    return HTMLResponse(html_file.read_text(encoding="utf-8"))


def get_narration(project_id: str, index: int):
    base_dir = get_config().output_base_dir
    narration = ProjectStorage.load_slide_narration(project_id, index, base_dir)
    try:
        rows = ProjectStorage.load_slides_data(project_id, base_dir)
        found = any(row.slide_index == index for row in rows)
        if not found:
            raise HTTPException(status_code=404, detail="slide not found")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="slides_data.json not found")
    return {"slide_index": index, "narration": narration}


def update_narration(project_id: str, index: int, narration: str):
    base_dir = get_config().output_base_dir
    try:
        rows = ProjectStorage.load_slides_data(project_id, base_dir)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="slides_data.json not found")

    found = any(row.slide_index == index for row in rows)
    if not found:
        raise HTTPException(status_code=404, detail="slide not found")

    ProjectStorage.save_slide_narration(project_id, index, narration, base_dir)
    return {"slide_index": index, "narration": narration}
