# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""视频生成业务层。

承接视频生成全部业务逻辑：任务表管理、字幕字体预检、一键生成、
高级单张生成与分段合成、进度查询、文件下载。
api 层只负责路由与参数透传。
"""
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

from fastapi import HTTPException
from fastapi.responses import FileResponse

from shared.config import get_config

logger = logging.getLogger("appservice.video")


# In-memory task table. Keyed by project_id. For a real deployment this
# would live in the database; for now the spec keeps things simple.
_tasks: Dict[str, dict] = {}
_tasks_lock = threading.Lock()


def _project_dir(project_id: str) -> Path:
    return get_config().output_base_dir / "html_slides" / project_id


def _get_or_create_task(project_id: str) -> dict:
    with _tasks_lock:
        t = _tasks.get(project_id)
        if t is None:
            t = {
                "task_id": str(uuid.uuid4()),
                "status": "idle",  # idle / running / completed / failed
                "percent": 0,
                "current_step": "",
                "error": None,
                "started_at": None,
                "finished_at": None,
            }
            _tasks[project_id] = t
        return t


# 用户可持久化的视频设置白名单（前端表单可改，保存到项目 video_config.json）
_USER_SETTING_FIELDS = ("voice_persona", "enable_subtitles", "subtitle_color")


def _save_user_video_settings(project_id: str, settings: dict) -> None:
    """把用户前端表单设置持久化到项目 video_config.json（仅白名单字段）。

    只保存用户可配置字段（语音人设/字幕开关/字幕颜色），不碰由智能体
    锁定的 aspect_ratio/resolution 等。保存后失效视频配置缓存，下次读取生效。
    """
    from domain.dal.project_store import ProjectStorage
    from video_pipeline.video_config_cache import invalidate_video_config

    if not settings:
        return
    new_fields = {k: v for k, v in settings.items() if k in _USER_SETTING_FIELDS and v is not None}
    if not new_fields:
        return
    base_dir = get_config().output_base_dir
    existing = ProjectStorage.load_video_config(project_id, base_dir)
    ProjectStorage.save_video_config(project_id, base_dir, {**existing, **new_fields})
    invalidate_video_config(project_id)


def _check_subtitle_font(project_id: str, request_config: dict) -> Optional[str]:
    """预检字幕字体：启用了字幕且配置了字体名时解析字体文件。

    返回错误文案（应使任务失败）；None 表示通过。
    """
    from video_pipeline.font_resolver import resolve_subtitle_font
    from video_pipeline.video_settings import load_video_settings, apply_aspect_ratio
    from domain.dal.project_store import ProjectStorage

    try:
        video_config = load_video_settings()
        project_config = ProjectStorage.load_video_config(project_id, get_config().output_base_dir)
        if project_config:
            for k, v in project_config.items():
                if v is not None and hasattr(video_config, k):
                    setattr(video_config, k, v)
            video_config = apply_aspect_ratio(video_config)
        # 请求参数覆盖字幕开关
        if "enable_subtitles" in request_config and request_config["enable_subtitles"] is not None:
            video_config.enable_subtitles = request_config["enable_subtitles"]
        if not (video_config.enable_subtitles and (video_config.subtitle_font or video_config.subtitle_font_file)):
            return None  # 无需字幕，不预检
        font_file, font_error = resolve_subtitle_font(
            video_config.subtitle_font, video_config.subtitle_font_file
        )
        if font_file is None:
            return (
                f"未找到字幕字体文件：{font_error or '未知错误'}。"
                f"如需继续生成视频，请关闭字幕，或修正 config/video_settings.json 中 "
                f"subtitle_font/subtitle_font_file 配置后重试。"
            )
        return None
    except Exception:
        return None  # 配置读取异常不阻塞生成（保守）


def _run_video_generation(project_id: str, config: dict) -> None:
    task = _get_or_create_task(project_id)
    with _tasks_lock:
        task.update({
            "status": "running",
            "percent": 0,
            "current_step": "准备生成",
            "error": None,
            "started_at": time.time(),
            "finished_at": None,
        })

    def _progress_cb(percent: int, step: str) -> None:
        with _tasks_lock:
            task["percent"] = percent
            task["current_step"] = step

    try:
        precheck_error = _check_subtitle_font(project_id, config)
        if precheck_error:
            logger.warning("subtitle font precheck failed for %s: %s", project_id, precheck_error)
            with _tasks_lock:
                task.update({
                    "status": "failed",
                    "error": precheck_error,
                    "percent": 0,
                    "finished_at": time.time(),
                })
            return
        # Hook print() to also update progress: monkey-patch stdout is
        # overkill, so we just step the progress bar discretely before
        # and after the call. The pipeline prints finer-grained steps
        # but we coarse-grain to 4 phases.
        _progress_cb(10, "生成图片")
        from video_pipeline.generate_video import generate_video

        result = generate_video(
            project_id=project_id,
            voice_persona=config.get("voice_persona"),
            aspect_ratio=config.get("aspect_ratio"),
            resolution=config.get("resolution"),
            enable_subtitles=config.get("enable_subtitles"),
        )
        _progress_cb(100, "完成")
        with _tasks_lock:
            task["status"] = "completed"
            task["result"] = result
            task["warnings"] = (result or {}).get("warnings", [])
            task["finished_at"] = time.time()
    except Exception as exc:  # noqa: BLE001
        logger.exception("video generation failed for %s", project_id)
        with _tasks_lock:
            task["status"] = "failed"
            task["error"] = str(exc)
            task["finished_at"] = time.time()


def get_voice_personas():
    """Get available voice personas for frontend selection."""
    from video_pipeline.voice_personas import list_voice_personas
    personas = list_voice_personas()
    return [
        {"id": pid, "name": p["name"]}
        for pid, p in personas.items()
    ]


def get_project_config(project_id: str):
    """项目配置与全局默认合并：项目缺字段自动回退全局默认，已有字段优先。"""
    from video_pipeline.video_settings import load_video_settings
    cfg = load_video_settings()
    project_dir = _project_dir(project_id)
    config_path = project_dir / "video_config.json"
    if config_path.exists():
        import json
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            if data:
                merged = cfg.model_dump()
                merged.update({k: v for k, v in data.items() if v is not None})
                return merged
        except (json.JSONDecodeError, IOError):
            pass
    return cfg.model_dump()


def start_generation(project_id: str, config: dict):
    project_dir = _project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="project not found")

    task = _get_or_create_task(project_id)
    if task.get("status") == "running":
        raise HTTPException(status_code=409, detail="generation already running")

    t = threading.Thread(
        target=_run_video_generation,
        args=(project_id, config),
        daemon=True,
    )
    t.start()
    return {"task_id": task["task_id"], "status": "running"}


def get_progress(project_id: str):
    task = _get_or_create_task(project_id)
    has_video = (_project_dir(project_id) / "final_video.mp4").exists()
    with _tasks_lock:
        return {
            "status": task["status"],
            "percent": task["percent"],
            "current_step": task["current_step"],
            "error": task["error"],
            "has_video": has_video,
            "warnings": task.get("warnings", []),
        }


def download(project_id: str):
    final = _project_dir(project_id) / "final_video.mp4"
    if not final.exists():
        raise HTTPException(status_code=404, detail="final_video.mp4 not found")
    return FileResponse(
        path=str(final),
        media_type="video/mp4",
        filename=f"{project_id}.mp4",
    )


# ---------------------------------------------------------------------------
# 高级生成模式 — 单页视频 & 分段合成
# ---------------------------------------------------------------------------

_slide_tasks: Dict[str, dict] = {}
_slide_tasks_lock = threading.Lock()

_concat_task: Dict[str, dict] = {}
_concat_task_lock = threading.Lock()

# 选段合成（片段）任务表：每项目同时只能进行一个片段合成
_clip_task: Dict[str, dict] = {}
_clip_task_lock = threading.Lock()


def _get_or_create_slide_task(key: str) -> dict:
    with _slide_tasks_lock:
        t = _slide_tasks.get(key)
        if t is None:
            t = {"status": "idle", "error": None}
            _slide_tasks[key] = t
        return t


def _get_or_create_concat_task(project_id: str) -> dict:
    with _concat_task_lock:
        t = _concat_task.get(project_id)
        if t is None:
            t = {"status": "idle", "error": None}
            _concat_task[project_id] = t
        return t


def _run_slide_video_generation(project_id: str, slide_index: int, user_settings: dict = None) -> None:
    task_key = f"{project_id}:{slide_index}"
    task = _get_or_create_slide_task(task_key)
    with _slide_tasks_lock:
        task.update({"status": "running", "error": None})

    try:
        # 持久化用户设置（语音人设/字幕开关/字幕颜色）到项目配置
        if user_settings:
            try:
                _save_user_video_settings(project_id, user_settings)
            except Exception:
                logger.warning("save user video settings failed for %s", project_id, exc_info=True)

        from domain.dal.project_store import ProjectStorage
        from video_pipeline.video_settings import load_video_settings, apply_aspect_ratio
        from video_pipeline.advanced_generate import generate_slide_video

        precheck_error = _check_subtitle_font(project_id, {})
        if precheck_error:
            raise RuntimeError(precheck_error)

        video_config = load_video_settings()

        project_config = ProjectStorage.load_video_config(
            project_id, get_config().output_base_dir
        )
        if project_config:
            for key, value in project_config.items():
                if value is not None and hasattr(video_config, key):
                    setattr(video_config, key, value)
            video_config = apply_aspect_ratio(video_config)

        result = generate_slide_video(project_id, slide_index, video_config)
        with _slide_tasks_lock:
            task["status"] = "completed"
            task["result"] = result
            task["error"] = None
    except Exception as exc:  # noqa: BLE001
        logger.exception("slide video generation failed for %s slide %s", project_id, slide_index)
        with _slide_tasks_lock:
            task["status"] = "failed"
            task["error"] = str(exc)


def _run_concat(project_id: str) -> None:
    task = _get_or_create_concat_task(project_id)
    with _concat_task_lock:
        task.update({"status": "running", "error": None})

    try:
        from domain.dal.project_store import ProjectStorage
        from video_pipeline.video_settings import load_video_settings, apply_aspect_ratio
        from video_pipeline.advanced_generate import concat_all_segments

        video_config = load_video_settings()

        project_config = ProjectStorage.load_video_config(
            project_id, get_config().output_base_dir
        )
        if project_config:
            for key, value in project_config.items():
                if value is not None and hasattr(video_config, key):
                    setattr(video_config, key, value)
            video_config = apply_aspect_ratio(video_config)

        result = concat_all_segments(project_id, video_config)
        with _concat_task_lock:
            task["status"] = "completed"
            task["result"] = result
            task["error"] = None
    except Exception as exc:  # noqa: BLE001
        logger.exception("concat failed for %s", project_id)
        with _concat_task_lock:
            task["status"] = "failed"
            task["error"] = str(exc)


def _get_or_create_clip_task(project_id: str) -> dict:
    with _clip_task_lock:
        t = _clip_task.get(project_id)
        if t is None:
            t = {"status": "idle", "error": None}
            _clip_task[project_id] = t
        return t


def _run_clip_concat(project_id: str, slide_indexes: list) -> None:
    task = _get_or_create_clip_task(project_id)
    with _clip_task_lock:
        task.update({"status": "running", "error": None})

    try:
        from domain.dal.project_store import ProjectStorage
        from video_pipeline.video_settings import load_video_settings, apply_aspect_ratio
        from video_pipeline.advanced_generate import concat_selected_segments

        video_config = load_video_settings()

        project_config = ProjectStorage.load_video_config(
            project_id, get_config().output_base_dir
        )
        if project_config:
            for key, value in project_config.items():
                if value is not None and hasattr(video_config, key):
                    setattr(video_config, key, value)
            video_config = apply_aspect_ratio(video_config)

        result = concat_selected_segments(project_id, slide_indexes, video_config)
        with _clip_task_lock:
            task["status"] = "completed"
            task["result"] = result
            task["error"] = None
    except Exception as exc:  # noqa: BLE001
        logger.exception("clip concat failed for %s", project_id)
        with _clip_task_lock:
            task["status"] = "failed"
            task["error"] = str(exc)


# Route 1: POST /{project_id}/slide/{slide_index}
def start_slide_generation(
    project_id: str,
    slide_index: int,
    settings: dict,
):
    project_dir = _project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="project not found")

    task_key = f"{project_id}:{slide_index}"
    task = _get_or_create_slide_task(task_key)
    if task.get("status") == "running":
        raise HTTPException(status_code=409, detail="slide generation already running")

    t = threading.Thread(
        target=_run_slide_video_generation,
        args=(project_id, slide_index, settings),
        daemon=True,
    )
    t.start()
    return {"status": "running"}


# Route 2: GET /{project_id}/slides/status
def get_slides_status(project_id: str):
    from video_pipeline.advanced_generate import get_slides_video_status

    status = get_slides_video_status(project_id)

    # Merge with _slide_tasks: if a slide is currently generating, override has_segment;
    # 若单张生成失败，透出 error 供前端刷新后恢复失败提示
    for slide in status["slides"]:
        si = slide["slide_index"]
        task_key = f"{project_id}:{si}"
        with _slide_tasks_lock:
            slide_task = _slide_tasks.get(task_key)
        if slide_task:
            st = slide_task.get("status")
            if st == "running":
                slide["has_segment"] = False
                slide["generating"] = True
            elif st == "failed":
                slide["has_segment"] = False
                slide["generating"] = False
                slide["error"] = slide_task.get("error")

    # Check _concat_task（含失败状态透出）
    with _concat_task_lock:
        concat = _concat_task.get(project_id)
    if concat:
        st = concat.get("status")
        if st == "running":
            status["has_final"] = False
            status["concat_status"] = "running"
        elif st == "failed":
            status["concat_status"] = "failed"
            status["concat_error"] = concat.get("error")

    # Check _clip_task（片段合成状态透出，供前端轮询刷新片段列表）
    with _clip_task_lock:
        clip = _clip_task.get(project_id)
    if clip:
        st = clip.get("status")
        if st == "running":
            status["clip_status"] = "running"
        elif st == "failed":
            status["clip_status"] = "failed"
            status["clip_error"] = clip.get("error")
        elif st == "completed":
            status["clip_status"] = "completed"

    # 合并各 slide 生成结果中的 warnings（多 face 等提示）
    merged_warnings: list = []
    with _slide_tasks_lock:
        for key, slide_task in _slide_tasks.items():
            if not key.startswith(f"{project_id}:"):
                continue
            result = slide_task.get("result") or {}
            for w in result.get("warnings", []) or []:
                if w not in merged_warnings:
                    merged_warnings.append(w)
    status["warnings"] = merged_warnings

    return status


# Route 3: POST /{project_id}/concat
def start_concat(project_id: str):
    project_dir = _project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="project not found")

    task = _get_or_create_concat_task(project_id)
    if task.get("status") == "running":
        raise HTTPException(status_code=409, detail="concat already running")

    t = threading.Thread(
        target=_run_concat,
        args=(project_id,),
        daemon=True,
    )
    t.start()
    return {"status": "running"}


# Route 4: GET /{project_id}/slide/{slide_index}/download
def download_slide(project_id: str, slide_index: int):
    segment = _project_dir(project_id) / f"slide_{slide_index:02d}" / "segment.mp4"
    if not segment.exists():
        raise HTTPException(status_code=404, detail="segment.mp4 not found")
    return FileResponse(
        path=str(segment),
        media_type="video/mp4",
        filename=f"slide_{slide_index:02d}.mp4",
    )


# ---------------------------------------------------------------------------
# 选段合成 — 片段视频（video_clips/）
# ---------------------------------------------------------------------------


# Route 5: POST /{project_id}/clips
def start_clip_concat(project_id: str, slide_indexes: list):
    project_dir = _project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="project not found")
    if not slide_indexes:
        raise HTTPException(status_code=400, detail="请至少选择一张幻灯片")
    # 合法序号校验（仅允许正整数，防路径注入）
    try:
        cleaned = sorted({int(si) for si in slide_indexes})
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="幻灯片序号不合法") from None
    if any(si < 1 for si in cleaned):
        raise HTTPException(status_code=400, detail="幻灯片序号不合法")

    task = _get_or_create_clip_task(project_id)
    if task.get("status") == "running":
        raise HTTPException(status_code=409, detail="片段合成已在进行中，请等待完成")

    t = threading.Thread(
        target=_run_clip_concat,
        args=(project_id, cleaned),
        daemon=True,
    )
    t.start()
    return {"status": "running"}


# Route 6: GET /{project_id}/clips
def list_clips(project_id: str):
    from video_pipeline.advanced_generate import list_video_clips
    from datetime import datetime

    clips = list_video_clips(project_id)
    project_dir = _project_dir(project_id)
    final_video = project_dir / "final_video.mp4"

    if final_video.exists():
        mtime = final_video.stat().st_mtime
        final_record = {
            "type": "final",
            "file_name": "final_video.mp4",
            "video_name": "所有幻灯片",
            "slides": [],
            "created_at": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
        }
        clips = [final_record] + clips

    return {"clips": clips}


# Route 7: DELETE /{project_id}/clips/{file_name}
def delete_clip(project_id: str, file_name: str):
    if file_name == "final_video.mp4":
        raise HTTPException(status_code=400, detail="完整视频（所有幻灯片）不能删除")
    from video_pipeline.advanced_generate import delete_video_clip
    try:
        return delete_video_clip(project_id, file_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


# Route 8: GET /{project_id}/clips/{file_name}/download
def download_clip(project_id: str, file_name: str):
    if not file_name or not file_name.endswith(".mp4") or "/" in file_name or "\\" in file_name:
        raise HTTPException(status_code=400, detail="非法文件名")

    project_dir = _project_dir(project_id)

    # 完整视频（所有幻灯片）直接从项目根目录取
    if file_name == "final_video.mp4":
        final = project_dir / "final_video.mp4"
        if not final.exists():
            raise HTTPException(status_code=404, detail="final_video.mp4 not found")
        return FileResponse(
            path=str(final),
            media_type="video/mp4",
            filename=f"{project_id}_final.mp4",
        )

    clip = project_dir / "video_clips" / file_name
    if not clip.exists():
        raise HTTPException(status_code=404, detail="clip not found")
    return FileResponse(
        path=str(clip),
        media_type="video/mp4",
        filename=file_name,
    )
