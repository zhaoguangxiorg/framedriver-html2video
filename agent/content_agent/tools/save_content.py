# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from shared.config import get_config
from shared.file_utils import ensure_dir


@tool
def save_content(content: str, config: RunnableConfig) -> dict:
    """保存完整的 Markdown 格式内容到项目目录的 content.md 文件（完全覆盖）。

    Args:
        content: 完整的 Markdown 格式 PPT 内容

    Returns:
        包含 project_id、message 和 file_path 的字典
    """
    project_id = config["configurable"]["project_id"]
    config_obj = get_config()
    base_dir = config_obj.output_base_dir

    project_dir = base_dir / "html_slides" / project_id
    ensure_dir(project_dir)

    content_path = project_dir / "content.md"
    content_path.write_text(content, encoding="utf-8")

    return {
        "project_id": project_id,
        "message": "内容已保存",
        "file_path": str(content_path.resolve()),
    }
