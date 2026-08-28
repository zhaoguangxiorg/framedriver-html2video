# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from typing import List

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from shared.config import get_config
from domain.dal.project_store import ProjectStorage
from domain.entities.schemas import SlideData


@tool
def init_project(
    topic: str,
    slides_meta: List[dict],
    config: RunnableConfig,
) -> dict:
    """初始化项目，创建项目目录并写入幻灯片内容数据。

    Args:
        topic: 整套幻灯片的主题
        slides_meta: 幻灯片列表，每个元素包含 slide_index、title

    Returns:
        包含project_id、total_slides和project_dir的字典
    """
    configurable = config.get("configurable", {})
    project_id = configurable.get("project_id")
    if not project_id:
        raise ValueError("project_id not found in config. Please pass project_id via config['configurable']['project_id']")

    config_obj = get_config()
    base_dir = config_obj.output_base_dir
    
    project_dir = base_dir / "html_slides" / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    
    slides_data: List[SlideData] = []
    for s in slides_meta:
        slide = SlideData(
            slide_index=s["slide_index"],
            title=s.get("title", ""),
            html_path=None,
        )
        slides_data.append(slide)
    
    slides_data.sort(key=lambda x: x.slide_index)
    ProjectStorage.save_slides_data(project_id, base_dir, slides_data)
    
    return {
        "project_id": project_id,
        "total_slides": len(slides_data),
        "project_dir": str(project_dir.resolve()),
    }
