# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""视频配置缓存（按 project_id）。

智能体执行期间视频配置可能被 update_video_config 工具修改，因此提供失效接口：
工具写入新配置后调用 invalidate_video_config，下次 get_video_config 会重新加载最新值。
"""
import threading
from typing import Dict

from shared.config import get_config
from domain.dal.project_store import ProjectStorage

_cache: Dict[str, dict] = {}
_lock = threading.Lock()


def get_video_config(project_id: str) -> dict:
    """返回项目视频配置（aspect_ratio + resolution）。

    缓存命中直接返回；未命中时按 项目配置 → 全局配置 → 硬编码默认 加载并写入缓存。
    """
    with _lock:
        cached = _cache.get(project_id)
        if cached is not None:
            return cached

        try:
            vc = ProjectStorage.load_video_config(project_id, get_config().output_base_dir)
            if not vc or "aspect_ratio" not in vc or "resolution" not in vc:
                from video_pipeline.video_settings import load_video_settings
                global_vc = load_video_settings()
                vc = {"aspect_ratio": global_vc.aspect_ratio, "resolution": global_vc.resolution}
            if not vc.get("aspect_ratio") or not vc.get("resolution"):
                vc = {"aspect_ratio": "16:9", "resolution": "1920x1080"}
        except Exception:
            vc = {"aspect_ratio": "16:9", "resolution": "1920x1080"}

        result = {"aspect_ratio": vc["aspect_ratio"], "resolution": vc["resolution"]}
        _cache[project_id] = result
        return result


def invalidate_video_config(project_id: str) -> None:
    """清除指定项目的视频配置缓存，下次 get_video_config 会重新加载最新值。"""
    with _lock:
        _cache.pop(project_id, None)
