# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""LLM 工厂与模型缓存。

通过 `model_code` 从 `model_configs` 表加载配置并构造对应的
`BaseChatModel` 实例，使用 LRU 策略的 OrderedDict 缓存已创建的实例，
避免重复初始化。`get_llm()` 在不传参时返回默认模型，保持向后兼容。
"""
import threading
from collections import OrderedDict
from typing import Optional

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from domain.service.model_config_service import get_model_by_code, get_default_model


_MODEL_CACHE: "OrderedDict[str, BaseChatModel]" = OrderedDict()
_MODEL_CACHE_LOCK = threading.Lock()
_MODEL_CACHE_MAX = 16


def _peek_cache(model_code: str) -> Optional[BaseChatModel]:
    """仅查询缓存，不创建。命中时返回实例，未命中返回 None。"""
    with _MODEL_CACHE_LOCK:
        model = _MODEL_CACHE.get(model_code)
        if model is not None:
            _MODEL_CACHE.move_to_end(model_code)
        return model


def _get_or_create_model(model_code: str) -> BaseChatModel:
    """获取或创建指定 model_code 对应的模型实例。

    1. 先在缓存中查找（命中则 move_to_end 并返回）
    2. 未命中则从 model_config_service 加载配置（明文 api_key）
    3. 在锁外使用 init_chat_model 创建实例（耗时 IO 不持锁）
    4. 加锁写入缓存（若仍不存在），超出容量则淘汰最旧项
    """
    cached = _peek_cache(model_code)
    if cached is not None:
        return cached

    cfg = get_model_by_code(model_code)
    if cfg is None:
        raise ValueError(f"model config not found: {model_code}")

    model = init_chat_model(
        model=cfg["model_name"],
        model_provider=cfg["model_provider"],
        api_key=cfg["api_key"],
        base_url=cfg["base_url"] or None,
        temperature=cfg.get("temperature"),
        max_tokens=cfg.get("max_tokens"),
    )

    with _MODEL_CACHE_LOCK:
        if model_code not in _MODEL_CACHE:
            _MODEL_CACHE[model_code] = model
            while len(_MODEL_CACHE) > _MODEL_CACHE_MAX:
                _MODEL_CACHE.popitem(last=False)
        else:
            # 其他线程已先行写入，复用其结果
            model = _MODEL_CACHE[model_code]
            _MODEL_CACHE.move_to_end(model_code)

    return model


def get_llm(model_code: Optional[str] = None) -> BaseChatModel:
    """获取模型实例。

    - model_code 为 None：使用 `model_configs` 表中 is_default=1 的模型
    - model_code 指定：使用对应模型
    """
    if model_code is None:
        default_cfg = get_default_model()
        if default_cfg is None:
            raise ValueError("no default model configured")
        model_code = default_cfg["code"]
    return _get_or_create_model(model_code)
