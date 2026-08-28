# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""PPT 智能体业务层。

承接 PPT 生成智能体的全部业务逻辑：agent 流式运行、SSE 事件推送、
消息持久化、人工介入（interrupt + resume）、状态查询、停止。
api 层只负责路由与参数透传。
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import AsyncGenerator, List, Optional

from fastapi.responses import StreamingResponse, JSONResponse
from langgraph.types import Command

from appservice.agent_manager import AgentManager
from shared.config import get_config
from domain.dal.project_store import ProjectStorage
from video_pipeline.video_config_cache import get_video_config
from domain.dal.message_dal import MessageStorage

logger = logging.getLogger("appservice.ppt")

# 智能体执行状态内存快照（供轮询接口使用）
_running_state: dict[str, dict] = {}

TOOL_NAME_MAP = {
    "init_project": "初始化项目",
    "read_content_md": "读取内容大纲",
    "read_style_spec": "读取样式规范",
    "read_slide_html": "读取幻灯片HTML",
    "read_slides_meta": "读取幻灯片列表",
    "delete_slide": "删除幻灯片",
    "move_slide": "移动幻灯片",
    "insert_slide": "插入幻灯片",
    "read_full_content": "读取完整PPT内容",
    "update_style_spec": "更新样式规范",
    "update_video_config": "更新视频配置",
    "save_slide_content": "保存幻灯片内容",
    "save_slide_html": "保存幻灯片HTML",
    "write_todos": "更新待办清单",
}

_TASK_DISPLAY = {
    "slide-designer": "生成幻灯片",
    "slide-manager": "管理幻灯片结构",
}


def _project_dir(project_id: str) -> Path:
    base = get_config().output_base_dir
    return base / "html_slides" / project_id


def _load_slides_data(project_id: str) -> List[dict]:
    p = _project_dir(project_id) / "slides_data.json"
    if not p.exists():
        return []
    try:
        rows = ProjectStorage.load_slides_data(project_id, get_config().output_base_dir)
        return [r.model_dump() for r in rows]
    except Exception:
        return []


def _validate_answers(questions, answers):
    """校验用户提交的答案。

    Args:
        questions: 问题列表，每项含 question_id/type/required 等字段。
        answers: 用户答案列表，每项形如 {"question_id": "...", "answer": ...}。

    Returns:
        None 表示校验通过；dict 表示校验失败（含 error_code 和 message）。
    """
    # 1. 数量校验
    if len(answers) != len(questions):
        return {"error_code": "ANSWER_COUNT_MISMATCH", "message": "答案数量与问题数量不一致"}
    # 2. question_id 匹配
    qids = {q["question_id"] for q in questions}
    aid_set = set()
    for a in answers:
        qid = a.get("question_id")
        if qid not in qids:
            return {"error_code": "QUESTION_ID_MISMATCH", "message": f"问题ID不匹配: {qid}"}
        if qid in aid_set:
            return {"error_code": "QUESTION_ID_MISMATCH", "message": f"问题ID重复: {qid}"}
        aid_set.add(qid)
    # 3. 必填校验
    q_map = {q["question_id"]: q for q in questions}
    for a in answers:
        q = q_map[a["question_id"]]
        if q.get("required", True):
            ans = a.get("answer")
            if ans is None or ans == "" or ans == []:
                return {"error_code": "REQUIRED_ANSWER_MISSING", "message": f"必填题未作答: {a['question_id']}"}
    # 4. 类型校验
    for a in answers:
        q = q_map[a["question_id"]]
        ans = a.get("answer")
        qtype = q["type"]
        if qtype == "single_choice":
            if not isinstance(ans, str):
                return {"error_code": "TYPE_ERROR", "message": f"单选题答案应为字符串: {a['question_id']}"}
        elif qtype == "multi_choice":
            if not isinstance(ans, list):
                return {"error_code": "TYPE_ERROR", "message": f"多选题答案应为数组: {a['question_id']}"}
        elif qtype == "text":
            if not isinstance(ans, str):
                return {"error_code": "TYPE_ERROR", "message": f"问答题答案应为字符串: {a['question_id']}"}
        elif qtype == "confirm":
            if not isinstance(ans, bool):
                return {"error_code": "TYPE_ERROR", "message": f"确认题答案应为布尔值: {a['question_id']}"}
    return None  # 校验通过


