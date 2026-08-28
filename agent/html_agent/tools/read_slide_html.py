# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from shared.config import get_config


@tool
def read_slide_html(
    slide_index: int,
    config: RunnableConfig,
) -> dict:
    """从项目目录读取对应幻灯片的HTML文件内容。

    Args:
        slide_index: 幻灯片编号（从1开始）

    Returns:
        包含slide_index、exists和html_content的字典
    """
    project_id = config["configurable"]["project_id"]
    config_obj = get_config()
    base_dir = config_obj.output_base_dir

    slide_dir = base_dir / "html_slides" / project_id / f"slide_{slide_index:02d}"
    html_file_path = slide_dir / "slide.html"

    exists = html_file_path.exists()
    html_content = ""
    if exists:
        with open(html_file_path, "r", encoding="utf-8") as f:
            html_content = f.read()

    return {
        "slide_index": slide_index,
        "exists": exists,
        "html_content": html_content,
    }
