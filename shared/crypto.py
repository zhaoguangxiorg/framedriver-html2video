# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""Fernet 对称加密/解密工具，用于 model_configs.api_key 字段。

密钥从 .env 的 MODEL_KEY_ENCRYPTION_KEY 读取；若不存在则自动生成
新的 Fernet 密钥并追加写入 .env 文件（文件不存在时创建）。
"""
import os
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv

# 项目根目录（与 shared/config.py 一致）
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# 环境变量名
_ENV_KEY = "MODEL_KEY_ENCRYPTION_KEY"

# 模块级缓存，避免重复读取/生成
_fernet = None


def _get_fernet() -> Fernet:
    """获取 Fernet 实例，密钥缺失时自动生成并写回 .env。"""
    global _fernet
    if _fernet is not None:
        return _fernet

    load_dotenv(_PROJECT_ROOT / ".env")
    key = os.getenv(_ENV_KEY)

    if not key:
        # .env 中没有该密钥，自动生成并追加写入
        key = Fernet.generate_key().decode("utf-8")
        _append_env_key(key)
        # 同步到当前进程环境变量，避免同进程内重复生成
        os.environ[_ENV_KEY] = key

    _fernet = Fernet(key)
    return _fernet


def _append_env_key(key: str) -> None:
    """将密钥追加写入 .env 文件（文件不存在则创建，已有内容不覆盖）。"""
    env_path = _PROJECT_ROOT / ".env"
    line = f"{_ENV_KEY}={key}\n"

    # 读取已有内容，判断是否需要补一个换行
    existing = ""
    if env_path.exists():
        existing = env_path.read_text(encoding="utf-8")

    prefix = "" if (not existing or existing.endswith("\n")) else "\n"

    with open(env_path, "a", encoding="utf-8") as f:
        f.write(prefix + line)


def encrypt(plaintext: str) -> str:
    """加密明文字符串，返回密文字符串。"""
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    """解密密文字符串，返回明文。"""
    return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
