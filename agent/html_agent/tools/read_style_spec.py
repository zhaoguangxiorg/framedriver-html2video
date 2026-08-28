# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from shared.config import get_config
from domain.dal.project_store import ProjectStorage


@tool
def read_style_spec(config: RunnableConfig) -> dict:
    """读取项目目录中的PPT设计规范文件。

    Returns:
        包含project_id、exists和content的字典
    """
    project_id = config["configurable"]["project_id"]
    config_obj = get_config()
    base_dir = config_obj.output_base_dir

    content = ProjectStorage.load_style_spec(project_id, base_dir)
    exists = content != ""

    return {
        "project_id": project_id,
        "exists": exists,
        "content": content,
    }
