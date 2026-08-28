# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

from typing import Tuple

from domain.entities.schemas import VideoConfig

__all__ = ["VideoConfig", "parse_resolution"]


def parse_resolution(resolution_str: str) -> Tuple[int, int]:
    """
    解析分辨率字符串为宽高元组。

    Args:
        resolution_str: 分辨率字符串，格式如 "1920x1080" 或 "1280*720"

    Returns:
        (width, height) 元组

    Raises:
        ValueError: 分辨率格式不正确时
    """
    resolution_str = resolution_str.strip().lower()
    for sep in ["x", "*"]:
        if sep in resolution_str:
            parts = resolution_str.split(sep)
            if len(parts) == 2:
                try:
                    width = int(parts[0].strip())
                    height = int(parts[1].strip())
                    if width > 0 and height > 0:
                        return (width, height)
                except ValueError:
                    pass
    raise ValueError(f"Invalid resolution format: {resolution_str}. Expected format like '1920x1080'")
