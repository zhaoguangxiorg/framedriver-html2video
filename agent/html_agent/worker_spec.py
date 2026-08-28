# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from agent.html_agent.worker_prompts import WORKER_PROMPT
from agent.html_agent.tools.read_style_spec import read_style_spec
from agent.html_agent.tools.read_slide_html import read_slide_html
from agent.html_agent.tools.read_full_content import read_full_content
from agent.html_agent.tools.save_slide_html import save_slide_html
from agent.html_agent.tools.save_slide_content import save_slide_content
from agent.llm.configurable_model import ConfigurableModelMiddleware


def build_worker_spec() -> dict:
    return {
        "name": "slide-designer",
        "description": "设计和修改单张PPT幻灯片。当需要生成或修改某一张幻灯片时调用此子智能体。每次只处理一张幻灯片。",
        "system_prompt": WORKER_PROMPT,
        "tools": [read_style_spec, read_full_content, read_slide_html, save_slide_html, save_slide_content],
        "middleware": [ConfigurableModelMiddleware()],
    }
