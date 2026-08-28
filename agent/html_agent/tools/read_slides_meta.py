# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from shared.config import get_config
from domain.dal.project_store import ProjectStorage

@tool
def read_slides_meta(config: RunnableConfig) -> list:
    """读取当前项目的所有幻灯片元数据，返回 slide_index 和 title 列表。"""
    project_id = config["configurable"]["project_id"]
    base_dir = get_config().output_base_dir
    try:
        slides_data = ProjectStorage.load_slides_data(project_id, base_dir)
    except (FileNotFoundError, Exception):
        return []
    return [{"slide_index": s.slide_index, "title": s.title} for s in slides_data]
