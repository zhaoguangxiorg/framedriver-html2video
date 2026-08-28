# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""可配置模型中间件。

通过 `ConfigurableModelMiddleware` 在 Agent 调用模型之前根据
`request.runtime.context["model_code"]` 切换底层 `BaseChatModel` 实例，
实现运行时模型切换。对未携带 context 的子 Agent（如 WorkerAgent），
使用 `contextvars.ContextVar` 作为回退机制，使其能继承父 Agent 的 model_code。
"""
import contextvars
from typing import TypedDict

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ExtendedModelResponse,
    ModelResponse,
)
from langchain_core.messages import AIMessage

from agent.llm.llm import _get_or_create_model, _peek_cache


class ModelContext(TypedDict, total=False):
    """运行时上下文中用于指定模型的字段。"""
    model_code: str


# 子 Agent 传播 model_code 的回退通道
_model_code_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "model_code", default=None
)


def _is_anthropic_model(model) -> bool:
    """判断一个模型实例是否为 Anthropic 提供方。

    优先通过 `ls_provider` 属性判断；不可用时回退到类名匹配。
    """
    if model is None:
        return False
    provider = getattr(model, "ls_provider", None)
    if provider:
        return str(provider).lower() == "anthropic"
    cls_name = type(model).__name__.lower()
    return "anthropic" in cls_name


class ConfigurableModelMiddleware(AgentMiddleware):
    """根据 runtime.context 中的 model_code 动态切换模型。"""

    def wrap_model_call(
        self, request, handler
    ) -> ModelResponse | AIMessage | ExtendedModelResponse:
        model_code = self._resolve_model_code(request)

        if not model_code:
            return handler(request)

        cached = _peek_cache(model_code)
        if cached is not None and cached is request.model:
            return handler(request)

        new_model = _get_or_create_model(model_code)
        new_request = request.override(model=new_model)

        # 跨 provider 切换：从 Anthropic 切到非 Anthropic 时剥离 cache_control
        if (
            request.model_settings
            and "cache_control" in request.model_settings
            and _is_anthropic_model(request.model)
            and not _is_anthropic_model(new_model)
        ):
            new_settings = {
                k: v for k, v in request.model_settings.items() if k != "cache_control"
            }
            new_request = new_request.override(model_settings=new_settings)

        return handler(new_request)

    async def awrap_model_call(
        self, request, handler
    ) -> ModelResponse | AIMessage | ExtendedModelResponse:
        model_code = self._resolve_model_code(request)

        if not model_code:
            return await handler(request)

        cached = _peek_cache(model_code)
        if cached is not None and cached is request.model:
            return await handler(request)

        new_model = _get_or_create_model(model_code)
        new_request = request.override(model=new_model)

        if (
            request.model_settings
            and "cache_control" in request.model_settings
            and _is_anthropic_model(request.model)
            and not _is_anthropic_model(new_model)
        ):
            new_settings = {
                k: v for k, v in request.model_settings.items() if k != "cache_control"
            }
            new_request = new_request.override(model_settings=new_settings)

        return await handler(new_request)

    @staticmethod
    def _resolve_model_code(request) -> str | None:
        """从 runtime.context 或 contextvar 中解析 model_code。

        解析成功后写入 contextvar，便于子 Agent 继承。
        """
        ctx = request.runtime.context if request.runtime else None
        model_code = None
        if isinstance(ctx, dict):
            model_code = ctx.get("model_code")

        if not model_code:
            model_code = _model_code_var.get()

        if model_code:
            _model_code_var.set(model_code)

        return model_code
