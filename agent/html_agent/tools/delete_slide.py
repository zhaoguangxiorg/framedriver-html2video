# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

import shutil
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from shared.config import get_config
from domain.dal.project_store import ProjectStorage
from domain.service.slide_service import reindex_slides, shift_slide_dirs

@tool
def delete_slide(slide_index: int, config: RunnableConfig) -> dict:
    """删除指定幻灯片，自动清理目录并把后续幻灯片目录前移重新索引。

    Args:
        slide_index: 要删除的幻灯片编号

    Returns:
        包含 deleted_slide_index 和 message 的字典
    """
    project_id = config["configurable"]["project_id"]
    base_dir = get_config().output_base_dir
    project_dir = ProjectStorage.get_project_dir(project_id, base_dir)

    slides_data = ProjectStorage.load_slides_data(project_id, base_dir)
    new_slides = [s for s in slides_data if s.slide_index != slide_index]

    if len(new_slides) == len(slides_data):
        return {"deleted_slide_index": slide_index, "message": f"幻灯片 {slide_index} 不存在"}

    # 删除源目录
    slide_dir = project_dir / f"slide_{slide_index:02d}"
    if slide_dir.exists():
        shutil.rmtree(slide_dir)

    # 后续幻灯片目录整体前移 -1（从最小编号正序平移，避免覆盖）
    max_idx = max((s.slide_index for s in slides_data), default=0)
    if slide_index < max_idx:
        shift_slide_dirs(project_id, base_dir, slide_index + 1, max_idx, -1)

    # 保存数据然后重排
    ProjectStorage.save_slides_data(project_id, base_dir, new_slides)
    reindex_slides(project_id, base_dir)

    return {"deleted_slide_index": slide_index, "message": f"幻灯片 {slide_index} 已删除"}
