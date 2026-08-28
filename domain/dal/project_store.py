# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

import json
from pathlib import Path
from typing import Union, List
from shared.file_utils import ensure_dir
from domain.entities.schemas import SlideData


class ProjectStorage:
    @staticmethod
    def get_project_dir(project_id: str, base_dir: Union[str, Path]) -> Path:
        base_dir = Path(base_dir)
        project_dir = base_dir / "html_slides" / project_id
        return project_dir

    @staticmethod
    def save_slides_data(project_id: str, base_dir: Union[str, Path], data: List[SlideData]) -> None:
        project_dir = ProjectStorage.get_project_dir(project_id, base_dir)
        ensure_dir(project_dir)
        slides_file = project_dir / "slides_data.json"
        slides_dict = [slide.model_dump() for slide in data]
        with open(slides_file, "w", encoding="utf-8") as f:
            json.dump(slides_dict, f, ensure_ascii=False, indent=2)

    @staticmethod
    def load_slides_data(project_id: str, base_dir: Union[str, Path]) -> List[SlideData]:
        project_dir = ProjectStorage.get_project_dir(project_id, base_dir)
        slides_file = project_dir / "slides_data.json"
        with open(slides_file, "r", encoding="utf-8") as f:
            slides_dict = json.load(f)
        return [SlideData(**item) for item in slides_dict]

    @staticmethod
    def save_video_config(project_id: str, base_dir: Union[str, Path], config: dict) -> None:
        project_dir = ProjectStorage.get_project_dir(project_id, base_dir)
        ensure_dir(project_dir)
        config_file = project_dir / "video_config.json"
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    @staticmethod
    def load_video_config(project_id: str, base_dir: Union[str, Path]) -> dict:
        project_dir = ProjectStorage.get_project_dir(project_id, base_dir)
        config_file = project_dir / "video_config.json"
        if not config_file.exists():
            return {}
        with open(config_file, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def save_style_spec(project_id: str, base_dir: Union[str, Path], content: str) -> None:
        project_dir = ProjectStorage.get_project_dir(project_id, base_dir)
        ensure_dir(project_dir)
        spec_file = project_dir / "style_spec.md"
        with open(spec_file, "w", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def load_style_spec(project_id: str, base_dir: Union[str, Path]) -> str:
        project_dir = ProjectStorage.get_project_dir(project_id, base_dir)
        spec_file = project_dir / "style_spec.md"
        if not spec_file.exists():
            return ""
        with open(spec_file, "r", encoding="utf-8") as f:
            return f.read()

    # ---- Slide content/narration as separate Markdown files ----

    @staticmethod
    def _slide_dir(project_id: str, slide_index: int, base_dir: Union[str, Path]) -> Path:
        return ProjectStorage.get_project_dir(project_id, base_dir) / f"slide_{slide_index:02d}"

    @staticmethod
    def save_slide_content(project_id: str, slide_index: int, content: str, base_dir: Union[str, Path]) -> None:
        slide_dir = ProjectStorage._slide_dir(project_id, slide_index, base_dir)
        ensure_dir(slide_dir)
        with open(slide_dir / "content.md", "w", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def load_slide_content(project_id: str, slide_index: int, base_dir: Union[str, Path]) -> str:
        slide_dir = ProjectStorage._slide_dir(project_id, slide_index, base_dir)
        content_file = slide_dir / "content.md"
        if not content_file.exists():
            return ""
        with open(content_file, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def save_slide_narration(project_id: str, slide_index: int, narration: str, base_dir: Union[str, Path]) -> None:
        slide_dir = ProjectStorage._slide_dir(project_id, slide_index, base_dir)
        ensure_dir(slide_dir)
        with open(slide_dir / "narration.md", "w", encoding="utf-8") as f:
            f.write(narration)

    @staticmethod
    def load_slide_narration(project_id: str, slide_index: int, base_dir: Union[str, Path]) -> str:
        slide_dir = ProjectStorage._slide_dir(project_id, slide_index, base_dir)
        narration_file = slide_dir / "narration.md"
        if not narration_file.exists():
            return ""
        with open(narration_file, "r", encoding="utf-8") as f:
            return f.read()
