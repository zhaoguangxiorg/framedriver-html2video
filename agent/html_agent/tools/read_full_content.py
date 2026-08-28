# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from shared.config import get_config
from domain.dal.project_store import ProjectStorage


@tool
def read_full_content(config: RunnableConfig) -> dict:
    """读取项目所有幻灯片的最新内容和逐字稿，拼成完整的 PPT Markdown 文档。

    格式与第一步 ContentAgent 生成的 content.md 完全一致，
    可以从整体视角了解当前 PPT 的全貌。

    Returns:
        包含 project_id 和 content（完整 Markdown 格式 PPT 内容）的字典
    """
    project_id = config["configurable"]["project_id"]
    config_obj = get_config()
    base_dir = config_obj.output_base_dir

    # 1. 读取 slides_data.json，获取排序后的幻灯片列表
    try:
        slides_data = ProjectStorage.load_slides_data(project_id, base_dir)
    except (FileNotFoundError, Exception):
        return {"project_id": project_id, "content": ""}

    slides = sorted(slides_data, key=lambda s: s.slide_index)

    # 2. 尝试从 content.md 提取标题
    project_dir = ProjectStorage.get_project_dir(project_id, base_dir)
    content_md_path = project_dir / "content.md"
    title_line = "PPT 完整内容"
    if content_md_path.exists():
        first_line = content_md_path.read_text(encoding="utf-8").split("\n")[0].strip()
        if first_line.startswith("# "):
            title_line = first_line[2:].strip()

    # 3. 遍历每张幻灯片，拼装内容
    lines = [f"# {title_line}\n"]

    for slide in slides:
        si = slide.slide_index
        slide_title = slide.title or ""

        slide_text = ProjectStorage.load_slide_content(project_id, si, base_dir)
        narration = ProjectStorage.load_slide_narration(project_id, si, base_dir)

        lines.append(f"## 第 {si} 张\n")
        lines.append(f"**标题**：{slide_title}\n")
        lines.append(f"**幻灯片内容**：")
        if slide_text:
            lines.append(slide_text)
        lines.append("")
        lines.append(f"**逐字讲解稿**：")
        if narration:
            lines.append(narration)
        lines.append("")

    return {
        "project_id": project_id,
        "content": "\n".join(lines),
    }
