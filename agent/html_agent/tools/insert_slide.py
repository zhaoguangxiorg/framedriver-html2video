# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from shared.config import get_config
from domain.dal.project_store import ProjectStorage
from domain.entities.schemas import SlideData
from domain.service.slide_service import reindex_slides, shift_slide_dirs

@tool
def insert_slide(position: int, title: str, config: RunnableConfig) -> dict:
    """在指定位置插入一张新幻灯片（仅元数据，不创建目录，不写内容文件）。

    插入位置及之后的幻灯片目录整体后移 +1，避免索引冲突。
    目录由后续 slide-designer 的 save_slide_content 创建。

    Args:
        position: 新幻灯片的插入位置（1-based，插入后幻灯片编号为 position）
        title: 新幻灯片的标题

    Returns:
        包含 new_slide_index 和 message 的字典
    """
    project_id = config["configurable"]["project_id"]
    base_dir = get_config().output_base_dir

    try:
        slides_data = ProjectStorage.load_slides_data(project_id, base_dir)
    except (FileNotFoundError, Exception):
        slides_data = []

    slides_list = sorted(slides_data, key=lambda s: s.slide_index)

    max_idx = max((s.slide_index for s in slides_list), default=0)

    # 插入位置及之后的目录整体后移 +1（从最大编号倒序平移，避免覆盖）
    if max_idx >= position:
        shift_slide_dirs(project_id, base_dir, position, max_idx, +1)

    # 创建新条目（用临时 slide_index，reindex 会修正）
    new_slide = SlideData(
        slide_index=position,
        title=title,
        html_path=None,
    )

    # 插入到指定位置
    insert_pos = min(position - 1, len(slides_list))
    slides_list.insert(insert_pos, new_slide)

    ProjectStorage.save_slides_data(project_id, base_dir, slides_list)
    reindex_slides(project_id, base_dir)

    # 实际插入后的编号（position 超出末尾时会被修正为末尾编号）
    new_slide_index = insert_pos + 1
    return {"new_slide_index": new_slide_index, "message": f"已在位置 {new_slide_index} 插入幻灯片「{title}」"}
