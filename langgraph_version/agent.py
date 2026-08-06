"""
LangGraph 对话 Agent（ReAct 智能体）

基于 langgraph.prebuilt.create_react_agent 构建一个能调用
「简历优化领域工具」的对话助手，并通过 MemorySaver 检查点实现
多轮会话记忆（按 session_id / thread_id 隔离）。

4 个工具（语义同 LangChain 版）：
    1. analyze_jd         分析岗位描述，输出结构化需求
    2. optimize_resume    针对 JD 优化简历（走 LangGraph 流水线）
    3. search_jobs        检索岗位知识库（RAG，按语义匹配）
    4. get_premium_jobs   获取大厂/高频优质岗位

导出接口：
    get_agent()                       获取带 MemorySaver 的 ReAct Agent（单例）
    chat_with_agent(user_input, session_id) -> str
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 工具定义（LangChain 版语义）
# ──────────────────────────────────────────────
@tool
def analyze_jd(jd_text: str) -> dict[str, Any]:
    """分析岗位描述（JD），提取结构化需求信息。

    适用于用户粘贴一段岗位描述时，提取：
    核心必备技能、加分技能、岗位职责、经验要求、关键词。
    """
    from jd_analyzer import analyze_jd as _analyze

    try:
        return _analyze(jd_text)
    except Exception as e:  # noqa: BLE001
        logger.warning("analyze_jd 工具执行失败: %s", e)
        return {"error": str(e)}


@tool
def optimize_resume(resume_text: str, jd_text: str) -> dict[str, Any]:
    """针对目标岗位 JD 优化简历内容。

    会按「定制简历九大原则」改写简历并构建简历-JD 匹配关系表，
    不虚构经历。返回优化后简历全文、匹配表与岗位分析。
    """
    from graph import run_optimize

    try:
        return run_optimize(resume_text, jd_text)
    except Exception as e:  # noqa: BLE001
        logger.warning("optimize_resume 工具执行失败: %s", e)
        return {"error": str(e), "optimized_text": ""}


@tool
def search_jobs(query: str, top_k: int = 10) -> list[dict[str, Any]]:
    """从岗位知识库检索与 query 最匹配的岗位（按语义向量检索）。

    query 可为技能、岗位名或公司名，如 "Python 后端"。
    """
    from jd_knowledge_base import search_jds

    try:
        return search_jds(query, top_k=top_k)
    except Exception as e:  # noqa: BLE001
        logger.warning("search_jobs 工具执行失败: %s", e)
        return []


@tool
def get_premium_jobs(limit: int = 20) -> list[dict[str, Any]]:
    """获取岗位知识库中的大厂/高频优质岗位推荐列表。"""
    from jd_knowledge_base import get_premium_jobs as _get_premium

    try:
        return _get_premium(limit=limit)
    except Exception as e:  # noqa: BLE001
        logger.warning("get_premium_jobs 工具执行失败: %s", e)
        return []


# 工具注册表
TOOLS = [analyze_jd, optimize_resume, search_jobs, get_premium_jobs]


# ──────────────────────────────────────────────
# Agent 构建与对话
# ──────────────────────────────────────────────
@lru_cache(maxsize=1)
def get_agent():
    """获取带 MemorySaver 检查点的 ReAct Agent（单例缓存）。

    每次调用按 session_id（thread_id）持久化会话状态，
    实现多轮对话记忆。
    """
    try:
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.prebuilt import create_react_agent
    except ImportError as e:
        raise ImportError(
            "缺少依赖 langgraph，请执行: pip install langgraph langgraph-checkpoint"
        ) from e

    from llm_client import get_llm

    model = get_llm()
    checkpointer = MemorySaver()

    agent = create_react_agent(
        model=model,
        tools=TOOLS,
        checkpointer=checkpointer,
    )
    logger.info("get_agent：ReAct Agent 构建完成（MemorySaver 记忆）")
    return agent


def chat_with_agent(user_input: str, session_id: str) -> str:
    """与 Agent 对话，返回回复文本。

    通过 config={"configurable": {"thread_id": session_id}}
    实现按 session 隔离的多轮记忆：同一 session_id 的多次对话
    共享同一会话上下文。
    """
    if not user_input or not user_input.strip():
        return "（请输入内容后再发送）"

    # Mock 模式（无 API Key）：不构建真实 Agent，直接返回模拟回复
    import llm_client

    if llm_client.mock_enabled():
        logger.info("[MOCK] 对话模式：返回模拟回复")
        return llm_client.chat(user_input)

    agent = get_agent()
    logger.info("chat_with_agent：session=%s 收到输入 %d 字", session_id, len(user_input))

    result = agent.invoke(
        {"messages": [{"role": "user", "content": user_input.strip()}]},
        config={"configurable": {"thread_id": session_id}},
    )

    messages = result.get("messages") or []
    if not messages:
        return "（Agent 没有返回内容，请稍后再试）"

    reply = messages[-1].content
    return str(reply)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    print(chat_with_agent("你好，你能帮我做什么？", "test-session-001"))
