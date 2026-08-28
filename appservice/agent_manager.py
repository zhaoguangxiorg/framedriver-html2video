# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from agent.content_agent.agent import create_content_agent
from agent.html_agent.orchestrator_agent import create_html_agent


class AgentManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._content_agent = create_content_agent()
        self._html_agent = create_html_agent()
        self._initialized = True

    def get_content_agent(self):
        return self._content_agent

    def get_html_agent(self):
        return self._html_agent
