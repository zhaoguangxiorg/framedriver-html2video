# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from deepagents import create_deep_agent

from agent.llm.llm import get_llm
from agent.checkpointer import get_sqlite_checkpointer
from agent.llm.configurable_model import ConfigurableModelMiddleware, ModelContext
from agent.content_agent.prompts import CONTENT_SYSTEM_PROMPT
from agent.content_agent.tools.read_content import read_content
from agent.content_agent.tools.save_content import save_content


def create_content_agent():
    checkpointer = get_sqlite_checkpointer()
    llm = get_llm()
    agent = create_deep_agent(
        model=llm,
        tools=[read_content, save_content],
        system_prompt=CONTENT_SYSTEM_PROMPT,
        checkpointer=checkpointer,
        middleware=[ConfigurableModelMiddleware()],
        context_schema=ModelContext,
    )
    return agent
