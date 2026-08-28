# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from shared.config import get_config
from shared.file_utils import ensure_dir


@tool
def save_slide_html(
    slide_index: int,
    html_content: str,
    config: RunnableConfig,
) -> dict:
    """将HTML内容保存为幻灯片文件，存储到项目目录。

    Args:
        slide_index: 幻灯片编号（从1开始）
        html_content: 完整的HTML内容字符串

    Returns:
        包含slide_index、html_file_path和project_id的字典
    """
    project_id = config["configurable"]["project_id"]
    config_obj = get_config()
    base_dir = config_obj.output_base_dir

    slide_dir = base_dir / "html_slides" / project_id / f"slide_{slide_index:02d}"
    ensure_dir(slide_dir)
    html_file_path = slide_dir / "slide.html"

    with open(html_file_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return {
        "slide_index": slide_index,
        "project_id": project_id,
    }
