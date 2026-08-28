# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from shared.config import get_config
from domain.dal.project_store import ProjectStorage


@tool
def save_slide_content(
    slide_index: int,
    content: str,
    narration: str,
    config: RunnableConfig,
) -> dict:
    """将幻灯片正文内容和旁白保存到项目目录。

    Args:
        slide_index: 幻灯片编号（从1开始）
        content: 幻灯片正文内容字符串
        narration: 幻灯片旁白字符串

    Returns:
        包含slide_index和project_id的字典
    """
    project_id = config["configurable"]["project_id"]
    config_obj = get_config()
    base_dir = config_obj.output_base_dir

    ProjectStorage.save_slide_content(project_id, slide_index, content, base_dir)
    ProjectStorage.save_slide_narration(project_id, slide_index, narration, base_dir)

    return {
        "slide_index": slide_index,
        "project_id": project_id,
    }
