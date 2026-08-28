# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""模型配置服务层（业务规则）。

提供 model_configs 表的 CRUD 业务规则：api_key 加密/解密/脱敏、
code 生成、联合唯一性校验、默认模型管理等。
数据访问委托给 domain.dal.model_config_dal（DAL 返回原始 dict，
api_key 为密文），本层负责解密/脱敏/组装后再对外返回。
"""
from typing import Optional, List

from shared.crypto import encrypt, decrypt
from domain.dal.model_config_dal import (
    list_model_rows,
    get_model_row_by_id,
    get_model_row_by_code,
    get_default_model_row,
    get_row_by_provider_model,
    insert_model_row,
    update_model_row,
    delete_model_row,
    clear_default_flags,
)


def mask_api_key(plaintext: str) -> str:
    """脱敏 api_key：保留前3后4，中间用 ****；长度不足8位则全 ****。"""
    if not plaintext or len(plaintext) < 8:
        return "****"
    return f"{plaintext[:3]}****{plaintext[-4:]}"


def _raw_to_dict(raw: dict, api_key_value: str) -> dict:
    """把 DAL 原始 dict 组装成对外 dict，api_key 用传入值（明文或脱敏串）替换。"""
    return {
        "id": raw["id"],
        "name": raw["name"],
        "code": raw["code"],
        "model_name": raw["model_name"],
        "api_key": api_key_value,
        "base_url": raw["base_url"],
        "model_provider": raw["model_provider"],
        "is_default": raw["is_default"],
        "is_fallback": raw["is_fallback"],
        "temperature": raw["temperature"],
        "max_tokens": raw["max_tokens"],
        "enabled": raw["enabled"],
        "created_at": raw["created_at"].isoformat() if raw["created_at"] else None,
        "updated_at": raw["updated_at"].isoformat() if raw["updated_at"] else None,
    }


def _raw_to_plain_dict(raw: dict) -> dict:
    """转换并解密 api_key，返回明文。"""
    plaintext = decrypt(raw["api_key"]) if raw["api_key"] else ""
    return _raw_to_dict(raw, plaintext)


def _raw_to_masked_dict(raw: dict) -> dict:
    """转换并对 api_key 脱敏。"""
    plaintext = decrypt(raw["api_key"]) if raw["api_key"] else ""
    return _raw_to_dict(raw, mask_api_key(plaintext))


def get_model_by_code(code: str) -> Optional[dict]:
    """按 code 查询，返回明文 api_key；不存在返回 None。"""
    raw = get_model_row_by_code(code)
    return _raw_to_plain_dict(raw) if raw else None


def get_default_model() -> Optional[dict]:
    """返回 is_default=1 的模型（明文 api_key）；不存在返回 None。"""
    raw = get_default_model_row()
    return _raw_to_plain_dict(raw) if raw else None


def create_model(data: dict) -> dict:
    """创建模型，加密 api_key 入库；若 is_default=1 则清空其他默认。

    code 自动生成，规则为 `{model_provider}-{model_name}`。
    联合唯一约束：(model_provider, model_name)。

    Raises:
        ValueError: 该提供商+模型名已存在。
    """
    model_provider = (data.get("model_provider") or "").strip()
    model_name = (data.get("model_name") or "").strip()
    if not model_provider or not model_name:
        raise ValueError("model_provider 和 model_name 不能为空")

    code = f"{model_provider}-{model_name}"

    # 联合唯一性检查（provider + model_name）
    if get_row_by_provider_model(model_provider, model_name) is not None:
        raise ValueError("该提供商+模型名已存在")

    is_default = int(data.get("is_default") or 0)
    if is_default == 1:
        # 清空其他默认模型
        clear_default_flags()

    enabled_val = data.get("enabled")
    enabled = int(enabled_val) if enabled_val is not None else 1

    fields = {
        "name": data.get("name", "") or model_name,
        "code": code,
        "model_name": model_name,
        "api_key": encrypt(data.get("api_key") or ""),
        "base_url": data.get("base_url"),
        "model_provider": model_provider,
        "is_default": is_default,
        "is_fallback": int(data.get("is_fallback") or 0),
        "temperature": data.get("temperature"),
        "max_tokens": data.get("max_tokens"),
        "enabled": enabled,
    }
    raw = insert_model_row(fields)
    return _raw_to_plain_dict(raw)


def update_model(model_id: int, data: dict) -> Optional[dict]:
    """更新模型字段；api_key 为空字符串或未传时保留原值。

    若 provider 或 model_name 变化，code 自动重算为 `{provider}-{model_name}`。
    联合唯一约束：(model_provider, model_name)。

    Raises:
        ValueError: 该提供商+模型名已存在。
    """
    raw = get_model_row_by_id(model_id)
    if raw is None:
        return None

    # 计算新的 provider / model_name
    new_provider = data.get("model_provider") if data.get("model_provider") is not None else raw["model_provider"]
    new_model_name = data.get("model_name") if data.get("model_name") is not None else raw["model_name"]
    new_provider = (new_provider or "").strip()
    new_model_name = (new_model_name or "").strip()

    # 联合唯一性检查（与其他模型冲突时抛错）
    if get_row_by_provider_model(new_provider, new_model_name, exclude_id=model_id) is not None:
        raise ValueError("该提供商+模型名已存在")

    fields = {}

    # provider / model_name 变化时重算 code
    if new_provider != raw["model_provider"] or new_model_name != raw["model_name"]:
        fields["code"] = f"{new_provider}-{new_model_name}"
    fields["model_provider"] = new_provider
    fields["model_name"] = new_model_name

    # api_key：未传或空字符串保留原值；非空则加密更新
    if "api_key" in data and data["api_key"]:
        fields["api_key"] = encrypt(data["api_key"])

    # name：未传时默认沿用 model_name（便于展示）
    if "name" in data and data["name"] is not None:
        fields["name"] = data["name"]
    if "base_url" in data:
        fields["base_url"] = data["base_url"]
    if "temperature" in data:
        fields["temperature"] = data["temperature"]
    if "max_tokens" in data:
        fields["max_tokens"] = data["max_tokens"]
    if "is_fallback" in data and data["is_fallback"] is not None:
        fields["is_fallback"] = int(data["is_fallback"])
    if "enabled" in data and data["enabled"] is not None:
        fields["enabled"] = int(data["enabled"])

    # is_default：若设为 1，先清空其他默认（等价于原逻辑：清其他行再置当前行为默认）
    if data.get("is_default") == 1:
        clear_default_flags()
        fields["is_default"] = 1
    elif "is_default" in data and data["is_default"] is not None:
        fields["is_default"] = int(data["is_default"])

    updated_raw = update_model_row(model_id, fields)
    return _raw_to_plain_dict(updated_raw) if updated_raw else None


def delete_model(model_id: int) -> bool:
    """删除模型；存在并删除返回 True，不存在返回 False。"""
    return delete_model_row(model_id)


def list_models_masked(enabled_only: bool = False) -> List[dict]:
    """返回模型列表，api_key 脱敏。供 API 列表接口使用。"""
    rows = list_model_rows(enabled_only=enabled_only)
    return [_raw_to_masked_dict(r) for r in rows]


def get_model_by_id_masked(model_id: int) -> Optional[dict]:
    """按 id 查询，api_key 脱敏。"""
    raw = get_model_row_by_id(model_id)
    return _raw_to_masked_dict(raw) if raw else None
