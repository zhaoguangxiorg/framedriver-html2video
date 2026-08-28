# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""内容智能体业务层。

承接内容生成智能体的业务逻辑：agent 线程运行、SSE 事件推送、消息持久化、
停止/停止登记、content.md 读写。api 层只负责路由与参数透传。
"""
import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

from fastapi.responses import StreamingResponse

from appservice.agent_manager import AgentManager
from shared.config import get_config
from shared.file_utils import ensure_dir

logger = logging.getLogger("appservice.content")

# 内容智能体运行登记集合：记录当前正在执行的内容生成任务 project_id
_content_running: set = set()
# 内容智能体停止请求集合：用户点击停止后置位，生成器循环检测后 break
_content_stop_requested: set = set()


TOOL_NAME_MAP = {
    "read_content": "读取内容",
    "save_content": "保存内容",
    "write_todos": "更新待办清单",
    "task": "生成幻灯片",
}


async def _run_agent_in_thread(
    queue: asyncio.Queue,
    project_id: str,
    user_message: str,
    model_code: Optional[str] = None,
) -> None:
    """Run content agent in a background thread, pushing SSE to asyncio queue."""
    _content_running.add(project_id)
    try:
        agent = AgentManager().get_content_agent()

        await queue.put({
            "type": "progress",
            "percent": 5,
            "current_step": "正在分析需求...",
        })

        response_text = ""
        collected_steps: list = []
        stopped = False

        for chunk in agent.stream(
            {"messages": [{"role": "user", "content": user_message}]},
            config={"configurable": {"thread_id": f"content_agent_{project_id}", "project_id": project_id}},
            context={"model_code": model_code} if model_code else {},
            stream_mode="updates",
        ):
            # 用户主动停止：下一个 chunk 处 break 停止生成器（温和停止）
            if project_id in _content_stop_requested:
                _content_stop_requested.discard(project_id)
                stopped = True
                break

            if not isinstance(chunk, dict):
                continue

            # updates 模式: chunk = {node_name: {"messages": [新消息]}}
            for node_name, state in chunk.items():
                if not isinstance(state, dict):
                    continue
                for msg in state.get("messages", []) or []:
                    msg_type = getattr(msg, "type", "") or ""
                    tool_calls = getattr(msg, "tool_calls", None)

                    # 跳过 HumanMessage
                    if msg_type == "human":
                        continue

                    # ToolMessage → 推送 step_done 事件
                    if msg_type == "tool":
                        tc_name = getattr(msg, "name", "") or ""
                        zh_name = TOOL_NAME_MAP.get(tc_name, tc_name)
                        if zh_name:
                            await queue.put({"type": "step_done", "name": f"{zh_name}成功", "code": tc_name})
                            # 事件级停止检查：停止后不再处理后续事件
                            if project_id in _content_stop_requested:
                                stopped = True
                                return
                            # 更新 collected_steps 中对应条目的 done 字段（持久化用）
                            for s in collected_steps:
                                if s["code"] == tc_name and "done" not in s:
                                    s["done"] = f"{zh_name}成功"
                                    break
                        continue

                    # AI 消息
                    if msg_type == "ai":
                        if tool_calls:
                            # 带工具调用 → 推送 step 事件
                            for tc in tool_calls:
                                tc_name = ""
                                if isinstance(tc, dict):
                                    tc_name = tc.get("name", "") or ""
                                else:
                                    tc_name = getattr(tc, "name", "") or ""
                                zh_name = TOOL_NAME_MAP.get(tc_name, tc_name)
                                if zh_name:
                                    collected_steps.append({"name": zh_name, "code": tc_name})
                                    await queue.put({"type": "step", "name": f"正在{zh_name}", "code": tc_name})
                                    # 事件级停止检查：停止后不再处理后续事件
                                    if project_id in _content_stop_requested:
                                        stopped = True
                                        return
                        else:
                            # 不带工具调用 → 推送 text 事件, 更新 response_text
                            content = ""
                            if hasattr(msg, "content"):
                                content = msg.content or ""
                            elif isinstance(msg, dict):
                                content = msg.get("content", "") or ""
                            content = str(content)
                            if content and content != response_text:
                                response_text = content
                                await queue.put({"type": "text", "content": content})
                                # 事件级停止检查：停止后不再处理后续事件
                                if project_id in _content_stop_requested:
                                    stopped = True
                                    return

        if not stopped:
            # 正常完成：保存消息并推送完成事件（停止场景的保存统一在 finally 处理）
            try:
                from domain.dal.message_dal import MessageStorage
                MessageStorage.add_message(project_id, "user", user_message, tab="content")
                MessageStorage.add_message(
                    project_id, "agent", response_text, tab="content",
                    steps=collected_steps,
                )
            except Exception:
                logger.warning("save messages to db failed", exc_info=True)

            await queue.put({"type": "progress", "percent": 100, "current_step": "完成"})
            await queue.put({
                "type": "done",
                "summary": "内容生成完成",
            })
    except Exception as exc:
        logger.exception("content agent failed for project=%s", project_id)
        await queue.put({
            "type": "error",
            "error_code": "AGENT_ERROR",
            "message": f"智能体执行失败: {exc}",
        })
    finally:
        _content_running.discard(project_id)
        _content_stop_requested.discard(project_id)
        if stopped:
            # 停止收尾：先保存部分内容（DB），再最后推送 stopped
            # 届时集合已清理、DB 已保存，前端收到 stopped 即代表真正停止完成，避免与新流产生竞态
            try:
                from domain.dal.message_dal import MessageStorage
                MessageStorage.add_message(project_id, "user", user_message, tab="content")
                MessageStorage.add_message(
                    project_id, "agent", response_text, tab="content",
                    steps=collected_steps, status="stopped",
                )
            except Exception:
                logger.warning("save stopped messages to db failed", exc_info=True)
            await queue.put({"type": "stopped", "summary": "已停止"})
        await queue.put({"type": "__close__"})


def stop_content_agent(project_id: str):
    """请求停止正在运行的内容智能体（温和停止：当前工具调用完成后停止）。

    仅当任务确实在运行时置位，避免任务结束后残留标记导致下次执行误停止。
    置位 _content_stop_requested，生成器循环在下一个 chunk 处 break。
    """
    if project_id in _content_running:
        _content_stop_requested.add(project_id)
    return None


async def handle_content(project_id: str, message: str, model_code: Optional[str] = None):
    """Single POST logic that returns SSE stream directly."""

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    thread = loop.run_in_executor(
        None,
        lambda: asyncio.run(_run_agent_in_thread(q, project_id, message, model_code)),
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            msg = await q.get()
            if msg.get("type") == "__close__":
                break
            # SSE format: event + data
            event_type = msg.get("type", "message")
            data = json.dumps(msg, ensure_ascii=False)
            yield f"event: {event_type}\ndata: {data}\n\n"
        # Wait for thread to finish before closing
        await thread

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def get_content_md(project_id: str):
    """读取项目目录中的 content.md 文件内容。"""
    config = get_config()
    base_dir = config.output_base_dir
    content_path = base_dir / "html_slides" / project_id / "content.md"

    if not content_path.exists():
        return {"exists": False, "content": ""}

    content = content_path.read_text(encoding="utf-8")
    return {"exists": True, "content": content}


def save_content_md(project_id: str, content: str):
    """保存用户编辑的 content.md 内容（完全覆盖）。"""
    config = get_config()
    base_dir = config.output_base_dir
    project_dir = base_dir / "html_slides" / project_id
    ensure_dir(project_dir)

    content_path = project_dir / "content.md"
    content_path.write_text(content, encoding="utf-8")

    return {"message": "内容已保存", "file_path": str(content_path.resolve())}
