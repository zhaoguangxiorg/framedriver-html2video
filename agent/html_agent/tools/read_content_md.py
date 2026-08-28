# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from shared.config import get_config


@tool
def read_content_md(config: RunnableConfig) -> dict:
    """读取项目目录中的 content.md 文件（上一步内容生成结果）。

    Returns:
        包含 project_id、exists 和 content 的字典
    """
    project_id = config["configurable"]["project_id"]
    config_obj = get_config()
    base_dir = config_obj.output_base_dir

    content_path = base_dir / "html_slides" / project_id / "content.md"
    exists = content_path.exists()
    content = ""
    if exists:
        content = content_path.read_text(encoding="utf-8")

    return {
        "project_id": project_id,
        "exists": exists,
        "content": content,
    }
