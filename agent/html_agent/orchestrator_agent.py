# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from deepagents import create_deep_agent

from agent.llm.llm import get_llm
from agent.checkpointer import get_sqlite_checkpointer
from agent.llm.configurable_model import ConfigurableModelMiddleware, ModelContext
from agent.html_agent.orchestrator_prompts import ORCHESTRATOR_PROMPT
from agent.html_agent.worker_spec import build_worker_spec
from agent.html_agent.slide_manager_spec import build_slide_manager_spec
from agent.html_agent.tools.init_project import init_project
from agent.html_agent.tools.read_style_spec import read_style_spec
from agent.html_agent.tools.read_content_md import read_content_md
from agent.html_agent.tools.update_video_config import update_video_config
from agent.html_agent.tools.update_style_spec import update_style_spec
from agent.html_agent.tools.ask_user_tool import ask_user


def create_html_agent():
    checkpointer = get_sqlite_checkpointer()
    worker_spec = build_worker_spec()
    slide_manager_spec = build_slide_manager_spec()
    llm = get_llm()
    agent = create_deep_agent(
        model=llm,
        tools=[init_project, read_style_spec, read_content_md, update_video_config, update_style_spec, ask_user],
        subagents=[worker_spec, slide_manager_spec],
        system_prompt=ORCHESTRATOR_PROMPT,
        checkpointer=checkpointer,
        middleware=[ConfigurableModelMiddleware()],
        context_schema=ModelContext,
    )
    return agent
