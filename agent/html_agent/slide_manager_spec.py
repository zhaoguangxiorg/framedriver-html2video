# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from agent.html_agent.slide_manager_prompts import SLIDE_MANAGER_PROMPT
from agent.html_agent.tools.read_slides_meta import read_slides_meta
from agent.html_agent.tools.delete_slide import delete_slide
from agent.html_agent.tools.move_slide import move_slide
from agent.html_agent.tools.insert_slide import insert_slide
from agent.llm.configurable_model import ConfigurableModelMiddleware


def build_slide_manager_spec() -> dict:
    return {
        "name": "slide-manager",
        "description": "管理幻灯片结构：删除、移动、插入幻灯片。不负责内容创作和HTML生成。",
        "system_prompt": SLIDE_MANAGER_PROMPT,
        "tools": [read_slides_meta, delete_slide, move_slide, insert_slide],
        "middleware": [ConfigurableModelMiddleware()],
    }