async def _run_ppt_stream(
    queue: asyncio.Queue,
    agent,
    input,          # {"messages": [HumanMessage]} 或 Command(resume=answers)
    config: dict,   # {"configurable": {"thread_id": ..., "project_id": ...}}
    project_id: str,
    mode: str,      # "send"（主接口）或 "resume"（恢复接口）
    model_code: Optional[str] = None,
    # 以下参数仅 mode="resume" 时传入（重建的临时变量）
    accumulated_text: str = "",
    collected_steps: list = None,
    collected_slides: list = None,
    existing_cards: list = None,
    message_id: str = None,
    user_message: str = "",
) -> None:
    """共享的流式处理函数，主接口和恢复接口都调用。

    - mode="send"：临时变量从零开始；中断时新增 agent 消息；完成时新增 agent + user 消息
    - mode="resume"：临时变量从数据库重建；中断时更新原消息追加 intervention 卡片；完成时更新原消息
    """
    if collected_steps is None:
        collected_steps = []
    if collected_slides is None:
        collected_slides = []
    if existing_cards is None:
        existing_cards = []

    _running_state[project_id] = {"steps": [], "text": "", "cards": [], "stop_requested": False}
    stopped_flag = False  # 标记是否因用户停止而退出（finally 中据此推 stopped 事件）

    try:
        await queue.put({
            "type": "progress",
            "percent": 5,
            "current_step": "正在规划幻灯片..." if mode == "send" else "正在恢复执行...",
        })

        emitted: set = set()
        tc_slide_map: dict = {}   # tool_call_id → slide_index
        _task_display_map: dict = {}  # tool_call_id → zh_name for task tool
        total_slides: Optional[int] = None

        # 预热视频配置缓存（智能体执行中可能被 update_video_config 修改，
        # slide 事件拼接时每次 get_video_config，保证拿到最新值）
        get_video_config(project_id)

        context = {"model_code": model_code} if model_code else {}

        # subgraphs=True：暴露 WorkerAgent 内部事件，用于卡片推送
        for namespace, chunk in agent.stream(
            input,
            config=config,
            context=context,
            stream_mode="updates",
            subgraphs=True,
        ):
            # 用户主动停止：stop_requested 置位后，下一个 chunk 处 break 停止生成器（温和停止）。
            # 只置标志跳出，stopped 事件延迟到 finally 最后推送（届时内存/DB 已清理完毕，
            # 前端收到 stopped 即代表真正停止完成，避免与新流产生竞态）
            if _running_state.get(project_id, {}).get("stop_requested"):
                stopped_flag = True
                break

            if not isinstance(chunk, dict):
                continue

            # __interrupt__ 事件检测（中断事件不区分 namespace）
            if "__interrupt__" in chunk:
                interrupt_value = chunk["__interrupt__"][0].value
                # interrupt_value = {"type": "human_intervention",
                #                    "intervention_id": "...", "questions": [...]}
                if mode == "send":
                    # 主接口首次中断：更新空壳 agent 消息（含已生成幻灯片 + intervention 卡片）
                    try:
                        cards_for_db = [{"card_type": "slides", "card_data": s} for s in collected_slides]
                        cards_for_db.append({"card_type": "intervention", "card_data": {
                            "intervention_id": interrupt_value["intervention_id"],
                            "questions": interrupt_value["questions"],
                        }})
                        MessageStorage.update_message_content_steps(
                            message_id, accumulated_text, collected_steps, cards_for_db,
                        )
                        MessageStorage.update_message_status(message_id, "interrupted")
                    except Exception:
                        logger.warning("update intervention message to db failed", exc_info=True)
                else:
                    # 恢复接口再次中断：更新原消息，追加新的 intervention 卡片
                    existing_cards.append({"card_type": "intervention", "card_data": {
                        "intervention_id": interrupt_value["intervention_id"],
                        "questions": interrupt_value["questions"],
                    }})
                    try:
                        MessageStorage.update_message_cards(message_id, existing_cards)
                        MessageStorage.update_message_status(message_id, "interrupted")
                    except Exception:
                        logger.warning("update intervention cards to db failed", exc_info=True)
                await queue.put({"type": "human_intervention", **interrupt_value})
                await queue.put({"type": "done", "summary": "等待用户作答", "interrupted": True})
                # 中断时 SSE 流结束，不发送 progress:100
                break

            # namespace 非空 → WorkerAgent 事件（仅用于卡片推送，不推 step 给前端）
            if namespace:
                for _node_name, state in chunk.items():
                    if not isinstance(state, dict):
                        continue
                    for msg in state.get("messages", []) or []:
                        msg_type = getattr(msg, "type", "") or ""
                        tool_calls = getattr(msg, "tool_calls", None)

                        if msg_type == "ai" and tool_calls:
                            for tc in tool_calls:
                                tc_name = ""
                                args = {}
                                if isinstance(tc, dict):
                                    tc_name = tc.get("name", "") or ""
                                    args = tc.get("args", {}) or {}
                                else:
                                    tc_name = getattr(tc, "name", "") or ""
                                    args = getattr(tc, "args", {}) or {}
                                tc_id = ""
                                if isinstance(tc, dict):
                                    tc_id = tc.get("id", "") or ""
                                else:
                                    tc_id = getattr(tc, "id", "") or ""
                                if tc_name in ("save_slide_html", "save_slide_content"):
                                    si = args.get("slide_index")
                                    if si is not None and tc_id:
                                        tc_slide_map[tc_id] = int(si)

                        elif msg_type == "tool":
                            tc_name = getattr(msg, "name", "") or ""
                            tc_id = getattr(msg, "tool_call_id", "") or ""
                            si = tc_slide_map.pop(tc_id, None) if tc_id else None
                            if tc_name == "save_slide_html" and si is not None and si not in emitted:
                                html_path = f"/api/slides/{project_id}/{si}/html"
                                title = ""
                                narration = ""
                                rows = _load_slides_data(project_id)
                                for row in rows:
                                    if int(row.get("slide_index", -1)) == si:
                                        title = row.get("title", "") or ""
                                        break
                                slides_meta = [
                                    {"slide_index": int(r.get("slide_index", 0)), "title": r.get("title", "") or ""}
                                    for r in rows
                                ]
                                narration = ProjectStorage.load_slide_narration(project_id, si, get_config().output_base_dir) or ""
                                slide_text = ProjectStorage.load_slide_content(project_id, si, get_config().output_base_dir) or ""
                                slide_data = {
                                    "slide_index": si,
                                    "title": title,
                                    "html_path": html_path,
                                    "narration": narration,
                                    "slide_text": slide_text,
                                    "slides_meta": slides_meta,
                                    "video_config": get_video_config(project_id),
                                }
                                collected_slides.append(slide_data)
                                _running_state[project_id]["cards"] = collected_slides[:]
                                # 逐步入库：幻灯片生成后同步写 DB
                                try:
                                    # 合并历史卡片（resume 时含 intervention 等），避免实时入库覆盖丢失
                                    cards_for_db = existing_cards + [{"card_type": "slides", "card_data": s} for s in collected_slides]
                                    MessageStorage.update_message_content_steps(message_id, accumulated_text, collected_steps, cards_for_db)
                                except Exception:
                                    pass
                                await queue.put(dict(type="slide", **slide_data))
                                emitted.add(si)
                                # 事件级停止检查：LLM 单 chunk 返回时，迭代级检查无法及时生效
                                if _running_state.get(project_id, {}).get("stop_requested"):
                                    stopped_flag = True
                                    return
                        continue
                continue

            # namespace 为空 → Orchestrator 事件（前端可见）
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
                        tc_id = getattr(msg, "tool_call_id", "") or ""
                        if tc_name == "task":
                            zh_name = _task_display_map.pop(tc_id, "调度子智能体") if tc_id else "调度子智能体"
                        else:
                            zh_name = TOOL_NAME_MAP.get(tc_name, tc_name)
                        if zh_name:
                            # task 类型用 tc_id 精确匹配，其他用 code 匹配（兼容非并行场景）
                            if tc_name == "task":
                                for s in collected_steps:
                                    if s.get("tc_id") == tc_id and "done" not in s:
                                        s_name = s["name"]
                                        s["done"] = f"{s_name}成功"
                                        done_name = f"{s_name}成功"
                                        break
                                else:
                                    done_name = f"{zh_name}成功"
                            else:
                                for s in collected_steps:
                                    if s["code"] == tc_name and "done" not in s:
                                        s["done"] = f"{zh_name}成功"
                                        break
                                done_name = f"{zh_name}成功"
                            _running_state[project_id]["steps"] = collected_steps[:]
                            # 逐步入库：步骤完成后同步写 DB
                            try:
                                # 合并历史卡片（resume 时含 intervention 等），避免实时入库覆盖丢失
                                cards_for_db = existing_cards + [{"card_type": "slides", "card_data": s} for s in collected_slides]
                                MessageStorage.update_message_content_steps(message_id, accumulated_text, collected_steps, cards_for_db)
                            except Exception:
                                pass
                            await queue.put({"type": "step_done", "name": done_name, "code": tc_name, "tc_id": tc_id})
                            # 事件级停止检查：停止后不再处理后续事件
                            if _running_state.get(project_id, {}).get("stop_requested"):
                                stopped_flag = True
                                return
                        continue

                    # AI 消息
                    if msg_type == "ai":
                        if tool_calls:
                            # 带工具调用 → 推送 step 事件
                            for tc in tool_calls:
                                tc_name = ""
                                tc_id = ""
                                args = {}
                                if isinstance(tc, dict):
                                    tc_name = tc.get("name", "") or ""
                                    tc_id = tc.get("id", "") or ""
                                    args = tc.get("args", {}) or {}
                                else:
                                    tc_name = getattr(tc, "name", "") or ""
                                    tc_id = getattr(tc, "id", "") or ""
                                    args = getattr(tc, "args", {}) or {}

                                if tc_name == "task":
                                    subagent = args.get("subagent_type", "")
                                    zh_name = _TASK_DISPLAY.get(subagent, "调度子智能体")
                                    if tc_id:
                                        _task_display_map[tc_id] = zh_name
                                else:
                                    zh_name = TOOL_NAME_MAP.get(tc_name, tc_name)

                                if zh_name:
                                    # 调度时无法获取真实 slide_index，步骤名不带序号
                                    display_name = zh_name

                                    collected_steps.append({"name": display_name, "code": tc_name, "tc_id": tc_id})
                                    _running_state[project_id]["steps"] = collected_steps[:]
                                    # 逐步入库：新步骤后同步写 DB
                                    try:
                                        # 合并历史卡片（resume 时含 intervention 等），避免实时入库覆盖丢失
                                        cards_for_db = existing_cards + [{"card_type": "slides", "card_data": s} for s in collected_slides]
                                        MessageStorage.update_message_content_steps(message_id, accumulated_text, collected_steps, cards_for_db)
                                    except Exception:
                                        pass
                                    await queue.put({"type": "step", "name": f"正在{display_name}", "code": tc_name, "tc_id": tc_id})
                                    # 事件级停止检查：停止后不再处理后续事件
                                    if _running_state.get(project_id, {}).get("stop_requested"):
                                        stopped_flag = True
                                        return
                        else:
                            # 不带工具调用 → 推送 text 事件, 更新 accumulated_text
                            content = ""
                            if hasattr(msg, "content"):
                                content = msg.content or ""
                            elif isinstance(msg, dict):
                                content = msg.get("content", "") or ""
                            content = str(content)
                            if content and content != accumulated_text:
                                accumulated_text = content
                                _running_state[project_id]["text"] = accumulated_text
                                # 逐步入库：文本更新后同步写 DB
                                try:
                                    # 合并历史卡片（resume 时含 intervention 等），避免实时入库覆盖丢失
                                    cards_for_db = existing_cards + [{"card_type": "slides", "card_data": s} for s in collected_slides]
                                    MessageStorage.update_message_content_steps(message_id, accumulated_text, collected_steps, cards_for_db)
                                except Exception:
                                    pass
                                await queue.put({"type": "text", "content": content})
                                # 事件级停止检查：停止后不再处理后续事件
                                if _running_state.get(project_id, {}).get("stop_requested"):
                                    stopped_flag = True
                                    return

            if total_slides is None:
                data = _load_slides_data(project_id)
                total_slides = len(data)

        else:
            # 正常完成时（for 循环未被 break，即未发生中断）
            new_count = len(emitted)
            if total_slides and new_count:
                await queue.put({
                    "type": "progress",
                    "percent": 100,
                    "current_step": f"已完成 {new_count} 张幻灯片",
                })
            await queue.put({
                "type": "done",
                "summary": f"已生成 {new_count} 张幻灯片" if new_count else "已就绪",
            })

            try:
                if mode == "send":
                    # 更新空壳 agent 消息为最终状态
                    final_cards = [{"card_type": "slides", "card_data": s} for s in collected_slides]
                    MessageStorage.update_message_content_steps(
                        message_id, accumulated_text, collected_steps, final_cards
                    )
                    MessageStorage.update_message_status(message_id, "completed")
                else:
                    # 恢复接口正常完成：更新原消息（不是新增）
                    final_cards = existing_cards + [
                        {"card_type": "slides", "card_data": s} for s in collected_slides
                    ]
                    MessageStorage.update_message_content_steps(
                        message_id, accumulated_text, collected_steps, final_cards
                    )
                    MessageStorage.update_message_status(message_id, "completed")
            except Exception:
                logger.warning("save final messages to db failed", exc_info=True)

    except Exception as exc:
        logger.exception("html_agent failed for project=%s", project_id)
        if message_id:
            try:
                MessageStorage.update_message_status(message_id, "error")
            except Exception:
                pass
        await queue.put({
            "type": "error",
            "error_code": "AGENT_ERROR",
            "message": f"智能体执行失败: {exc}",
        })
    finally:
        _running_state.pop(project_id, None)
        # 停止收尾最后推送 stopped：此时内存已清理、DB 状态已更新，
        # 前端收到 stopped 即代表真正停止完成（实时 SSE 与刷新后轮询均可据此收尾）
        if stopped_flag:
            if message_id:
                try:
                    MessageStorage.update_message_status(message_id, "stopped")
                except Exception:
                    logger.warning("update stopped status failed", exc_info=True)
            await queue.put({"type": "stopped", "summary": "已停止"})
        await queue.put({"type": "__close__"})


