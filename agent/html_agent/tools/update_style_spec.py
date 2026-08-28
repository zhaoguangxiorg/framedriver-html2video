# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from shared.config import get_config
from domain.dal.project_store import ProjectStorage


@tool
def update_style_spec(content: str, config: RunnableConfig) -> dict:
    """保存PPT设计规范到项目目录。

    Args:
        content: 完整的设计规范Markdown内容

    Returns:
        包含project_id、message和file_path的字典
    """
    project_id = config["configurable"]["project_id"]
    config_obj = get_config()
    base_dir = config_obj.output_base_dir

    ProjectStorage.save_style_spec(project_id, base_dir, content)

    return {
        "project_id": project_id,
        "message": "设计规范已更新",
        "file_path": str((base_dir / "html_slides" / project_id / "style_spec.md").resolve()),
    }
