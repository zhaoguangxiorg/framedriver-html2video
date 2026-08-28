# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""ask_user 工具：人工介入机制的核心工具。

LLM 调用此工具向用户提问，工具内部通过 LangGraph interrupt() 阻塞等待用户作答，
用户提交答案后智能体恢复执行，工具返回格式化后的答案文本给 LLM。
"""

from typing import List, Literal

import uuid

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt
from pydantic import BaseModel


class Option(BaseModel):
    """选项定义。"""

    key: str    # 选项标识，如 "A"、"B"
    label: str  # 选项展示文本，如 "商务蓝"


class Question(BaseModel):
    """单个问题定义。"""

    question_id: str            # 问题唯一标识，如 "q1"
    type: Literal["single_choice", "multi_choice", "text", "confirm"]  # 问题类型
    text: str                   # 问题文本
    options: List[Option] = []  # 选项列表（single_choice/multi_choice 需要，text/confirm 为空）
    required: bool = True       # 是否必填
    placeholder: str = ""       # 文本输入提示（text 类型用）
    confirm_text: str = "确认"   # 确认按钮文本（confirm 类型用，其他类型忽略）
    cancel_text: str = "取消"    # 取消按钮文本（confirm 类型用，其他类型忽略）


@tool
def ask_user(questions: List[Question], config: RunnableConfig) -> str:
    """向用户提问，阻塞等待用户作答。

    当你需要用户确认、决策或补充信息时调用此工具。
    一次可提出多个问题，用户将逐题作答。
    confirm 类型的问题不会与其他类型混合出现，应单独调用。

    Args:
        questions: 问题列表，每个问题包含 question_id、type、text 等字段。
        config: LangGraph 运行时配置，用于获取 project_id（对 LLM 隐藏）。
    """
    # 1. 从 config 获取 project_id（与 init_project 等工具一致）
    configurable = config.get("configurable", {})
    project_id = configurable.get("project_id")
    if not project_id:
        raise ValueError(
            "project_id not found in config. "
            "Please pass project_id via config['configurable']['project_id']"
        )

    # 2. 校验 question_id 唯一性
    qids = [q.question_id for q in questions]
    if len(qids) != len(set(qids)):
        raise ValueError("question_id 重复，请确保每个问题的 question_id 唯一")

    # 3. confirm 类型校验：questions 数组长度必须为 1
    has_confirm = any(q.type == "confirm" for q in questions)
    if has_confirm and len(questions) != 1:
        raise ValueError("confirm 类型问题必须单独调用，questions 数组长度只能为 1")

    # 4. 生成 intervention_id
    intervention_id = str(uuid.uuid4())

    # 5. 构造 interrupt value
    value = {
        "type": "human_intervention",
        "intervention_id": intervention_id,
        "questions": [q.model_dump() for q in questions],
    }

    # 6. 调用 interrupt() 阻塞等待用户作答
    #    返回值即 Command(resume=answers) 传入的 answers 列表
    answers = interrupt(value)

    # 7. 格式化答案为 LLM 可读文本并返回
    return _format_answers_for_llm(questions, answers)


def _format_answers_for_llm(questions: List[Question], answers: list) -> str:
    """格式化答案为 LLM 可读的文本。

    Args:
        questions: 问题列表，用于确定输出顺序。
        answers: 用户提交的答案列表，格式为
                 [{"question_id": "q1", "answer": "A"},
                  {"question_id": "q2", "answer": ["intro", "case"]},
                  ...]

    Returns:
        格式化后的文本，每行一个问题及其答案：
            q1: A
            q2: intro, case, 其他:xxx
            q3: 用户输入文本
    """
    other_prefix = "OTHER:"
    # 按 question_id 建立答案索引
    answer_map = {a.get("question_id"): a.get("answer") for a in answers}

    lines = []
    for q in questions:
        ans = answer_map.get(q.question_id)
        if isinstance(ans, list):
            # 多选：逐项解析 OTHER 前缀
            parts = []
            for item in ans:
                if isinstance(item, str) and item.startswith(other_prefix):
                    parts.append(f"其他:{item[len(other_prefix):]}")
                else:
                    parts.append(str(item))
            ans_text = ", ".join(parts)
        elif isinstance(ans, bool):
            # confirm：bool → "确认" / "取消"
            ans_text = "确认" if ans else "取消"
        elif isinstance(ans, str) and ans.startswith(other_prefix):
            # 单选：解析 OTHER 前缀
            ans_text = f"其他:{ans[len(other_prefix):]}"
        else:
            ans_text = str(ans)
        lines.append(f"{q.question_id}: {ans_text}")

    return "\n".join(lines)