async def handle_ppt(project_id: str, message: str, model_code: Optional[str] = None):
    """主接口逻辑：发送用户消息，返回 SSE 流。"""

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    agent = AgentManager().get_html_agent()
    thread_id = f"html_agent_{project_id}"
    config = {"configurable": {"thread_id": thread_id, "project_id": project_id}}
    input_data = {"messages": [{"role": "user", "content": message}]}

    # 提前写入 user 消息和空壳 agent 消息
    MessageStorage.add_message(project_id, "user", message, tab="ppt")
    agent_msg = MessageStorage.add_message(
        project_id, "agent", "", tab="ppt",
        steps=[], cards=[], status="pending"
    )
    agent_msg_id = agent_msg["id"]

    thread = loop.run_in_executor(
        None,
        lambda: asyncio.run(_run_ppt_stream(
            q, agent, input_data, config, project_id, "send",
            model_code=model_code,
            user_message=message,
            message_id=agent_msg_id,
        )),
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            msg = await q.get()
            if msg.get("type") == "__close__":
                break
            event_type = msg.get("type", "message")
            data = json.dumps(msg, ensure_ascii=False)
            yield f"event: {event_type}\ndata: {data}\n\n"
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


def stop_agent(project_id: str):
    """请求停止正在运行的智能体（温和停止：当前工具调用完成后停止）。

    置位 _running_state 的 stop_requested，生成器循环在下一个 chunk 处 break。
    """
    state = _running_state.get(project_id)
    if state is not None:
        state["stop_requested"] = True
    return None


async def handle_intervention(
    project_id: str,
    intervention_id: str,
    answers: list,
    model_code: Optional[str] = None,
):
    """恢复接口逻辑：提交用户答案，恢复智能体执行，返回独立 SSE 流。"""

    # 1. 从数据库查找 intervention 消息
    msg = MessageStorage.get_message_by_intervention_id(project_id, intervention_id)
    if not msg:
        return JSONResponse(
            status_code=404,
            content={"error_code": "NOT_FOUND", "message": "介入问题不存在"},
        )

    # 2. 解析 cards 并定位 intervention 卡片
    cards = json.loads(msg["cards"]) if isinstance(msg["cards"], str) else msg["cards"]
    intervention_card = None
    for card in cards:
        if not isinstance(card, dict):
            continue
        if card.get("card_type") == "intervention":
            card_data = card.get("card_data") or {}
            if card_data.get("intervention_id") == intervention_id:
                intervention_card = card
                break
    if not intervention_card:
        return JSONResponse(
            status_code=404,
            content={"error_code": "NOT_FOUND", "message": "介入问题不存在"},
        )

    # 3. 检查是否已提交（intervention 卡片已有 answers）
    if "answers" in (intervention_card.get("card_data") or {}):
        return JSONResponse(
            status_code=409,
            content={"error_code": "ALREADY_SUBMITTED", "message": "该介入问题已作答"},
        )

    # 4. 校验 answers
    questions = intervention_card["card_data"]["questions"]
    error = _validate_answers(questions, answers)
    if error:
        return JSONResponse(status_code=422, content=error)

    # 5. 重建临时变量（中断前无 slides）
    accumulated_text = msg["content"] or ""
    collected_steps = json.loads(msg["steps"]) if isinstance(msg["steps"], str) else msg["steps"]
    collected_slides: list = []
    existing_cards = cards

    # 6. 更新 intervention 卡片加入 answers
    intervention_card["card_data"]["answers"] = answers
    try:
        MessageStorage.update_message_cards(msg["id"], existing_cards)
    except Exception:
        logger.warning("update intervention answers to db failed", exc_info=True)

    # 7. 检查 checkpoint 是否存在（失效则直接返回 409，避免异常被 _run_ppt_stream 通用 except 吞掉）
    from agent.checkpointer import get_sqlite_checkpointer
    checkpointer = get_sqlite_checkpointer()
    checkpoint_config = {"configurable": {"thread_id": f"html_agent_{project_id}"}}
    checkpoint = checkpointer.get(checkpoint_config)
    if checkpoint is None or not checkpoint:
        return JSONResponse(status_code=409, content={
            "error_code": "CHECKPOINT_MISSING",
            "message": "智能体状态已失效，请重新发起对话",
        })

    # 恢复前更新消息状态为 pending
    try:
        MessageStorage.update_message_status(msg["id"], "pending")
    except Exception:
        logger.warning("update message status to pending failed", exc_info=True)

    # 8. 调用 _run_ppt_stream(mode="resume")
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    agent = AgentManager().get_html_agent()
    thread_id = f"html_agent_{project_id}"
    config = {"configurable": {"thread_id": thread_id, "project_id": project_id}}
    resume_input = Command(resume=answers)

    thread = loop.run_in_executor(
        None,
        lambda: asyncio.run(_run_ppt_stream(
            q, agent, resume_input, config, project_id, "resume",
            model_code=model_code,
            accumulated_text=accumulated_text,
            collected_steps=collected_steps,
            collected_slides=collected_slides,
            existing_cards=existing_cards,
            message_id=msg["id"],
        )),
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            evt = await q.get()
            if evt.get("type") == "__close__":
                break
            event_type = evt.get("type", "message")
            data = json.dumps(evt, ensure_ascii=False)
            yield f"event: {event_type}\ndata: {data}\n\n"
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


async def get_agent_status(project_id: str):
    """查询智能体执行状态。"""
    # 1. 查 DB：最后一条 agent 消息的 status
    last_msg = MessageStorage.get_last_agent_message(project_id)
    db_status = last_msg["status"] if last_msg else "none"

    # 2. 查内存：是否正在运行
    state = _running_state.get(project_id)
    if state:
        return {
            "db_status": db_status,
            "backend_running": True,
            "memory": {"steps": state.get("steps", []), "text": state.get("text", ""), "cards": state.get("cards", [])},
        }

    # 3. 内存无数据，查 DB 兜底（agent 已完成但 _running_state 已清理）
    if db_status == "completed" and last_msg:
        cards_raw = []
        for c in (last_msg.get("cards") or []):
            if c.get("card_type") == "slides" and c.get("card_data"):
                cards_raw.append(c["card_data"])
        return {
            "db_status": "completed",
            "backend_running": False,
            "memory": {
                "steps": last_msg.get("steps") or [],
                "text": last_msg.get("content") or "",
                "cards": cards_raw,
            },
        }

    # 4. 不在运行也不是 completed → 异常或无数据
    return {
        "db_status": db_status,
        "backend_running": False,
        "memory": None,
    }
