# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

import shutil
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from shared.config import get_config
from domain.dal.project_store import ProjectStorage
from domain.service.slide_service import reindex_slides, shift_slide_dirs

@tool
def move_slide(from_index: int, to_index: int, config: RunnableConfig) -> dict:
    """移动幻灯片位置，自动重新索引并方向平移中间幻灯片目录。

    Args:
        from_index: 要移动的幻灯片当前编号
        to_index: 目标位置编号

    Returns:
        包含 message 的字典
    """
    project_id = config["configurable"]["project_id"]
    base_dir = get_config().output_base_dir
    project_dir = ProjectStorage.get_project_dir(project_id, base_dir)

    slides_data = ProjectStorage.load_slides_data(project_id, base_dir)
    slides_list = sorted(slides_data, key=lambda s: s.slide_index)

    # 找到 from_index 位置的幻灯片
    from_idx = None
    for i, s in enumerate(slides_list):
        if s.slide_index == from_index:
            from_idx = i
            break

    if from_idx is None:
        return {"message": f"幻灯片 {from_index} 不存在"}

    # 取出并插入到目标位置
    moved = slides_list.pop(from_idx)
    # to_index 是目标位置编号（要变成第几张），列表插入位置 = to_index - 1
    insert_pos = max(0, min(to_index - 1, len(slides_list)))
    slides_list.insert(insert_pos, moved)

    # 实际生效的目标编号（to_index 超出范围时会被修正）
    to_pos = insert_pos + 1

    # 先把源目录移到临时目录，避免被平移覆盖
    tmp_dir = project_dir / "_move_tmp"
    src_dir = project_dir / f"slide_{from_index:02d}"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    if src_dir.exists():
        src_dir.rename(tmp_dir)

    # 中间目录方向平移
    if from_index < to_pos:
        # 前移 -1：slide_{from+1}..slide_{to_pos}
        shift_slide_dirs(project_id, base_dir, from_index + 1, to_pos, -1)
    elif from_index > to_pos:
        # 后移 +1：slide_{to_pos}..slide_{from-1}
        shift_slide_dirs(project_id, base_dir, to_pos, from_index - 1, +1)

    # 源目录放回目标位置
    if tmp_dir.exists():
        tmp_dir.rename(project_dir / f"slide_{to_pos:02d}")

    # 保存并重排
    ProjectStorage.save_slides_data(project_id, base_dir, slides_list)
    reindex_slides(project_id, base_dir)

    return {"message": f"幻灯片已从 {from_index} 移动到 {to_pos} 位置"}
