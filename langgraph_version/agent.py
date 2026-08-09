"""
LangGraph 对话 Agent（RAG 优先答疑模式）

基于 langgraph.prebuilt.create_react_agent 构建一个「答疑助手」：
用户提问 → 优先检索面试/笔试经验知识库（interview_kb，RAG）
    → 命中：整理参考答案回答 + 推荐 5 道相关题目
    → 未命中：直接由大模型回答，并注明"题库暂无收录，以下为模型回答"
简历/JD 相关请求仍走 analyze_jd / optimize_resume 工具。

工具（3 个）：
    1. answer_from_kb   从面试题库语义检索相关题目（含参考答案/考察点）
    2. analyze_jd       分析岗位描述，输出结构化需求
    3. optimize_resume  针对 JD 优化简历（走 LangGraph 流水线）

多轮记忆：MemorySaver 检查点，按 session_id / thread_id 隔离。

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
# 工具定义
# ──────────────────────────────────────────────
@tool
def answer_from_kb(question: str, top_k: int = 5) -> list[dict[str, Any]]:
    """从面试/笔试经验知识库（RAG）检索与 question 相关的题目及答案。

    用于回答用户提出的面试/求职/技术类问题：先查题库看是否已有收录，
    命中则返回题目、参考答案、考察点，供整理回答与推荐相关题目。
    """
    from interview_knowledge_base import search_questions

    try:
        return search_questions(question, top_k=top_k, max_distance=0.6)
    except Exception as e:  # noqa: BLE001
        logger.warning("answer_from_kb 检索失败: %s", e)
        return []


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

    会按「定制简历原则」改写简历并构建简历-JD 匹配关系表，
    不虚构经历。返回优化后简历全文、匹配表与岗位分析。
    """
    from graph import run_optimize

    try:
        return run_optimize(resume_text, jd_text)
    except Exception as e:  # noqa: BLE001
        logger.warning("optimize_resume 工具执行失败: %s", e)
        return {"error": str(e), "optimized_text": ""}


# 工具注册表
TOOLS = [answer_from_kb, analyze_jd, optimize_resume]


# ──────────────────────────────────────────────
# 系统提示词（RAG 优先答疑）
# ──────────────────────────────────────────────
SYSTEM_PROMPT = """你是一位专业的求职答疑助手，服务求职者与面试准备者。回答用户问题时遵循以下流程：

【答疑流程】
1. 用户提出问题时，**优先调用 answer_from_kb 工具**，从面试/笔试经验知识库检索相关内容。
2. 如果题库有命中（检索结果非空）：
   - 基于命中的参考答案，用通俗清晰的语言整理回答用户的问题。
   - 回答末尾**推荐 5 道相关题目**（从命中的题目中挑选，列出题目名称，可附简要考察点）。
3. 如果题库未命中（检索结果为空）：
   - 直接用你自身的大模型知识回答用户问题。
   - 回答开头注明「本题库暂无收录，以下为模型回答」。
4. 如果用户请求与简历优化 / 岗位分析相关（如"帮我改简历""分析这段 JD"），
   则调用 analyze_jd / optimize_resume 工具处理，不套用答疑流程。

【回答要求】
- 回答准确、克制、结构化，必要时用列表分点。
- 引用题库内容时基于检索结果，不要编造题目或答案。
- 推荐题目仅从检索命中的题目中选择。
- 不确定的内容明确说明。"""


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
        prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
    logger.info("get_agent：RAG 优先答疑 Agent 构建完成（MemorySaver 记忆）")
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
