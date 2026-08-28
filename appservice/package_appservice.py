# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""PPT 打包业务层。

生成单文件 PPT.html（离线查看），以及在线查看的公共组装逻辑。
"""
import json
import logging
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import Response

from shared.config import get_config
from domain.dal.project_store import ProjectStorage

logger = logging.getLogger("appservice.package")

# 模板文件路径（项目根目录 / resource / ppt_templates / ppt_viewer.html）
_TEMPLATE_PATH = Path(__file__).parent.parent / "resource" / "ppt_templates" / "ppt_viewer.html"


def _project_dir(project_id: str) -> Path:
    return get_config().output_base_dir / "html_slides" / project_id


def _escape_script_close(content: str) -> str:
    """转义 </script> 标签，防止破坏外层 <script type="text/html"> 模板。

    type="text/html" 的 script 标签不会被浏览器解析，
    唯一的风险是内容中包含 </script> 会导致标签提前结束。
    """
    return content.replace("</script>", "<\\/script>")


def _build_slide_templates(project_dir: Path, slides_data) -> str:
    """读取每个 slide.html，组装成 <script type="text/html"> 模板块。"""
    templates = []
    for slide in slides_data:
        idx = slide.slide_index
        slide_html_path = project_dir / f"slide_{idx:02d}" / "slide.html"

        if not slide_html_path.exists():
            logger.warning("slide.html not found: %s", slide_html_path)
            continue

        html_content = slide_html_path.read_text(encoding="utf-8")
        escaped_html = _escape_script_close(html_content)

        template = (
            f'<script type="text/html" id="slide-{idx}">\n'
            f'{escaped_html}\n'
            f'</script>'
        )
        templates.append(template)

    return "\n\n".join(templates)


def _build_slides_json(slides_data) -> str:
    """构建幻灯片元数据 JSON（仅包含 index 和 title）。"""
    items = []
    for slide in slides_data:
        items.append({
            "index": slide.slide_index,
            "title": slide.title or f"幻灯片 {slide.slide_index}",
        })
    return json.dumps(items, ensure_ascii=False)


def _build_slide_size(project_id: str, base_dir) -> str:
    """从 video_config.json 读取分辨率，构建幻灯片尺寸 JSON。"""
    try:
        video_config = ProjectStorage.load_video_config(project_id, base_dir)
        resolution = video_config.get("resolution", "1920x1080")
    except (FileNotFoundError, Exception):
        resolution = "1920x1080"

    parts = resolution.split("x")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        slide_size = {"width": int(parts[0]), "height": int(parts[1])}
    else:
        slide_size = {"width": 1920, "height": 1080}

    return json.dumps(slide_size, ensure_ascii=False)


def _derive_filename(project_id: str) -> str:
    """从 project_id 生成下载文件名。

    project_id 格式可能是 "20260702_173600_智能体介绍" 或 UUID 格式。
    取最后一个部分作为项目名。
    """
    # 去掉时间戳前缀（YYYYMMDD_HHMMSS_）
    parts = project_id.split("_")
    if len(parts) >= 3 and parts[0].isdigit() and len(parts[0]) == 8:
        project_name = "_".join(parts[2:])
    else:
        project_name = project_id

    if not project_name:
        project_name = "presentation"

    return f"PPT_{project_name}.html"


def download_ppt(project_id: str):
    """下载 PPT.html 单文件。"""

    ppt_html = _generate_ppt_html(project_id)
    filename = _derive_filename(project_id)

    return Response(
        content=ppt_html,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


def view_ppt(project_id: str):
    """在线查看 PPT.html（内联渲染，不触发下载）。

    同时在项目目录下生成 ppt.html 文件，供线上访问。
    可通过 ?slide=N 参数指定初始聚焦的幻灯片（1-based）。
    """

    ppt_html = _generate_ppt_html(project_id)

    # 在项目目录下生成 ppt.html 文件
    project_dir = _project_dir(project_id)
    ppt_file = project_dir / "ppt.html"
    ppt_file.write_text(ppt_html, encoding="utf-8")

    return Response(
        content=ppt_html,
        media_type="text/html; charset=utf-8",
    )


def _generate_ppt_html(project_id: str) -> str:
    """组装完整的 PPT.html 内容（公共逻辑，download 和 view 共用）。"""

    config = get_config()
    project_dir = _project_dir(project_id)

    # 1. 校验项目目录存在
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    # 2. 读取 slides_data.json
    try:
        slides_data = ProjectStorage.load_slides_data(project_id, config.output_base_dir)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="slides_data.json not found")

    if not slides_data:
        raise HTTPException(status_code=404, detail="No slides found")

    # 3. 读取每个 slide.html 并组装模板
    slide_templates = _build_slide_templates(project_dir, slides_data)
    if not slide_templates:
        raise HTTPException(status_code=400, detail="No valid slide.html files found")

    # 4. 构建幻灯片元数据 JSON
    slides_json = _build_slides_json(slides_data)

    # 5. 构建幻灯片尺寸 JSON（从 video_config.json 读取）
    slide_size = _build_slide_size(project_id, config.output_base_dir)

    # 6. 读取模板文件
    if not _TEMPLATE_PATH.exists():
        raise HTTPException(status_code=500, detail="ppt_viewer.html template not found")
    template_content = _TEMPLATE_PATH.read_text(encoding="utf-8")

    # 7. 填充占位符
    ppt_html = template_content.replace("{slide_templates}", slide_templates)
    ppt_html = ppt_html.replace("{slides_json}", slides_json)
    ppt_html = ppt_html.replace("{slide_size}", slide_size)

    return ppt_html
