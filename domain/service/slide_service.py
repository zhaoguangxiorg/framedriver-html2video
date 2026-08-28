# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from pathlib import Path
from typing import Union

from domain.dal.project_store import ProjectStorage, SlideData


def reindex_slides(project_id: str, base_dir: Union[str, Path]) -> None:
    """重排幻灯片索引，使 slide_index 从 1 开始连续递增（仅更新元数据）。

    目录的平移由 insert/delete/move 工具调用 shift_slide_dirs 负责，
    本函数只负责把 slides_data.json 的 slide_index 与 html_path 更新为连续值，
    与平移后的目录保持一致。

    不创建目录、不删除目录、不重命名目录。
    """
    slides_data = ProjectStorage.load_slides_data(project_id, base_dir)

    new_slides = []
    for i, slide in enumerate(slides_data, start=1):
        slide.slide_index = i
        slide.html_path = f"slide_{i:02d}/slide.html"
        new_slides.append(slide)

    ProjectStorage.save_slides_data(project_id, base_dir, new_slides)


def shift_slide_dirs(
    project_id: str,
    base_dir: Union[str, Path],
    start: int,
    end: int,
    delta: int,
) -> None:
    """方向平移 slide_XX/ 目录，避免逐个重命名时的索引冲突。

    - delta=+1（后移）：从 end 倒序向 start 平移，slide_{i} -> slide_{i+1}
    - delta=-1（前移）：从 start 正序向 end 平移，slide_{i} -> slide_{i-1}

    只平移实际存在的目录，不存在的目录跳过（其元数据由 reindex_slides 修正）。
    平移区间 [start, end] 之外的目录保持不变。
    """
    base_dir = Path(base_dir)
    project_dir = ProjectStorage.get_project_dir(project_id, base_dir)

    if delta > 0:
        indices = range(end, start - 1, -1)
    else:
        indices = range(start, end + 1)

    for i in indices:
        src = project_dir / f"slide_{i:02d}"
        if not src.exists():
            continue
        dst = project_dir / f"slide_{i + delta:02d}"
        src.rename(dst)
